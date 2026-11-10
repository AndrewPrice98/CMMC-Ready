from datetime import date

import pytest

from cmmcready import db
from cmmcready.catalog import load_catalog
from cmmcready.poam import default_due_date, generate_poam
from cmmcready.scoring import score


def _all_unmet(catalog, ids):
    return {o.id: "not_met" for rid in ids for o in catalog.by_id(rid).objectives}


def _drafts(ids, partial=None):
    catalog = load_catalog()
    partial = partial or {}
    result = score(catalog, _all_unmet(catalog, ids), partial)
    return {d.req_id: d for d in generate_poam(catalog, result, [], partial, "2026-10-12")
            if d.req_id in ids}


def test_poam_respects_rules():
    catalog = load_catalog()
    five = next(r.id for r in catalog.requirements if r.weight == 5)
    one = next(r.id for r in catalog.requirements
               if r.weight == 1 and r.poam_allowed and r.id != "3.13.11")
    drafts = _drafts([five, one, "3.1.20", "3.13.11"], {"3.13.11": "encryption_not_fips"})
    assert drafts[five].allowed is False and "32 CFR §170.21(a)(2)" in drafts[five].reason
    assert drafts[one].allowed and drafts[one].reason == ""
    assert drafts["3.1.20"].allowed is False and "32 CFR §170.21(a)(2)" in drafts["3.1.20"].reason
    assert drafts["3.13.11"].allowed is True   # 3-point partial


def test_missing_ssp_gets_a_not_allowed_draft():
    catalog = load_catalog()
    # 3.12.4 unanswered: the SSP is missing, though no points are deducted for it.
    answers = {o.id: "met" for r in catalog.requirements for o in r.objectives}
    for o in catalog.by_id("3.12.4").objectives:
        answers[o.id] = "unanswered"
    result = score(catalog, answers, {})
    assert result.ssp_missing and not result.deductions
    drafts = {d.req_id: d for d in generate_poam(catalog, result, [], {}, "2026-10-12")}
    d = drafts["3.12.4"]
    assert d.allowed is False and d.points == 0 and "170.21(a)(2)" in d.reason
    assert "system security plan" in d.reason
    # An existing item suppresses the draft, as for any other requirement.
    assert not [x for x in generate_poam(catalog, result, ["3.12.4"], {}, "2026-10-12")]
    # Once the plan is in place there is no draft.
    answers.update({o.id: "met" for o in catalog.by_id("3.12.4").objectives})
    assert not generate_poam(catalog, score(catalog, answers, {}), [], {}, "2026-10-12")


def test_fips_without_partial_not_allowed():
    d = _drafts(["3.13.11"])["3.13.11"]
    assert d.allowed is False and d.points == 5 and "170.21" in d.reason


def test_existing_items_skipped_and_unassessed_ignored():
    catalog = load_catalog()
    result = score(catalog, _all_unmet(catalog, ["3.1.3"]), {})
    out = generate_poam(catalog, result, [{"req_id": "3.1.3"}], {}, "2026-10-12")
    # Everything else is merely unassessed; only the missing SSP (3.12.4) is a finding.
    assert [d.req_id for d in out] == ["3.12.4"]


def test_due_date_180():
    assert default_due_date("2026-10-12") == "2027-04-10"
    assert default_due_date(date(2026, 1, 1)) == "2026-06-30"
    assert _drafts(["3.1.3"])["3.1.3"].due_date == "2027-04-10"


def test_poam_status_check_constraint(conn):
    conn.execute("INSERT INTO organization (name) VALUES ('o')")
    aid = db.create_assessment(conn, 1, "t")
    for status in ("open", "in_progress", "closed"):
        conn.execute("INSERT INTO poam_items (assessment_id, req_id, weakness, status) "
                     "VALUES (?, '3.1.3', 'w', ?)", (aid, status))
    with pytest.raises(Exception):
        conn.execute("INSERT INTO poam_items (assessment_id, req_id, weakness, status) "
                     "VALUES (?, '3.1.3', 'w', 'done')", (aid,))
