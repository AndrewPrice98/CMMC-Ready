import pytest
from fastapi.testclient import TestClient

from cmmcready.api import app
from cmmcready.catalog import load_catalog

from conftest import TEST_PASSWORD, TEST_USER

ORG = {"name": "Acme Machining (fictional)", "cage_codes": ["1abc2"], "description": "d",
       "cui_boundary": "b"}


@pytest.fixture
def empty(db_file):
    """Logged-in admin over an EMPTY, non-demo database."""
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"username": TEST_USER, "password": TEST_PASSWORD}).status_code == 200
    return c


def test_empty_db_reads(empty):
    r = empty.get("/api/organization")
    assert r.status_code == 200 and r.json() is None
    assert empty.get("/api/assets").json() == [] and empty.get("/api/assessments").json() == []
    assert empty.get("/api/history").json() == {"assessments": [], "changes": []}


def test_end_to_end_on_empty_database(empty):
    org = empty.put("/api/organization", json=ORG)
    assert org.status_code == 200 and org.json()["cage_codes"] == ["1ABC2"]
    asset = empty.post("/api/assets", json={"name": "Laptops", "category": "cui"})
    assert asset.status_code == 201
    asset_id = asset.json()["id"]
    assert empty.put(f"/api/assets/{asset_id}", json={"name": "Laptops 2", "category": "spa"}).json()["name"] == "Laptops 2"
    assert empty.delete(f"/api/assets/{asset_id}").status_code == 200
    assert empty.get("/api/assets").json() == []

    created = empty.post("/api/assessments", json={"title": "First"})
    assert created.status_code == 201
    aid = created.json()["id"]
    assert created.json()["odp"]["min_password_length"] == 12

    objective = load_catalog().requirements[0].objectives[0].id
    r = empty.put(f"/api/assessments/{aid}/objectives/{objective}", json={"answer": "met"})
    assert r.status_code == 200
    overview = empty.get(f"/api/assessments/{aid}/overview").json()
    assert overview["score"]["max"] == 110 and overview["provisional"] is True

    done = empty.patch(f"/api/assessments/{aid}", json={"completed_at": "2026-11-09", "title": "Done"})
    assert done.json()["completed_at"] == "2026-11-09" and done.json()["title"] == "Done"
    export = empty.get(f"/api/assessments/{aid}/exports/ssp.docx")
    assert export.status_code == 200 and export.content[:2] == b"PK"
    assert "acme-machining-ssp-" in export.headers["content-disposition"]


def test_organization_update_keeps_single_org(empty):
    empty.put("/api/organization", json=ORG)
    r = empty.put("/api/organization", json={**ORG, "name": "Renamed", "cage_codes": []})
    assert r.json()["name"] == "Renamed" and r.json()["cage_codes"] == []
    assert empty.get("/api/organization").json()["id"] == r.json()["id"]


@pytest.mark.parametrize("body", [
    {**ORG, "name": ""}, {**ORG, "name": "   "}, {**ORG, "name": "x" * 201},
    {**ORG, "cage_codes": ["TOOLONG"]}, {**ORG, "cage_codes": ["ab-12"]},
    {**ORG, "cage_codes": ["AAAAA"] * 21},
])
def test_organization_validation(empty, body):
    assert empty.put("/api/organization", json=body).status_code == 422


def test_conflicts_without_organization(empty):
    assert empty.post("/api/assets", json={"name": "x", "category": "cui"}).status_code == 409
    assert empty.post("/api/assessments", json={"title": "x"}).status_code == 409
    assert empty.put("/api/assets/1", json={"name": "x", "category": "cui"}).status_code == 409


def test_asset_validation_and_ids(empty):
    empty.put("/api/organization", json=ORG)
    assert empty.post("/api/assets", json={"name": "x", "category": "bogus"}).status_code == 422
    assert empty.post("/api/assets", json={"name": " ", "category": "cui"}).status_code == 422
    for cat in ("cui", "spa", "crma", "specialized", "out_of_scope"):
        assert empty.post("/api/assets", json={"name": cat, "category": cat}).status_code == 201
    assert empty.put("/api/assets/999", json={"name": "x", "category": "cui"}).status_code == 404
    assert empty.delete("/api/assets/abc").status_code == 404


def test_assessment_validation(empty):
    empty.put("/api/organization", json=ORG)
    assert empty.post("/api/assessments", json={"title": ""}).status_code == 422
    assert empty.post("/api/assessments", json={"title": "  "}).status_code == 422
    assert empty.post("/api/assessments", json={"title": "t", "copy_from": 99}).status_code == 404
    assert empty.post("/api/assessments", json={"title": "t", "copy_from": 0}).status_code == 422
    aid = empty.post("/api/assessments", json={"title": "t"}).json()["id"]
    path = f"/api/assessments/{aid}"
    assert empty.patch(path, json={"completed_at": "yesterday"}).status_code == 422
    assert empty.patch(path, json={"completed_at": "2026-02-30"}).status_code == 422
    assert empty.patch(path, json={"title": ""}).status_code == 422
    assert empty.patch(path, json={"title": None}).status_code == 422
    assert empty.patch(path, json={"completed_at": "2026-11-09T10:00:00Z"}).status_code == 200
    assert empty.patch(path, json={"completed_at": None}).json()["completed_at"] is None
    assert empty.patch("/api/assessments/999", json={"title": "x"}).status_code == 404


def test_copy_from_copies_answers_odp_and_partial_but_not_evidence(client):
    # seeded demo db: assessment 2 has answers and evidence
    client.put("/api/assessments/2/odp", json={"min_password_length": 15})
    client.put("/api/assessments/2/partial/3.5.3", json={"choice": "mfa_remote_privileged_only"})
    src = client.get("/api/assessments/2/requirements/3.1.1").json()
    new = client.post("/api/assessments", json={"title": "Next year", "copy_from": 2})
    assert new.status_code == 201 and new.json()["odp"]["min_password_length"] == 15
    nid = new.json()["id"]
    assert new.json()["score"] == client.get("/api/assessments/2/overview").json()["score"]["score"]
    copied = client.get(f"/api/assessments/{nid}/requirements/3.1.1").json()
    assert [o["answer"] for o in copied["objectives"]] == [o["answer"] for o in src["objectives"]]
    assert [o["note"] for o in copied["objectives"]] == [o["note"] for o in src["objectives"]]
    assert client.get(f"/api/assessments/{nid}/overview").json()["partial_choices"]["3.5.3"] == \
        "mfa_remote_privileged_only"
    assert client.get(f"/api/assessments/{nid}/evidence").json() == []
    assert client.get(f"/api/assessments/{nid}/poam").json()["items"] == []
    # the source is untouched
    assert len(client.get("/api/assessments/2/evidence").json()) == 3


WRITES = [
    ("put", "/api/organization", {"json": ORG}),
    ("post", "/api/assets", {"json": {"name": "x", "category": "cui"}}),
    ("put", "/api/assets/1", {"json": {"name": "x", "category": "cui"}}),
    ("delete", "/api/assets/1", {}),
    ("post", "/api/assessments", {"json": {"title": "x"}}),
    ("patch", "/api/assessments/2", {"json": {"title": "x"}}),
    ("put", "/api/organization", {"json": {"name": ""}}),
    ("post", "/api/assessments", {"json": {"title": ""}}),
]


@pytest.mark.parametrize("method, path, kwargs", WRITES)
def test_guest_cannot_manage(seeded_db, monkeypatch, method, path, kwargs):
    monkeypatch.setenv("CMMCREADY_DEMO", "true")
    assert getattr(TestClient(app), method)(path, **kwargs).status_code == 403


def test_demo_seeds_at_startup_not_per_request(db_file, monkeypatch):
    monkeypatch.setenv("CMMCREADY_DEMO", "true")
    from cmmcready import db

    with TestClient(app) as c:  # runs the lifespan
        conn = db.connect(db_file)
        try:
            assert db.get_organization(conn) is not None
        finally:
            conn.close()
        assert len(c.get("/api/assessments").json()) == 2
