"""The Vercel entry point (api/index.py) and the files the deployed function needs."""

import fnmatch
import importlib.util
import json
import os
import re
import sys

from fastapi.testclient import TestClient

from cmmcready import catalog, config
from cmmcready.api import SECURITY_HEADERS
from cmmcready.evidence import engine

REPO = config.REPO_DIR
ENTRY = REPO / "api" / "index.py"
# sys.path just before the smoke test (other test modules may add scripts/ while they run).
PATH_BEFORE: list[str] = []
HOSTED_DEFAULTS = ("CMMCREADY_DEMO", "CMMCREADY_GUEST", "CMMCREADY_TRUST_PROXY", "CMMCREADY_MAX_UPLOAD_MB",
                   "CMMCREADY_ADMIN_PASSWORD_HASH", "CMMCREADY_SECRET_KEY")


def _vercel() -> dict:
    return json.loads((REPO / "vercel.json").read_text(encoding="utf-8"))


def test_vercel_entry_serves_seeded_demo_to_guests(tmp_path, monkeypatch):
    PATH_BEFORE[:] = sys.path
    monkeypatch.setenv("CMMCREADY_DB", str(tmp_path / "vercel.db"))
    # Hosted-demo defaults: let api/index.py set these itself. setenv first so monkeypatch
    # records each variable's original state (delenv alone records nothing for an unset
    # variable), which removes whatever the entry point sets once the test ends.
    for name in HOSTED_DEFAULTS:
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    monkeypatch.setattr(sys, "path", list(sys.path))  # the entry point prepends backend/

    spec = importlib.util.spec_from_file_location("vercel_entry_under_test", ENTRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # seeds the database, like a cold start
    assert os.environ["CMMCREADY_MAX_UPLOAD_MB"] == "4" and os.environ["CMMCREADY_TRUST_PROXY"] == "true"

    client = TestClient(module.app)
    health = client.get("/api/health").json()
    assert health["demo"] is True and health["guest"] is True and health["auth_configured"] is False
    assert client.get("/api/auth/me").json() == {"username": "guest", "guest": True}
    assessments = client.get("/api/assessments")
    assert assessments.status_code == 200 and len(assessments.json()) == 2
    overview = client.get("/api/assessments/2/overview")
    assert overview.status_code == 200
    assert overview.headers["Content-Security-Policy"] == SECURITY_HEADERS["Content-Security-Policy"]
    # The rules.yml-driven evidence and the DOCX exports work from the bundled files.
    assert client.get("/api/assessments/2/evidence/1").status_code == 200
    assert client.get("/api/assessments/2/exports/ssp.docx").content[:2] == b"PK"
    # Guests are read-only.
    write = client.put("/api/assessments/2/objectives/3.1.1[a]", json={"answer": "met"})
    assert write.status_code == 403
    assert client.post("/api/auth/login", json={"username": "admin", "password": "x" * 12}).status_code == 503


def test_vercel_entry_leaves_no_settings_behind():
    # Runs after the smoke test in file order: the entry point's setdefault()s were undone.
    assert "CMMCREADY_DEMO" not in os.environ and "CMMCREADY_MAX_UPLOAD_MB" not in os.environ
    assert os.environ["CMMCREADY_TRUST_PROXY"] == "false"  # conftest's value, not the entry point's
    assert PATH_BEFORE and sys.path == PATH_BEFORE  # the entry point's sys.path.insert was undone


def _runtime_files() -> list[str]:
    """Every file the API reads at runtime, relative to the repository."""
    package = REPO / "backend" / "cmmcready"
    files = [p for p in package.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    files += [catalog.DATA_FILE, config.DEMO_FIXTURE, engine.RULES_FILE]
    return sorted({p.resolve().relative_to(REPO).as_posix() for p in files})


def test_function_bundle_includes_every_runtime_file():
    pattern = _vercel()["functions"]["api/index.py"]["includeFiles"]
    globs = re.fullmatch(r"\{(.+)\}", pattern).group(1).split(",")
    ignored = [line.strip() for line in (REPO / ".vercelignore").read_text(encoding="utf-8").splitlines()
               if line.strip() and not line.startswith("#")]
    files = _runtime_files()
    assert "backend/cmmcready/evidence/rules.yml" in files and "backend/data/nist_800_171r2.json" in files
    for path in files:
        assert any(fnmatch.fnmatch(path, g.replace("**", "*")) for g in globs), f"{path} is not in includeFiles"
        for rule in ignored:
            rule = rule.removeprefix("**/")
            hit = fnmatch.fnmatch(path, rule) or path.startswith(rule.rstrip("/") + "/")
            assert not hit, f"{path} is excluded by .vercelignore ({rule})"


def _names(path) -> set[str]:
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            names.add(re.match(r"[A-Za-z0-9_.-]+", line).group(0).lower())
    return names


def test_root_requirements_match_backend_runtime_dependencies():
    # Vercel installs the root requirements.txt; it needs everything the API imports.
    # uvicorn is the local server only (Vercel runs the ASGI app itself).
    assert _names(REPO / "requirements.txt") == _names(REPO / "backend" / "requirements.txt") - {"uvicorn"}


def test_static_headers_match_the_api_headers():
    headers = {h["key"]: h["value"] for h in _vercel()["headers"][0]["headers"]}
    assert headers == SECURITY_HEADERS
