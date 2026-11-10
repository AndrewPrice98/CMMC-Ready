import importlib.util
import json
from collections import Counter
from pathlib import Path

import pytest

from cmmcready import config, db, demo
from cmmcready.catalog import load_catalog

BACKEND = Path(__file__).resolve().parent.parent


@pytest.fixture
def seeded(conn):
    assert demo.seed(conn) is True
    titles = {a["title"]: a["id"] for a in db.list_assessments(conn)}
    current = next(i for t, i in titles.items() if t.startswith("Annual"))
    previous = next(i for t, i in titles.items() if t.startswith("Initial"))
    return conn, current, previous


def test_demo_scores(seeded):
    conn, current, previous = seeded
    now = db.current_score(conn, current)
    assert 85 <= now.score <= 87
    assert not now.conditional_eligible
    # Not eligible for two reasons: below 88, and a 3-point gap that cannot go on a POA&M.
    catalog = load_catalog()
    blockers = [d for d in now.deductions if not catalog.by_id(d.req_id).poam_allowed]
    assert any(d.points == 3 for d in blockers)
    assert {d.req_id for d in blockers} == {"3.5.3", "3.8.8"}
    rest = [d for d in now.deductions if d.req_id not in ("3.5.3", "3.8.8")]
    assert rest and all(d.points == 1 for d in rest)
    assert not now.provisional and not now.ssp_missing

    before = db.current_score(conn, previous)
    assert 35 <= before.score <= 45
    assert before.ssp_missing and before.provisional


def test_demo_identity_and_assets(seeded):
    conn, current, previous = seeded
    org = db.get_organization(conn)
    assert org["name"].endswith("(fictional)") and org["cage_codes"] == "DEMO1"
    assets = conn.execute("SELECT category FROM assets").fetchall()
    assert len(assets) == 12
    assert {a["category"] for a in assets} == {"cui", "spa", "crma", "specialized", "out_of_scope"}
    first, second = db.get_assessment(conn, previous), db.get_assessment(conn, current)
    assert first["started_at"][:7] == "2026-06" and second["started_at"][:7] == "2026-10"
    assert second["partial_choices"] == {"3.5.3": "mfa_remote_privileged_only"}


def test_demo_has_conflicts_and_na(seeded):
    conn, current, _ = seeded
    views = {o.id: db.objective_view(conn, current, o.id)
             for r in load_catalog().requirements for o in r.objectives}
    conflicts = [oid for oid, v in views.items() if v["conflict"]]
    assert len(conflicts) >= 3
    assert {views[oid]["answer"] for oid in conflicts} == {"met", "not_met"}  # both directions

    na = conn.execute("SELECT objective_id, justification FROM answers "
                      "WHERE assessment_id = ? AND answer = 'na'", (current,)).fetchall()
    assert na and all(row["justification"].strip() for row in na)
    assert "3.1.16" in {row["objective_id"].rsplit("[", 1)[0] for row in na}

    evidence = db.list_evidence(conn, current)
    assert Counter(e["collector"] for e in evidence) == {"windows": 2, "m365": 1}
    assert {e["host"] for e in evidence if e["collector"] == "windows"} == {"ENG-WS-01", "FS-01"}


def test_demo_poam_only_for_allowed_open_requirements(seeded):
    conn, current, _ = seeded
    catalog = load_catalog()
    rows = conn.execute("SELECT * FROM poam_items WHERE assessment_id = ?", (current,)).fetchall()
    assert len(rows) >= 10
    open_ids = {d.req_id for d in db.current_score(conn, current).deductions}
    for row in rows:
        assert catalog.by_id(row["req_id"]).poam_allowed
        assert row["req_id"] in open_ids
        assert row["owner"].strip() and row["due_date"]
        assert len(json.loads(row["milestone_json"])) >= 2


def test_demo_has_implementation_notes(seeded):
    conn, current, _ = seeded
    query = "SELECT COUNT(*) FROM answers WHERE assessment_id = ?"
    assert conn.execute(query, (current,)).fetchone()[0] == 320
    noted = conn.execute(query + " AND note != ''", (current,)).fetchone()[0]
    assert noted >= 100


def test_seed_idempotent(conn):
    tables = ("organization", "assets", "assessments", "answers", "evidence", "findings", "poam_items")

    def counts():
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}

    assert demo.seed(conn) is True
    first = counts()
    assert demo.seed(conn) is False
    assert counts() == first and first["organization"] == 1


def test_ensure_seeded_creates_database(db_file):
    demo.ensure_seeded()
    demo.ensure_seeded()
    conn = db.connect(db_file)
    try:
        assert conn.execute("SELECT COUNT(*) FROM organization").fetchone()[0] == 1
    finally:
        conn.close()


def test_committed_fixture_matches_fresh_build():
    spec = importlib.util.spec_from_file_location("build_demo", BACKEND / "scripts" / "build_demo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with open(config.DEMO_FIXTURE, encoding="utf-8") as handle:
        committed = json.load(handle)
    assert committed == json.loads(module.render())
    assert module.render() == module.render()  # deterministic
