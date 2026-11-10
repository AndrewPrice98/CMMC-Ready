from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cmmcready import db
from cmmcready.api import app
from cmmcready.catalog import load_catalog

from conftest import TEST_PASSWORD, TEST_USER

WINDOWS = Path(__file__).parent / "fixtures" / "windows-compliant.json"
ANNUAL, INITIAL = 2, 1
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def a(path, assessment=ANNUAL):
    return f"/api/assessments/{assessment}{path}"


# -- auth and public routes --------------------------------------------------------------------

def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["version"] == "0.1.0"


def test_login_me_logout(seeded_db):
    c = TestClient(app)
    assert c.get("/api/auth/me").status_code == 401
    r = c.post("/api/auth/login", json={"username": TEST_USER, "password": TEST_PASSWORD})
    assert r.status_code == 200 and set(r.json()) == {"username", "expires_at"}
    assert "httponly" in r.headers["set-cookie"].lower()
    assert c.get("/api/auth/me").json() == {"username": TEST_USER, "guest": False}
    assert c.post("/api/auth/logout").json() == {"ok": True}


def test_bad_login_and_rate_limit(seeded_db):
    c = TestClient(app)
    bad = {"username": TEST_USER, "password": "wrong password!"}
    assert [c.post("/api/auth/login", json=bad).status_code for _ in range(5)] == [401] * 5
    r = c.post("/api/auth/login", json=bad)
    assert r.status_code == 429 and "retry-after" in r.headers


def test_security_headers(client):
    h = client.get("/api/health").headers
    assert h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in h["content-security-policy"]


def test_protected_routes_need_login(seeded_db):
    assert TestClient(app).get("/api/assessments").status_code == 401


# -- organization, assets, assessments, overview --------------------------------------------

def test_organization_and_assets(client):
    org = client.get("/api/organization").json()
    assert {"id", "name", "cage_codes", "cui_boundary"} <= set(org)
    assets = client.get("/api/assets").json()
    assert assets and {"name", "category"} <= set(assets[0])


def test_assessments_list(client):
    items = client.get("/api/assessments").json()
    assert {i["id"] for i in items} == {INITIAL, ANNUAL}
    annual = next(i for i in items if i["id"] == ANNUAL)
    assert 85 <= annual["score"] <= 87 and annual["max"] == 110 and annual["provisional"] is False
    assert "odp" in annual


def test_overview_shape(client):
    body = client.get(a("/overview")).json()
    assert {"score", "family_heatmap", "top_gaps", "provisional", "ssp_missing",
            "conditional_eligible", "conflicts_count"} <= set(body)
    assert body["score"]["max"] == 110 and 85 <= body["score"]["score"] <= 87
    heat = body["family_heatmap"]
    assert len(heat) == 14 and sum(sum(h[k] for k in ("met", "not_met", "na", "not_assessed"))
                                   for h in heat) == 110
    assert sum(h["points_lost"] for h in heat) == 110 - body["score"]["score"]
    assert body["top_gaps"] and body["top_gaps"][0]["points"] >= body["top_gaps"][-1]["points"]
    assert "does not certify" in body["disclaimer"]
    assert isinstance(body["conflicts_count"], int)


def test_overview_flags_missing_ssp_on_initial(client):
    body = client.get(a("/overview", INITIAL)).json()
    assert body["ssp_missing"] and body["provisional"] and not body["conditional_eligible"]


def test_overview_poam_blocker_ids(client):
    annual = client.get(a("/overview")).json()
    # 3.5.3 at the 3-point partial and 3.8.8 (weight 3) can't go on a POA&M; weight-1 gaps can.
    assert annual["poam_blocker_ids"] == ["3.5.3", "3.8.8"]
    eligible = set(annual["score"]["poam_eligible_ids"])
    assert not eligible & set(annual["poam_blocker_ids"])
    initial = client.get(a("/overview", INITIAL)).json()
    assert "3.12.4" in initial["poam_blocker_ids"]  # SSP missing, though it carries no points
    # 3.13.11 stops blocking once it is at the not-FIPS-validated partial choice.
    for obj in client.get(a("/requirements/3.13.11")).json()["objectives"]:
        assert client.put(a(f"/objectives/{obj['id']}"), json={"answer": "not_met"}).status_code == 200
    assert "3.13.11" in client.get(a("/overview")).json()["poam_blocker_ids"]
    assert client.put(a("/partial/3.13.11"), json={"choice": "encryption_not_fips"}).status_code == 200
    assert "3.13.11" not in client.get(a("/overview")).json()["poam_blocker_ids"]


# -- requirements ----------------------------------------------------------------------------

def test_requirement_list_and_filters(client):
    everything = client.get(a("/requirements")).json()
    assert everything["total"] == 110 and everything["items"][0]["id"] == "3.1.1"
    ac = client.get(a("/requirements"), params={"family": "AC"}).json()
    assert ac["total"] == 22 and {i["family"] for i in ac["items"]} == {"AC"}
    not_met = client.get(a("/requirements"), params={"status": "not_met"}).json()
    assert not_met["total"] > 0 and {i["status"] for i in not_met["items"]} == {"not_met"}
    found = client.get(a("/requirements"), params={"q": "multifactor"}).json()
    assert any(i["id"] == "3.5.3" for i in found["items"])
    assert client.get(a("/requirements"), params={"family": "ZZ"}).status_code == 400
    assert client.get(a("/requirements"), params={"status": "bogus"}).status_code == 400


def test_requirement_detail(client):
    body = client.get(a("/requirements/3.5.3")).json()
    assert body["requirement"]["id"] == "3.5.3" and body["requirement"]["partial"]
    assert body["objectives"] and {"id", "text", "answer", "findings", "conflict"} <= set(body["objectives"][0])
    assert "status" in body and "poam" in body


def test_requirement_list_counts_evidence_and_conflicts(client):
    items = client.get(a("/requirements")).json()["items"]
    assert all(isinstance(i["evidence"], int) and 0 <= i["conflicts"] <= i["evidence"] for i in items)
    assert sum(i["conflicts"] for i in items) == client.get(a("/overview")).json()["conflicts_count"]
    mfa = next(i for i in items if i["id"] == "3.5.3")
    detail = client.get(a("/requirements/3.5.3")).json()
    assert mfa["evidence"] == sum(1 for o in detail["objectives"] if o["findings"])


def test_requirement_detail_poam_rule_reason(client):
    assert client.get(a("/requirements/3.1.3")).json()["poam_rule_reason"] is None
    heavy = client.get(a("/requirements/3.8.8")).json()["poam_rule_reason"]
    assert "170.21" in heavy and "weighted 3" in heavy
    named = client.get(a("/requirements/3.12.4")).json()["poam_rule_reason"]
    assert "excluded from POA&Ms by name" in named
    # 3.13.11 is allowed only at the not-FIPS-validated partial choice.
    assert "FIPS" in client.get(a("/requirements/3.13.11")).json()["poam_rule_reason"]
    assert client.put(a("/partial/3.13.11"), json={"choice": "encryption_not_fips"}).status_code == 200
    assert client.get(a("/requirements/3.13.11")).json()["poam_rule_reason"] is None


def test_ssp_cannot_be_not_applicable(client):
    r = client.put(a("/objectives/3.12.4[a]"), json={"answer": "na", "justification": "We have no SSP."})
    assert r.status_code == 422
    assert r.json()["detail"] == "A System Security Plan is required; 3.12.4 cannot be not applicable."
    assert client.get(a("/requirements/3.12.4")).json()["objectives"][0]["answer"] == "met"
    # Other answers on 3.12.4 are still accepted.
    assert client.put(a("/objectives/3.12.4[a]"), json={"answer": "not_met"}).status_code == 200


def test_unknown_ids_are_404(client):
    assert client.get(a("/requirements/9.9.9")).status_code == 404
    assert client.get("/api/assessments/999/overview").status_code == 404
    assert client.get("/api/assessments/abc/overview").status_code == 404
    assert client.put(a("/objectives/9.9.9[a]"), json={"answer": "met"}).status_code == 404
    assert client.put(a("/partial/9.9.9"), json={"choice": None}).status_code == 404


def test_other_organizations_assessments_are_404(client, db_file):
    c = db.connect(db_file)
    other = c.execute("INSERT INTO organization (name) VALUES ('Other')").lastrowid
    c.commit()
    foreign = db.create_assessment(c, other, "Foreign")
    c.close()
    assert client.get(f"/api/assessments/{foreign}/overview").status_code == 404
    assert foreign not in [x["id"] for x in client.get("/api/assessments").json()]


# -- answers -----------------------------------------------------------------------------------

def test_put_objective_changes_status_and_score(client):
    before = client.get(a("/overview")).json()["score"]["score"]
    req = client.get(a("/requirements/3.1.1")).json()
    for obj in req["objectives"]:
        r = client.put(a(f"/objectives/{obj['id']}"), json={"answer": "not_met", "note": "n"})
        assert r.status_code == 200
    body = r.json()
    assert body["requirement_status"] == "not_met" and body["objective"]["note"] == "n"
    assert client.get(a("/overview")).json()["score"]["score"] <= before


def test_na_requires_justification(client):
    path = a("/objectives/3.1.1[a]")
    assert client.put(path, json={"answer": "na"}).status_code == 422
    assert client.put(path, json={"answer": "na", "justification": "   "}).status_code == 422
    r = client.put(path, json={"answer": "na", "justification": "No such system in scope"})
    assert r.status_code == 200 and r.json()["objective"]["answer"] == "na"
    assert client.get(a("/requirements/3.1.1")).json()["objectives"][0]["justification"]


def test_invalid_answer_is_422(client):
    assert client.put(a("/objectives/3.1.1[a]"), json={"answer": "maybe"}).status_code == 422


def test_partial_choice(client):
    path = a("/partial/3.5.3")
    r = client.put(path, json={"choice": "mfa_remote_privileged_only"})
    assert r.status_code == 200 and r.json()["choice"] == "mfa_remote_privileged_only"
    assert client.get(a("/overview")).json()["partial_choices"]["3.5.3"] == "mfa_remote_privileged_only"
    assert client.put(path, json={"choice": "nonsense"}).status_code == 422
    assert client.put(a("/partial/3.1.1"), json={"choice": "encryption_not_fips"}).status_code == 422
    assert client.put(path, json={"choice": None}).status_code == 200


# -- ODP and evidence --------------------------------------------------------------------------

def test_odp_change_reevaluates(client):
    client.post(a("/evidence"), files={"file": ("w.json", WINDOWS.read_bytes())})

    def result():
        objs = client.get(a("/requirements/3.5.7")).json()["objectives"]
        return next(o for o in objs if o["id"] == "3.5.7[a]")["findings"][-1]["result"]

    assert result() == "met"
    r = client.put(a("/odp"), json={"min_password_length": 30})
    assert r.status_code == 200 and r.json()["odp"]["min_password_length"] == 30
    assert r.json()["reevaluated"] >= 1
    assert result() == "not_met"


@pytest.mark.parametrize("body", [
    {"nonsense": 5}, {"min_password_length": 0}, {"min_password_length": -3},
    {"min_password_length": "12"}, {"min_password_length": True}, {"min_password_length": None},
])
def test_odp_validation_is_422(client, body):
    assert client.put(a("/odp"), json=body).status_code == 422


def test_evidence_list_and_upload(client):
    listing = client.get(a("/evidence")).json()
    assert len(listing) == 3 and set(listing[0]["findings"]) == {"met", "not_met", "not_assessed"}
    assert "raw_json" not in listing[0]
    r = client.post(a("/evidence"), files={"file": ("w.json", WINDOWS.read_bytes())})
    assert r.status_code == 200 and r.json()["findings"]
    assert len(client.get(a("/evidence")).json()) == 4


def test_evidence_detail_lists_checks_commands_and_findings(client):
    first = client.get(a("/evidence")).json()[0]
    body = client.get(a(f"/evidence/{first['id']}")).json()
    assert body["id"] == first["id"] and body["host"] == first["host"] and "raw_json" not in body
    assert body["findings"] == first["findings"]
    assert body["source"]["name"] == first["host"]
    password = next(c for c in body["checks"] if c["id"] == "password_policy")
    assert password["status"] == "ok" and password["command"].startswith("secedit /export")
    assert password["findings"] and all(f["check_id"] == "password_policy" for f in password["findings"])
    assert {f["objective_id"].split("[")[0] for f in password["findings"]} >= {"3.5.7"}
    assert password["result"] in ("met", "not_met", "not_assessed")
    total = sum(len(c["findings"]) for c in body["checks"])
    assert total == sum(body["findings"].values())


def test_evidence_detail_includes_derived_m365_checks(client):
    m365 = next(e for e in client.get(a("/evidence")).json() if e["collector"] == "m365")
    checks = {c["id"]: c for c in client.get(a(f"/evidence/{m365['id']}")).json()["checks"]}
    assert checks["mfa"]["command"].startswith("derived from ")
    assert checks["security_defaults"]["command"].startswith("GET /v1.0/")


def test_evidence_detail_unknown_is_404(client):
    assert client.get(a("/evidence/999")).status_code == 404
    assert client.get(a("/evidence/abc")).status_code == 404
    first = client.get(a("/evidence")).json()[0]["id"]
    assert client.get(a(f"/evidence/{first}", INITIAL)).status_code == 404  # belongs to another assessment


# -- POA&M -------------------------------------------------------------------------------------

def test_poam_get(client):
    body = client.get(a("/poam")).json()
    assert body["items"] and {"id", "req_id", "weakness", "status", "milestones"} <= set(body["items"][0])
    assert isinstance(body["drafts"], list)


def test_poam_create_and_patch(client):
    drafts = client.get(a("/poam", INITIAL)).json()["drafts"]
    ok = next(d for d in drafts if d["allowed"])
    r = client.post(a("/poam", INITIAL), json={"req_id": ok["req_id"], "weakness": "w",
                                               "milestones": [{"description": "m", "due": "2026-12-01"}]})
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["status"] == "open" and item["due_date"] and item["milestones"][0]["description"] == "m"
    assert client.post(a("/poam", INITIAL), json={"req_id": ok["req_id"], "weakness": "w"}).status_code == 409

    path = a(f"/poam/{item['id']}", INITIAL)
    r = client.patch(path, json={"status": "in_progress", "owner": "IT lead"})
    assert r.status_code == 200 and r.json()["status"] == "in_progress" and r.json()["owner"] == "IT lead"
    assert r.json()["weakness"] == "w"
    assert client.patch(path, json={"status": "done"}).status_code == 422
    assert client.patch(path, json={"due_date": "tomorrow"}).status_code == 422
    assert client.patch(path, json={"status": None}).status_code == 422
    assert client.patch(a("/poam/9999", INITIAL), json={"status": "closed"}).status_code == 404
    assert client.patch(a("/poam/abc", INITIAL), json={"status": "closed"}).status_code == 404
    # an item belongs to its own assessment
    assert client.patch(a(f"/poam/{item['id']}", ANNUAL), json={"status": "closed"}).status_code == 404


def test_poam_refused_for_ineligible_requirement(client):
    drafts = client.get(a("/poam", INITIAL)).json()["drafts"]
    bad = next(d for d in drafts if not d["allowed"])
    r = client.post(a("/poam", INITIAL), json={"req_id": bad["req_id"], "weakness": "w"})
    assert r.status_code == 422 and "170.21" in r.json()["detail"]
    # a requirement that is met is not a gap at all
    met = next(i for i in client.get(a("/requirements")).json()["items"] if i["status"] == "met")
    assert client.post(a("/poam"), json={"req_id": met["id"], "weakness": "w"}).status_code == 422
    assert client.post(a("/poam"), json={"req_id": "9.9.9", "weakness": "w"}).status_code == 404
    assert client.post(a("/poam"), json={"req_id": met["id"], "weakness": "w",
                                         "status": "done"}).status_code == 422


# -- exports -----------------------------------------------------------------------------------

@pytest.mark.parametrize("name, media, ext", [
    ("ssp.docx", DOCX, "docx"), ("poam.docx", DOCX, "docx"),
    ("poam.csv", "text/csv; charset=utf-8", "csv"), ("sprs.md", "text/markdown; charset=utf-8", "md"),
])
def test_exports(client, name, media, ext):
    r = client.get(a(f"/exports/{name}"))
    assert r.status_code == 200 and r.headers["content-type"] == media
    disposition = r.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="') and disposition.endswith(f'-{ANNUAL}.{ext}"')
    assert all(c.isalnum() or c in '-."; =' for c in disposition)
    if ext == "docx":
        assert r.content[:2] == b"PK"


def test_sprs_summary_route_matches_markdown(client):
    body = client.get(a("/sprs")).json()
    assert body["disclaimer"].startswith("CMMC Ready is a self-assessment aid.")
    assert {"assessment_date", "score", "max_score", "provisional", "provisional_note", "scope",
            "ssp_name", "ssp_version", "poam_completion_date"} <= set(body)
    markdown = client.get(a("/exports/sprs.md")).text
    assert f"**Score:** {body['score']} (maximum {body['max_score']})" in markdown
    assert f"**Planned POA&M completion date:** {body['poam_completion_date']}" in markdown


def test_unknown_export_is_404(client):
    assert client.get(a("/exports/other.pdf")).status_code == 404
    assert client.get("/api/assessments/999/exports/sprs.md").status_code == 404


# -- history -----------------------------------------------------------------------------------

def test_history_demo(client):
    body = client.get("/api/history").json()
    assert [x["id"] for x in body["assessments"]] == [INITIAL, ANNUAL]
    assert body["assessments"][0]["provisional"] is True
    assert body["assessments"][1]["score"] > body["assessments"][0]["score"]
    assert len(body["changes"]) == 1 and body["changes"][0]["became_met"]


def test_history_diff(db_file):
    conn = db.connect(db_file)
    org = conn.execute("INSERT INTO organization (name) VALUES ('Diff Org (fictional)')").lastrowid
    conn.commit()
    first = db.create_assessment(conn, org, "First", started_at="2026-01-01T00:00:00Z")
    second = db.create_assessment(conn, org, "Second", started_at="2026-02-01T00:00:00Z")
    cat = load_catalog()

    def mark(assessment, req_id, answer):
        for o in cat.by_id(req_id).objectives:
            db.set_answer(conn, assessment, o.id, answer, justification="out of scope")

    mark(first, "3.1.1", "met"), mark(second, "3.1.1", "not_met")    # regressed
    mark(first, "3.1.2", "not_met"), mark(second, "3.1.2", "met")    # became met
    mark(first, "3.1.3", "na"), mark(second, "3.1.3", "met")         # left n/a
    mark(first, "3.1.4", "met"), mark(second, "3.1.4", "na")         # became n/a
    mark(first, "3.1.5", "met"), mark(second, "3.1.5", "met")        # unchanged
    conn.close()

    c = TestClient(app)
    c.post("/api/auth/login", json={"username": TEST_USER, "password": TEST_PASSWORD})
    body = c.get("/api/history").json()
    assert [(x["id"], x["date"]) for x in body["assessments"]] == [(first, "2026-01-01"), (second, "2026-02-01")]
    assert set(body["assessments"][0]) == {"id", "title", "date", "score", "provisional"}
    (change,) = body["changes"]
    assert (change["from_id"], change["to_id"]) == (first, second)
    assert change["regressed"] == ["3.1.1"]
    assert change["became_met"] == ["3.1.2"]
    assert change["no_longer_na"] == ["3.1.3"]
    assert change["became_na"] == ["3.1.4"]
