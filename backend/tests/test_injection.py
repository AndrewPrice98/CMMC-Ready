import sqlite3
from urllib.parse import quote

import pytest

HOSTILE = ["'", "%", "_", "\\", "\" OR 1=1 --", "'; DROP TABLE answers; --", "x" * 10_000,
           "../../etc/passwd", "3.1.1' OR '1'='1", "\x00", "%00"]
A = "/api/assessments/2"


@pytest.fixture
def tables_intact(seeded_db):
    def check():
        c = sqlite3.connect(seeded_db)
        try:
            names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            n = c.execute("SELECT COUNT(*) FROM answers").fetchone()[0]
        finally:
            c.close()
        return {"answers", "evidence", "poam_items", "assessments"} <= names and n > 0
    return check


@pytest.mark.parametrize("value", HOSTILE)
@pytest.mark.parametrize("param", ["q", "family", "status"])
def test_hostile_filter_values_are_harmless(client, tables_intact, param, value):
    r = client.get(f"{A}/requirements", params={param: value})
    if param == "q" and len(value) <= 200:
        assert r.status_code == 200  # searched literally
        assert r.json()["total"] == 0 or value in ("%", "_", "\\", "'") or "" == value
    else:
        assert r.status_code in (400, 422)  # allow-listed or over-length
    assert tables_intact()


def test_like_wildcards_are_literal(client):
    everything = client.get(f"{A}/requirements").json()["total"]
    assert everything == 110
    for wildcard in ("%", "_"):
        # No requirement text contains these literally, so a wildcard must not match everything.
        assert client.get(f"{A}/requirements", params={"q": wildcard}).json()["total"] < everything


@pytest.mark.parametrize("value", HOSTILE)
def test_hostile_ids_are_404_or_422(client, tables_intact, value):
    value = quote(value, safe="")
    for path in (f"/api/assessments/{value}/overview", f"{A}/requirements/{value}",
                 f"/api/assessments/{value}/exports/sprs.md"):
        assert client.get(path).status_code in (404, 422, 400)
    assert client.put(f"{A}/objectives/{value}", json={"answer": "met"}).status_code in (404, 422, 400)
    assert client.put(f"{A}/partial/{value}", json={"choice": None}).status_code in (404, 422, 400)
    assert client.patch(f"{A}/poam/{value}", json={"status": "closed"}).status_code in (404, 422, 400)
    assert tables_intact()


@pytest.mark.parametrize("value", HOSTILE)
def test_hostile_body_values_are_stored_literally_or_refused(client, tables_intact, value):
    r = client.put(f"{A}/objectives/3.1.1[a]", json={"answer": "not_met", "note": value[:5000]})
    assert r.status_code == 200
    assert client.get(f"{A}/requirements/3.1.1").json()["objectives"][0]["note"] == value[:5000]
    assert client.put(f"{A}/objectives/3.1.1[a]", json={"answer": value}).status_code == 422
    assert client.put(f"{A}/odp", json={value: 5}).status_code == 422
    assert client.post(f"{A}/poam", json={"req_id": value, "weakness": "w"}).status_code in (404, 422)
    assert tables_intact()
