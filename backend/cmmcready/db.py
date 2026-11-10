"""SQLite storage for organizations, assessments, answers, evidence and POA&M items.

The score is never stored: it is always computed from ``answers`` through
``scoring.score``. All SQL is parameterized.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .catalog import load_catalog
from .evidence.engine import DEFAULT_ODP, EvidenceFinding, evaluate
from .scoring import ScoreResult, score

SCHEMA = """
CREATE TABLE IF NOT EXISTS organization (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    cage_codes    TEXT NOT NULL DEFAULT '',
    description   TEXT NOT NULL DEFAULT '',
    cui_boundary  TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS assets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id      INTEGER NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL
                CHECK (category IN ('cui','spa','crma','specialized','out_of_scope')),
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS assessments (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id                INTEGER NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    title                 TEXT NOT NULL,
    started_at            TEXT NOT NULL,
    completed_at          TEXT,
    odp_json              TEXT NOT NULL DEFAULT '{}',
    partial_choices_json  TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS answers (
    assessment_id  INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    objective_id   TEXT NOT NULL,
    answer         TEXT NOT NULL CHECK (answer IN ('met','not_met','na')),
    note           TEXT NOT NULL DEFAULT '',
    justification  TEXT NOT NULL DEFAULT '',
    answered_at    TEXT NOT NULL,
    PRIMARY KEY (assessment_id, objective_id)
);

CREATE TABLE IF NOT EXISTS evidence (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    collector     TEXT NOT NULL,
    collected_at  TEXT NOT NULL,
    host          TEXT NOT NULL,
    raw_json      TEXT NOT NULL,
    uploaded_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS findings (
    evidence_id   INTEGER NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
    objective_id  TEXT NOT NULL,
    result        TEXT NOT NULL CHECK (result IN ('met','not_met','not_assessed')),
    check_id      TEXT NOT NULL,
    detail        TEXT NOT NULL DEFAULT '',
    -- supporting detail for the UI, from the same evaluation
    rule_id       TEXT NOT NULL DEFAULT '',
    expected      TEXT NOT NULL DEFAULT '',
    observed_json TEXT NOT NULL DEFAULT 'null',
    partial_hint  TEXT
);
CREATE INDEX IF NOT EXISTS idx_findings_evidence  ON findings(evidence_id);
CREATE INDEX IF NOT EXISTS idx_findings_objective ON findings(objective_id);

CREATE TABLE IF NOT EXISTS poam_items (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id  INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    req_id         TEXT NOT NULL,
    weakness       TEXT NOT NULL,
    remediation    TEXT NOT NULL DEFAULT '',
    owner          TEXT NOT NULL DEFAULT '',
    milestone_json TEXT NOT NULL DEFAULT '[]',
    due_date       TEXT,
    status         TEXT NOT NULL DEFAULT 'open'
                   CHECK (status IN ('open','in_progress','closed'))
);
CREATE INDEX IF NOT EXISTS idx_evidence_assessment ON evidence(assessment_id);
CREATE INDEX IF NOT EXISTS idx_poam_assessment     ON poam_items(assessment_id);
"""

BUSY_TIMEOUT_SECONDS = 15.0
ANSWER_VALUES = ("met", "not_met", "na")


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tx(conn: sqlite3.Connection, commit: bool):
    """Commit on success when ``commit`` is true; otherwise leave the surrounding
    transaction (opened by the caller) alone."""
    return conn if commit else nullcontext()


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open the database, creating it and its schema if needed."""
    path = Path(path or config.db_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    # FastAPI may run a dependency and its endpoint on different worker threads;
    # each request still gets its own connection.
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_SECONDS, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    return conn


# -- organization and assessments ----------------------------------------------------------

def get_organization(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT * FROM organization ORDER BY id LIMIT 1").fetchone()
    return dict(row) if row else None


def create_assessment(
    conn: sqlite3.Connection, org_id: int, title: str, *, started_at: str | None = None,
    odp: dict | None = None, partial_choices: dict | None = None,
    commit: bool = True,
) -> int:
    with _tx(conn, commit):
        cur = conn.execute(
            "INSERT INTO assessments (org_id, title, started_at, odp_json, partial_choices_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (org_id, title, started_at or now_utc(),
             json.dumps({**DEFAULT_ODP, **(odp or {})}), json.dumps(partial_choices or {})),
        )
    return int(cur.lastrowid)


def _assessment_dict(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["odp"] = {**DEFAULT_ODP, **json.loads(out.pop("odp_json"))}
    out["partial_choices"] = json.loads(out.pop("partial_choices_json"))
    return out


def get_assessment(conn: sqlite3.Connection, assessment_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM assessments WHERE id = ?", (assessment_id,)).fetchone()
    return _assessment_dict(row) if row else None


def list_assessments(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM assessments ORDER BY started_at DESC, id DESC").fetchall()
    return [_assessment_dict(r) for r in rows]


def set_odp(conn: sqlite3.Connection, assessment_id: int, odp: dict) -> None:
    """Replace the assessment's organization-defined parameters. Call
    ``reevaluate_evidence`` afterwards so stored findings follow the new values."""
    merged = {**DEFAULT_ODP, **odp}
    for name, value in merged.items():
        if name in DEFAULT_ODP and (isinstance(value, bool) or not isinstance(value, (int, float))
                                    or value <= 0):
            raise ValueError(f"ODP {name} must be a positive number")
    with conn:
        conn.execute("UPDATE assessments SET odp_json = ? WHERE id = ?",
                     (json.dumps(merged), assessment_id))


def set_partial_choice(conn: sqlite3.Connection, assessment_id: int, req_id: str,
                       choice: str | None) -> None:
    req = load_catalog().by_id(req_id)
    if choice is not None and not (req and req.partial and choice in req.partial):
        raise ValueError(f"{choice!r} is not a partial-credit choice for {req_id}")
    assessment = get_assessment(conn, assessment_id)
    if assessment is None:
        raise ValueError("unknown assessment")
    choices = assessment["partial_choices"]
    if choice is None:
        choices.pop(req_id, None)
    else:
        choices[req_id] = choice
    with conn:
        conn.execute("UPDATE assessments SET partial_choices_json = ? WHERE id = ?",
                     (json.dumps(choices), assessment_id))


# -- answers and score ---------------------------------------------------------------------

def _objective_ids() -> set[str]:
    return {o.id for r in load_catalog().requirements for o in r.objectives}


def set_answer(
    conn: sqlite3.Connection, assessment_id: int, objective_id: str, answer: str,
    note: str = "", justification: str = "", answered_at: str | None = None,
) -> None:
    """Record the assessor's answer. ``unanswered`` clears it. N/A needs a justification."""
    if objective_id not in _objective_ids():
        raise ValueError(f"unknown objective {objective_id!r}")
    if answer == "unanswered":
        with conn:
            conn.execute("DELETE FROM answers WHERE assessment_id = ? AND objective_id = ?",
                         (assessment_id, objective_id))
        return
    if answer not in ANSWER_VALUES:
        raise ValueError(f"answer must be one of {', '.join(ANSWER_VALUES)} or unanswered")
    if answer == "na" and not justification.strip():
        raise ValueError("Not applicable needs a justification")
    with conn:
        conn.execute(
            "INSERT INTO answers (assessment_id, objective_id, answer, note, justification, answered_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(assessment_id, objective_id) DO UPDATE SET answer = excluded.answer, "
            "note = excluded.note, justification = excluded.justification, "
            "answered_at = excluded.answered_at",
            (assessment_id, objective_id, answer, note, justification, answered_at or now_utc()),
        )


def get_answers(conn: sqlite3.Connection, assessment_id: int) -> dict[str, str]:
    rows = conn.execute("SELECT objective_id, answer FROM answers WHERE assessment_id = ?",
                        (assessment_id,)).fetchall()
    return {r["objective_id"]: r["answer"] for r in rows}


def current_score(conn: sqlite3.Connection, assessment_id: int) -> ScoreResult:
    """The score for an assessment, always computed from its answers."""
    assessment = get_assessment(conn, assessment_id)
    if assessment is None:
        raise ValueError("unknown assessment")
    return score(load_catalog(), get_answers(conn, assessment_id), assessment["partial_choices"])


# -- evidence and findings ------------------------------------------------------------------

def _host_label(data: dict) -> str:
    if data.get("collector") == "windows":
        return str(data.get("host", {}).get("name") or "unknown host")
    return str(data.get("tenant", {}).get("id") or "unknown tenant")


def _replace_findings(conn: sqlite3.Connection, evidence_id: int,
                      findings: list[EvidenceFinding]) -> None:
    conn.execute("DELETE FROM findings WHERE evidence_id = ?", (evidence_id,))
    conn.executemany(
        "INSERT INTO findings (evidence_id, objective_id, result, check_id, detail, rule_id, "
        "expected, observed_json, partial_hint) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(evidence_id, f.objective_id, f.result, f.check_id, f.detail, f.rule_id, f.expected,
          json.dumps(f.observed, sort_keys=True, default=str), f.partial_hint) for f in findings],
    )


def add_evidence(conn: sqlite3.Connection, assessment_id: int, collector_json: dict,
                 uploaded_at: str | None = None, commit: bool = True) -> int:
    """Store a collector file and the findings it produces. Raises ValueError when the
    file is not recognised collector output; nothing is stored in that case.
    ``commit=False`` leaves the commit to the caller's transaction."""
    assessment = get_assessment(conn, assessment_id)
    if assessment is None:
        raise ValueError("unknown assessment")
    findings = evaluate(collector_json, assessment["odp"])
    with _tx(conn, commit):
        cur = conn.execute(
            "INSERT INTO evidence (assessment_id, collector, collected_at, host, raw_json, uploaded_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (assessment_id, collector_json["collector"], str(collector_json.get("collected_at", "")),
             _host_label(collector_json), json.dumps(collector_json, sort_keys=True),
             uploaded_at or now_utc()),
        )
        _replace_findings(conn, cur.lastrowid, findings)
    return int(cur.lastrowid)


def reevaluate_evidence(conn: sqlite3.Connection, assessment_id: int) -> int:
    """Re-run the stored raw evidence through the engine with the assessment's current
    organization-defined parameters and replace its findings. Returns the number of
    evidence files processed. Answers are never touched."""
    assessment = get_assessment(conn, assessment_id)
    if assessment is None:
        raise ValueError("unknown assessment")
    rows = conn.execute("SELECT id, raw_json FROM evidence WHERE assessment_id = ? ORDER BY id",
                        (assessment_id,)).fetchall()
    with conn:
        for row in rows:
            _replace_findings(conn, row["id"], evaluate(json.loads(row["raw_json"]), assessment["odp"]))
    return len(rows)


def list_evidence(conn: sqlite3.Connection, assessment_id: int) -> list[dict]:
    """Evidence files for an assessment (without the raw JSON)."""
    rows = conn.execute(
        "SELECT id, assessment_id, collector, collected_at, host, uploaded_at FROM evidence "
        "WHERE assessment_id = ? ORDER BY id", (assessment_id,)).fetchall()
    return [dict(r) for r in rows]


# -- the objective view ---------------------------------------------------------------------

def objective_view(conn: sqlite3.Connection, assessment_id: int, objective_id: str) -> dict:
    """The assessor's answer next to the automated findings for one objective.

    The assessor's answer always stands and is what the score uses. ``conflict`` is
    true when the answer is ``met`` and any finding is ``not_met``, or the answer is
    ``not_met`` and every finding is ``met``.
    """
    row = conn.execute(
        "SELECT answer, note, justification FROM answers WHERE assessment_id = ? AND objective_id = ?",
        (assessment_id, objective_id)).fetchone()
    answer, note, justification = (
        (row["answer"], row["note"], row["justification"]) if row else ("unanswered", "", ""))
    rows = conn.execute(
        "SELECT f.evidence_id, e.host, e.collector, e.collected_at, f.result, f.check_id, f.detail, "
        "f.rule_id, f.expected, f.observed_json, f.partial_hint "
        "FROM findings f JOIN evidence e ON e.id = f.evidence_id "
        "WHERE e.assessment_id = ? AND f.objective_id = ? ORDER BY e.id, f.check_id, f.rule_id",
        (assessment_id, objective_id)).fetchall()
    findings = []
    for r in rows:
        item = dict(r)
        item["observed"] = json.loads(item.pop("observed_json"))
        findings.append(item)
    results = [f["result"] for f in findings]
    conflict = bool(findings) and (
        (answer == "met" and "not_met" in results)
        or (answer == "not_met" and all(r == "met" for r in results))
    )
    return {"answer": answer, "note": note, "justification": justification,
            "findings": findings, "conflict": conflict}
