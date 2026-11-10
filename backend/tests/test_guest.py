import pytest
from fastapi.testclient import TestClient

from cmmcready.api import app

from conftest import TEST_PASSWORD, TEST_USER

A = "/api/assessments/2"
GETS = [
    "/api/health", "/api/auth/me", "/api/organization", "/api/assets", "/api/assessments",
    "/api/history", f"{A}/overview", f"{A}/requirements", f"{A}/requirements/3.1.1",
    f"{A}/requirements?family=AC&status=not_met&q=access", f"{A}/evidence", f"{A}/poam",
    f"{A}/exports/ssp.docx", f"{A}/exports/poam.docx", f"{A}/exports/poam.csv",
    f"{A}/exports/sprs.md",
]


@pytest.fixture
def guest(seeded_db, monkeypatch):
    monkeypatch.setenv("CMMCREADY_DEMO", "true")
    return TestClient(app)


@pytest.mark.parametrize("path", GETS)
def test_guest_reads_everything(guest, path):
    assert guest.get(path).status_code == 200


def test_guest_identity(guest):
    assert guest.get("/api/auth/me").json() == {"username": "guest", "guest": True}
    assert guest.get("/api/health").json()["guest"] is True


WRITES = [
    ("put", f"{A}/objectives/3.1.1[a]", {"json": {"answer": "met"}}),
    ("put", f"{A}/partial/3.5.3", {"json": {"choice": None}}),
    ("put", f"{A}/odp", {"json": {"min_password_length": 14}}),
    ("post", f"{A}/evidence", {"files": {"file": ("e.json", b"{}")}}),
    ("post", f"{A}/poam", {"json": {"req_id": "3.1.1", "weakness": "w"}}),
    ("patch", f"{A}/poam/1", {"json": {"status": "closed"}}),
    # even malformed or junk requests are refused before anything else is looked at
    ("put", f"{A}/odp", {"json": {"nonsense": -1}}),
    ("post", f"{A}/evidence", {"content": b"not multipart"}),
]


@pytest.mark.parametrize("method, path, kwargs", WRITES)
def test_guest_cannot_write(guest, method, path, kwargs):
    assert getattr(guest, method)(path, **kwargs).status_code == 403


def test_guest_writes_change_nothing(guest, seeded_db):
    before = guest.get(f"{A}/overview").json()["score"]["score"]
    guest.put(f"{A}/objectives/3.1.1[a]", json={"answer": "not_met"})
    assert guest.get(f"{A}/overview").json()["score"]["score"] == before


def test_admin_still_writes_in_demo(guest):
    r = guest.post("/api/auth/login", json={"username": TEST_USER, "password": TEST_PASSWORD})
    assert r.status_code == 200
    assert guest.get("/api/auth/me").json()["guest"] is False
    assert guest.put(f"{A}/objectives/3.1.1[a]", json={"answer": "met"}).status_code == 200


def test_guest_works_without_admin_configured(guest, monkeypatch):
    monkeypatch.delenv("CMMCREADY_ADMIN_PASSWORD_HASH")
    assert guest.get("/api/assessments").status_code == 200


def test_guest_can_be_disabled(guest, monkeypatch):
    monkeypatch.setenv("CMMCREADY_GUEST", "false")
    assert guest.get("/api/assessments").status_code == 401


def test_no_guest_outside_demo(seeded_db):
    c = TestClient(app)
    assert c.get("/api/assessments").status_code == 401
    assert c.get("/api/health").json()["guest"] is False


def test_demo_mode_seeds_an_empty_database(db_file, monkeypatch):
    monkeypatch.setenv("CMMCREADY_DEMO", "true")
    c = TestClient(app)
    assert len(c.get("/api/assessments").json()) == 2
