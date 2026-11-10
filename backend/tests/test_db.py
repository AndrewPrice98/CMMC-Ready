import json
import sqlite3
from pathlib import Path

import pytest

from cmmcready import db
from cmmcready.catalog import load_catalog
from cmmcready.evidence.engine import DEFAULT_ODP

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    with open(FIXTURES / name, encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture
def assessment(conn):
    org_id = conn.execute("INSERT INTO organization (name) VALUES ('Test Org (fictional)')").lastrowid
    return db.create_assessment(conn, org_id, "Test assessment")


def test_assessor_answer_wins_and_conflict_flagged(conn, assessment):
    # windows-noncompliant reports 3.1.8[a] as not met (lockout threshold too high).
    db.add_evidence(conn, assessment, load("windows-noncompliant.json"))
    for req in load_catalog().requirements:
        for obj in req.objectives:
            db.set_answer(conn, assessment, obj.id, "met")
    db.set_answer(conn, assessment, "3.1.8[a]", "met", note="Policy applied by GPO")
    view = db.objective_view(conn, assessment, "3.1.8[a]")
    assert view["answer"] == "met"  # the assessor's answer stands
    assert view["conflict"] is True
    assert any(f["result"] == "not_met" for f in view["findings"])
    assert view["note"] == "Policy applied by GPO"
    # The score uses the assessor's answer, not the finding.
    assert db.current_score(conn, assessment).score == 110


def test_conflict_when_answer_not_met_and_every_finding_met(conn, assessment):
    db.add_evidence(conn, assessment, load("windows-compliant.json"))
    db.set_answer(conn, assessment, "3.1.8[a]", "not_met")
    view = db.objective_view(conn, assessment, "3.1.8[a]")
    assert view["findings"] and all(f["result"] == "met" for f in view["findings"])
    assert view["conflict"] is True


def test_no_conflict_cases(conn, assessment):
    db.add_evidence(conn, assessment, load("windows-compliant.json"))
    db.set_answer(conn, assessment, "3.1.8[a]", "met")
    assert db.objective_view(conn, assessment, "3.1.8[a]")["conflict"] is False
    # Unanswered and N/A never conflict.
    assert db.objective_view(conn, assessment, "3.1.8[b]")["conflict"] is False
    db.set_answer(conn, assessment, "3.1.8[b]", "na", justification="Not used")
    assert db.objective_view(conn, assessment, "3.1.8[b]")["conflict"] is False
    # No findings at all: nothing to conflict with, in either direction.
    db.set_answer(conn, assessment, "3.1.2[a]", "not_met")
    view = db.objective_view(conn, assessment, "3.1.2[a]")
    assert view["findings"] == [] and view["conflict"] is False


def test_not_assessed_findings_do_not_conflict(conn, assessment):
    db.add_evidence(conn, assessment, load("windows-compliant.json"))
    for answer in ("met", "not_met"):
        db.set_answer(conn, assessment, "3.1.1[d]", answer)
        view = db.objective_view(conn, assessment, "3.1.1[d]")
        assert [f["result"] for f in view["findings"]] == ["not_assessed"]
        assert view["conflict"] is False


def test_na_requires_justification(conn, assessment):
    with pytest.raises(ValueError):
        db.set_answer(conn, assessment, "3.1.16[a]", "na")
    with pytest.raises(ValueError):
        db.set_answer(conn, assessment, "3.1.16[a]", "na", justification="   ")
    db.set_answer(conn, assessment, "3.1.16[a]", "na", justification="No wireless in the boundary")
    assert db.get_answers(conn, assessment)["3.1.16[a]"] == "na"


def test_set_answer_validates_and_clears(conn, assessment):
    with pytest.raises(ValueError):
        db.set_answer(conn, assessment, "9.9.9[a]", "met")
    with pytest.raises(ValueError):
        db.set_answer(conn, assessment, "3.1.1[a]", "maybe")
    db.set_answer(conn, assessment, "3.1.1[a]", "met")
    db.set_answer(conn, assessment, "3.1.1[a]", "unanswered")
    assert "3.1.1[a]" not in db.get_answers(conn, assessment)


def test_findings_are_stored_at_upload_and_survive_reevaluation(conn, assessment):
    evidence_id = db.add_evidence(conn, assessment, load("windows-compliant.json"))
    count = "SELECT COUNT(*) FROM findings WHERE evidence_id = ?"
    stored = conn.execute(count, (evidence_id,)).fetchone()[0]
    assert stored > 0
    assert db.reevaluate_evidence(conn, assessment) == 1
    assert conn.execute(count, (evidence_id,)).fetchone()[0] == stored


def test_reevaluation_follows_changed_odp(conn, assessment):
    db.add_evidence(conn, assessment, load("windows-compliant.json"))
    # The compliant host has a 14-character minimum; a 16-character ODP makes it not met.
    assert db.objective_view(conn, assessment, "3.5.7[a]")["findings"][0]["result"] == "met"
    db.set_odp(conn, assessment, {**DEFAULT_ODP, "min_password_length": 16})
    db.reevaluate_evidence(conn, assessment)
    assert db.objective_view(conn, assessment, "3.5.7[a]")["findings"][0]["result"] == "not_met"
    with pytest.raises(ValueError):
        db.set_odp(conn, assessment, {"min_password_length": 0})


def test_unrecognised_evidence_stores_nothing(conn, assessment):
    with pytest.raises(ValueError):
        db.add_evidence(conn, assessment, {"collector": "other"})
    assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 0


def test_partial_choice_validated_and_scored(conn, assessment):
    with pytest.raises(ValueError):
        db.set_partial_choice(conn, assessment, "3.1.1", "mfa_remote_privileged_only")
    db.set_partial_choice(conn, assessment, "3.5.3", "mfa_remote_privileged_only")
    assert db.get_assessment(conn, assessment)["partial_choices"] == {"3.5.3": "mfa_remote_privileged_only"}
    db.set_partial_choice(conn, assessment, "3.5.3", None)
    assert db.get_assessment(conn, assessment)["partial_choices"] == {}


def test_asset_category_check_constraint(conn, assessment):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO assets (org_id, name, category) VALUES (1, 'x', 'bogus')")
