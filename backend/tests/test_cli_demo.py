"""`python -m cmmcready demo` / `serve` and the collector coverage report."""

import os
import sqlite3

import pytest

from cmmcready import coverage
from cmmcready.__main__ import DEFAULT_DEMO_DB, build_parser, main
from cmmcready.evidence.engine import load_rules


@pytest.fixture
def server_env(monkeypatch):
    """Record CMMCREADY_DB / CMMCREADY_DEMO so whatever the CLI sets is undone afterwards."""
    for name in ("CMMCREADY_DB", "CMMCREADY_DEMO"):
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    calls = []
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: calls.append((app, kw, dict(os.environ))))
    return calls


def test_parser_defaults():
    parser = build_parser()
    demo = parser.parse_args(["demo"])
    assert demo.db is None and not demo.serve and not demo.reset
    assert (demo.host, demo.port, demo.reload) == ("127.0.0.1", 8000, False)
    assert DEFAULT_DEMO_DB.name == "demo.db" and DEFAULT_DEMO_DB.parent.name == "data"
    serve = parser.parse_args(["serve", "--port", "9000", "--host", "0.0.0.0", "--reload"])
    assert (serve.host, serve.port, serve.reload) == ("0.0.0.0", 9000, True)
    with pytest.raises(SystemExit):
        parser.parse_args(["serve", "--port", "not-a-number"])


def test_demo_seeds_a_separate_database(tmp_path, server_env, capsys):
    path = tmp_path / "demo.db"
    assert main(["demo", "--db", str(path)]) == 0
    out = capsys.readouterr().out
    assert "Loaded the fictional demo organization" in out and "assessment 2:" in out
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM assessments").fetchone()[0] == 2
        conn.execute("UPDATE organization SET name = 'changed'")
        conn.commit()
    finally:
        conn.close()
    assert server_env == []  # no --serve, no server

    assert main(["demo", "--db", str(path)]) == 0  # a second run keeps the data
    assert "already holds an organization" in capsys.readouterr().out

    assert main(["demo", "--db", str(path), "--reset"]) == 0  # --reset reloads it
    assert "Loaded the fictional demo organization" in capsys.readouterr().out
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT name FROM organization").fetchone()[0] != "changed"
    finally:
        conn.close()


def test_demo_serve_runs_the_api_in_demo_mode(tmp_path, server_env):
    path = tmp_path / "demo.db"
    assert main(["demo", "--db", str(path), "--serve", "--port", "8123"]) == 0
    [(app, kwargs, env)] = server_env
    assert app == "cmmcready.api:app"
    assert kwargs == {"host": "127.0.0.1", "port": 8123, "reload": False}
    assert env["CMMCREADY_DB"] == str(path.resolve()) and env["CMMCREADY_DEMO"] == "true"


def test_serve_uses_the_configured_database(server_env):
    assert main(["serve"]) == 0
    [(app, kwargs, env)] = server_env
    assert app == "cmmcready.api:app" and kwargs["port"] == 8000
    assert "CMMCREADY_DEMO" not in env and "CMMCREADY_DB" not in env


# -- coverage -------------------------------------------------------------------------------

def test_coverage_outcomes_follow_the_rule_semantics():
    rules = {(r.id, r.check_id): r for c in ("windows", "m365") for rs in load_rules(c).values() for r in rs}
    assert coverage.outcome(rules[("min_length", "password_policy")]) == coverage.DECIDES
    assert coverage.outcome(rules[("all_drives", "autoplay")]) == coverage.MET_ONLY
    assert coverage.outcome(rules[("enabled", "firewall_profiles")]) == coverage.NOT_MET_ONLY
    assert coverage.outcome(rules[("enabled", "fips_mode")]) == coverage.SUPPORTING
    assert coverage.outcome(rules[("list", "local_admins")]) == coverage.INFO


def test_coverage_summary_adds_up():
    s = coverage.summary()
    assert s["objectives"] == 320
    assert sum(f["objectives"] for f in s["families"]) == 320
    assert sum(f["covered"] for f in s["families"]) == s["covered"]
    assert 0 < s["can_meet"] < s["covered"] < 320


def test_committed_coverage_tables_are_current(capsys):
    assert coverage.stale_files() == []
    assert main(["catalog", "--coverage-md", "--check"]) == 0


def test_coverage_check_reports_stale_files(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(coverage, "COVERAGE_DOC", tmp_path / "COLLECTOR_COVERAGE.md")
    monkeypatch.setattr(coverage, "README", tmp_path / "README.md")
    (tmp_path / "README.md").write_text(f"# Title\n{coverage.START}\nold\n{coverage.END}\nrest\n", encoding="utf-8")
    assert main(["catalog", "--coverage-md", "--check"]) == 1
    assert "docs/COLLECTOR_COVERAGE.md, README.md" in capsys.readouterr().err

    assert main(["catalog", "--coverage-md", "--write"]) == 0
    assert main(["catalog", "--coverage-md", "--check"]) == 0
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert readme.startswith("# Title\n") and readme.endswith(f"{coverage.END}\nrest\n") and "old" not in readme

    (tmp_path / "README.md").write_text("no markers\n", encoding="utf-8")
    assert main(["catalog", "--coverage-md", "--write"]) == 1
    assert "no coverage markers" in capsys.readouterr().err
