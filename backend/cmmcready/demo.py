"""The fictional demo organization: load it into an empty database.

The data lives in ``backend/data/demo_fixture.json``, built by
``backend/scripts/build_demo.py``. Everything in it is invented.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading

from . import config, db

log = logging.getLogger(__name__)
_seed_lock = threading.Lock()


def load_fixture() -> dict:
    with open(config.DEMO_FIXTURE, encoding="utf-8") as handle:
        return json.load(handle)


def _already_seeded(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM organization LIMIT 1").fetchone() is not None


def seed(conn: sqlite3.Connection) -> bool:
    """Load the demo organization in one transaction: either everything is stored or
    nothing is. Returns False (and does nothing) if the database already has an
    organization, so calling it twice is safe."""
    if _already_seeded(conn):
        return False
    fixture = load_fixture()
    conn.commit()  # no transaction may be open when taking the write lock
    conn.execute("BEGIN IMMEDIATE")
    try:
        # Re-check under the write lock: another process may have seeded meanwhile.
        if _already_seeded(conn):
            conn.rollback()
            return False
        org = fixture["organization"]
        org_id = conn.execute(
            "INSERT INTO organization (name, cage_codes, description, cui_boundary) VALUES (?, ?, ?, ?)",
            (org["name"], org["cage_codes"], org["description"], org["cui_boundary"]),
        ).lastrowid
        conn.executemany(
            "INSERT INTO assets (org_id, name, category, description) VALUES (?, ?, ?, ?)",
            [(org_id, a["name"], a["category"], a["description"]) for a in fixture["assets"]],
        )
        for item in fixture["assessments"]:
            assessment_id = db.create_assessment(
                conn, org_id, item["title"], started_at=item["started_at"],
                odp=item["odp"], partial_choices=item["partial_choices"], commit=False)
            if item["completed_at"]:
                conn.execute("UPDATE assessments SET completed_at = ? WHERE id = ?",
                             (item["completed_at"], assessment_id))
            conn.executemany(
                "INSERT INTO answers (assessment_id, objective_id, answer, note, justification, answered_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [(assessment_id, a["objective_id"], a["answer"], a["note"], a["justification"],
                  a["answered_at"]) for a in item["answers"]],
            )
            for ev in item["evidence"]:
                db.add_evidence(conn, assessment_id, ev["raw"], uploaded_at=ev["uploaded_at"],
                                commit=False)
            conn.executemany(
                "INSERT INTO poam_items (assessment_id, req_id, weakness, remediation, owner, "
                "milestone_json, due_date, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(assessment_id, p["req_id"], p["weakness"], p["remediation"], p["owner"],
                  json.dumps(p["milestones"]), p["due_date"], p["status"]) for p in item["poam"]],
            )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return True


def ensure_seeded() -> None:
    """Create and seed the database if this instance does not have one yet."""
    with _seed_lock:
        conn = db.connect()
        try:
            if seed(conn):
                log.info("Seeded demo database at %s", config.db_path())
        finally:
            conn.close()
