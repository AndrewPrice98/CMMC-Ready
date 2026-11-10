import pytest

from cmmcready.auth import hash_password, limiter

TEST_USER = "admin"
TEST_PASSWORD = "correct horse battery staple"
# Few iterations keep the suite fast; production hashes use auth.DEFAULT_ITERATIONS.
TEST_HASH = hash_password(TEST_PASSWORD, iterations=1_000)


@pytest.fixture(autouse=True)
def auth_env(monkeypatch):
    """Known admin credentials for every test, regardless of any local backend/.env."""
    monkeypatch.setenv("CMMCREADY_ADMIN_USER", TEST_USER)
    monkeypatch.setenv("CMMCREADY_ADMIN_PASSWORD_HASH", TEST_HASH)
    monkeypatch.setenv("CMMCREADY_SECRET_KEY", "test-secret-" + "x" * 40)
    monkeypatch.setenv("CMMCREADY_COOKIE_SECURE", "false")  # TestClient talks plain http
    monkeypatch.setenv("CMMCREADY_TRUST_PROXY", "false")
    monkeypatch.delenv("CMMCREADY_DEMO", raising=False)
    monkeypatch.delenv("CMMCREADY_GUEST", raising=False)
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def db_file(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("CMMCREADY_DB", str(path))
    return path


@pytest.fixture
def conn(db_file):
    from cmmcready import db

    c = db.connect(db_file)
    yield c
    c.close()


@pytest.fixture
def seeded_db(db_file):
    """A database holding the fictional demo organization (assessment 1 = initial, 2 = annual)."""
    from cmmcready import db, demo

    c = db.connect(db_file)
    try:
        assert demo.seed(c)
    finally:
        c.close()
    return db_file


@pytest.fixture
def client(seeded_db):
    """A logged-in admin client over the seeded database."""
    from fastapi.testclient import TestClient

    from cmmcready.api import app

    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": TEST_USER, "password": TEST_PASSWORD})
    assert r.status_code == 200, r.text
    return c
