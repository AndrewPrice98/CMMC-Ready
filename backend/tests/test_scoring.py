from cmmcready.catalog import load_catalog
from cmmcready.scoring import Deduction, ScoreResult, requirement_status, score, top_gaps

CAT = load_catalog()


def _all(value, skip=()):
    return {o.id: value for r in CAT.requirements if r.id not in skip for o in r.objectives}


def _answers(overrides=None, base="met"):
    a = _all(base)
    for req_id, value in (overrides or {}).items():
        for o in CAT.by_id(req_id).objectives:
            a[o.id] = value
    return a


def _ids_of_weight(w):
    return [r.id for r in CAT.requirements if r.weight == w and r.poam_allowed and r.id != "3.13.11"]


def test_all_met_scores_110():
    r = score(CAT, _all("met"), {})
    assert r.score == 110 and r.max == 110
    assert r.deductions == [] and not r.provisional and not r.ssp_missing
    assert r.not_assessed == 0 and r.conditional_eligible


def test_nothing_answered_scores_minus_203():
    r = score(CAT, {}, {})
    assert r.score == -203
    assert r.not_assessed == 110
    assert r.provisional and r.ssp_missing
    assert not r.conditional_eligible
    assert all(d.req_id != "3.12.4" for d in r.deductions)


def test_requirement_status_rollup():
    req = CAT.by_id("3.1.1")
    ids = [o.id for o in req.objectives]
    assert len(ids) >= 2
    def st(*vals):
        return requirement_status(req, dict(zip(ids, vals)))
    n = len(ids)
    assert requirement_status(req, {i: "na" for i in ids}) == "na"
    assert requirement_status(req, {i: "met" for i in ids}) == "met"
    assert st("met", "na", *["na"] * (n - 2)) == "met"
    assert requirement_status(req, {i: "unanswered" for i in ids}) == "not_assessed"
    assert requirement_status(req, {}) == "not_assessed"
    assert st("met", "unanswered", *["met"] * (n - 2)) == "not_met"
    assert st("met", "not_met", *["met"] * (n - 2)) == "not_met"
    assert st("na", "unanswered", *["na"] * (n - 2)) == "not_met"


def test_partial_credit_mfa():
    a = _answers({"3.5.3": "not_met"})
    assert score(CAT, a, {"3.5.3": "mfa_remote_privileged_only"}).score == 107
    assert score(CAT, a, {}).score == 105


def test_partial_credit_fips():
    a = _answers({"3.13.11": "not_met"})
    assert score(CAT, a, {"3.13.11": "encryption_not_fips"}).score == 107
    assert score(CAT, a, {}).score == 105


def test_unknown_partial_choice_ignored():
    a = _answers({"3.5.3": "not_met"})
    assert score(CAT, a, {"3.5.3": "bogus"}).score == 105
    # a valid key on a requirement without partial credit is ignored too
    a = _answers({"3.1.1": "not_met"})
    w = CAT.by_id("3.1.1").weight
    assert score(CAT, a, {"3.1.1": "encryption_not_fips"}).score == 110 - w


def test_na_scores_as_met():
    a = _answers({"3.1.1": "na"})
    r = score(CAT, a, {})
    assert r.score == 110 and r.deductions == []


def test_missing_ssp_flags_provisional():
    r = score(CAT, _answers({"3.12.4": "not_met"}), {})
    assert r.ssp_missing and r.provisional
    assert r.score == 110  # 3.12.4 is unscored
    assert not r.conditional_eligible
    r = score(CAT, _answers({"3.12.4": "na"}), {})
    assert r.ssp_missing and r.provisional
    r = score(CAT, _answers({"3.12.4": "unanswered"}), {})
    assert r.ssp_missing and r.provisional and r.not_assessed == 1
    r = score(CAT, _answers({"3.1.1": "unanswered"}), {})
    assert r.provisional and not r.ssp_missing


def _fail(ids, partial=None):
    return score(CAT, _answers({i: "not_met" for i in ids}), partial or {})


def test_conditional_eligibility():
    ones = _ids_of_weight(1)
    threes = [r.id for r in CAT.requirements if r.weight == 3 and r.id != "3.13.11" and r.id != "3.5.3"]
    fives = [r.id for r in CAT.requirements if r.weight == 5]
    # exactly 88 with only weight-1 gaps
    r = _fail(ones[:22])
    assert r.score == 88 and r.conditional_eligible
    assert r.poam_eligible_ids == ones[:22]
    # 88 with a 3-point gap
    r = _fail(ones[:19] + [threes[0]])
    assert r.score == 88 and not r.conditional_eligible
    # 87
    r = _fail(ones[:23])
    assert r.score == 87 and not r.conditional_eligible
    # 3.13.11 at -3 allowed; at -5 not
    r = _fail(ones[:5] + ["3.13.11"], {"3.13.11": "encryption_not_fips"})
    assert r.score == 102 and r.conditional_eligible
    assert "3.13.11" in r.poam_eligible_ids
    r = _fail(["3.13.11"])
    assert r.score == 105 and not r.conditional_eligible
    # excluded weight-1 requirement blocks
    r = _fail(["3.1.20"])
    assert not r.conditional_eligible
    # not_assessed gaps count too
    a = _answers({ones[0]: "unanswered"})
    assert score(CAT, a, {}).conditional_eligible
    a = _answers({fives[0]: "unanswered"})
    assert not score(CAT, a, {}).conditional_eligible


def test_top_gaps_order():
    r = ScoreResult(
        score=0, max=110, provisional=False, ssp_missing=False,
        conditional_eligible=False, poam_eligible_ids=[], not_assessed=0,
        deductions=[
            Deduction("3.2.1", 1, "x"), Deduction("3.1.2", 5, "x"),
            Deduction("3.1.1", 5, "x"), Deduction("3.5.3", 3, "x"),
        ],
    )
    assert [d.req_id for d in top_gaps(r)] == ["3.1.1", "3.1.2", "3.5.3", "3.2.1"]
    assert len(top_gaps(r, 2)) == 2
    assert top_gaps(r, 0) == []
