"""Windows collector parsing and the evidence engine."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest
import yaml

from cmmcready.catalog import load_catalog
from cmmcready.evidence import windows
from cmmcready.evidence.engine import (
    DEFAULT_ODP,
    RULES_FILE,
    combine,
    evaluate,
    expand_objective_spec,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def by_objective(findings):
    out: dict[str, list] = {}
    for f in findings:
        out.setdefault(f.objective_id, []).append(f)
    return out


def results(findings) -> dict[str, str]:
    return {oid: f.result for oid, f in combine(findings).items()}


def decisive(findings):
    """Findings from rules that give a verdict (information-only rules never do)."""
    return [f for f in findings if f.result != "not_assessed" or f.observed is None]


def test_compliant_fixture_all_met():
    findings = evaluate(load("windows-compliant.json"), DEFAULT_ODP)
    assert findings
    combined = combine(findings)
    # Information-only rules (for example local administrators) never reach "met".
    informational = {f.objective_id for f in findings if f.check_id == "local_admins"}
    for oid, finding in combined.items():
        if oid in informational and len(by_objective(findings)[oid]) == 1:
            assert finding.result == "not_assessed"
        else:
            assert finding.result == "met", f"{oid}: {finding.detail}"
    for oid in ("3.5.7[a]", "3.1.8[b]", "3.1.10[c]", "3.13.16[a]", "3.13.11[a]"):
        assert combined[oid].result == "met"


def test_noncompliant_fixture():
    findings = evaluate(load("windows-noncompliant.json"), DEFAULT_ODP)
    got = results(findings)
    expected_not_met = [
        "3.5.7[a]", "3.5.7[c]", "3.5.8[a]", "3.5.8[b]",
        "3.1.8[a]", "3.1.8[b]",
        "3.3.1[c]", "3.3.1[f]",
        "3.13.16[a]", "3.13.1[f]", "3.13.6[a]", "3.13.15[a]", "3.13.11[a]",
        "3.1.10[a]", "3.1.10[b]", "3.1.10[c]",
        "3.4.7[l]", "3.1.12[c]", "3.1.13[b]",
        "3.14.2[b]", "3.14.4[a]", "3.14.5[c]", "3.14.1[f]",
        "3.1.9[b]", "3.1.1[d]",
    ]
    for oid in expected_not_met:
        assert got[oid] == "not_met", oid
    # Weak evidence stays inconclusive rather than failing the objective.
    assert got["3.8.7[a]"] == "not_assessed"
    # Each failing finding names what was seen and what was required.
    for f in findings:
        if f.result == "not_met":
            assert "observed" in f.detail and "expected" in f.detail, f.detail
            assert f.observed is not None and f.expected
    length = [f for f in by_objective(findings)["3.5.7[a]"] if f.check_id == "password_policy"][0]
    assert "8" in length.detail and "12" in length.detail
    assert length.observed == {"MinimumPasswordLength": 8}


def test_odp_changes_outcome():
    data = load("windows-compliant.json")
    data["checks"]["password_policy"]["value"]["MinimumPasswordLength"] = 12
    met = results(evaluate(data, {**DEFAULT_ODP, "min_password_length": 12}))
    unmet = results(evaluate(data, {**DEFAULT_ODP, "min_password_length": 14}))
    assert met["3.5.7[a]"] == "met"
    assert unmet["3.5.7[a]"] == "not_met"
    # Other ODPs move their own checks.
    assert results(evaluate(data, {"lockout_threshold": 3}))["3.1.8[b]"] == "not_met"
    assert results(evaluate(data, {"session_lock_minutes": 10}))["3.1.10[b]"] == "not_met"
    assert results(evaluate(data, {"password_history": 30}))["3.5.8[b]"] == "not_met"
    assert results(evaluate(data, {"audit_retention_days": 180}))["3.3.1[f]"] != "met"


def test_unavailable_checks_do_not_decide():
    data = load("windows-unavailable.json")
    findings = evaluate(data, DEFAULT_ODP)
    got = results(findings)
    for check_id in ("password_policy", "lockout_policy", "event_log_retention",
                     "smb_signing", "defender", "bitlocker", "patch_level"):
        assert data["checks"][check_id]["status"] == "unavailable" or check_id not in data["checks"]
        for f in findings:
            if f.check_id == check_id:
                assert f.result == "not_assessed", (check_id, f.objective_id)
                assert f.observed is None
    for oid in ("3.5.7[a]", "3.5.8[b]", "3.1.8[b]", "3.3.1[f]", "3.13.16[a]",
                "3.13.15[a]", "3.14.2[b]", "3.14.1[f]"):
        assert got[oid] == "not_assessed", oid
    # Non-English auditpol output is not guessed at.
    assert got["3.3.1[c]"] == "not_assessed"
    # An unreadable NLA value leaves RDP control undecided; readable checks still count.
    assert got["3.1.12[c]"] == "not_assessed"
    assert got["3.1.13[b]"] == "met"
    assert got["3.1.9[b]"] == "met"
    unavailable_detail = [f for f in findings if f.check_id == "bitlocker"][0].detail
    assert "Get-BitLockerVolume" in unavailable_detail


def test_garbled_value_is_not_assessed():
    data = load("windows-compliant.json")
    data["checks"]["password_policy"]["value"]["MinimumPasswordLength"] = "fourteen"
    data["checks"]["lockout_policy"]["value"] = "garbage"
    data["checks"]["bitlocker"]["value"] = {"volumes": []}
    del data["checks"]["firewall_profiles"]
    got = results(evaluate(data, DEFAULT_ODP))
    assert got["3.5.7[a]"] == "not_assessed"
    assert got["3.1.8[b]"] == "not_assessed"
    assert got["3.13.16[a]"] == "not_assessed"
    assert got["3.13.6[a]"] == "not_assessed"


def test_combination_rules():
    data = load("windows-compliant.json")
    data["checks"]["usb_storage"]["value"]["usbstor_start"] = 3
    got = results(evaluate(data, DEFAULT_ODP))
    # autoplay says met, USB storage is inconclusive: not enough for "met".
    assert got["3.8.7[a]"] == "not_assessed"
    data["checks"]["password_policy"]["value"]["PasswordComplexity"] = 0
    findings = evaluate(data, DEFAULT_ODP)
    assert combine(findings)["3.5.7[c]"].result == "not_met"


def test_rules_reference_real_objectives():
    raw = yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))
    catalog = load_catalog()
    known = {o.id for r in catalog.requirements for o in r.objectives}
    seen = 0
    for check_id, check in raw["windows"]["checks"].items():
        assert check["rules"], check_id
        for rule in check["rules"]:
            assert rule["rationale"].strip() and "\n" not in rule["rationale"].strip()
            for spec in rule["objectives"]:
                for oid in expand_objective_spec(spec):
                    assert oid in known, f"{check_id}: {oid}"
                    seen += 1
    assert seen > 25
    # Every collector check is mapped.
    assert set(raw["windows"]["checks"]) == set(windows.CHECK_IDS)


def test_expand_objective_spec():
    assert expand_objective_spec("3.1.10[a-c]") == ["3.1.10[a]", "3.1.10[b]", "3.1.10[c]"]
    assert expand_objective_spec("3.5.7[a]") == ["3.5.7[a]"]
    with pytest.raises(ValueError):
        expand_objective_spec("3.5.7")


def test_unknown_version_rejected():
    data = load("windows-compliant.json")
    data["version"] = 2
    with pytest.raises(ValueError):
        evaluate(data, DEFAULT_ODP)
    with pytest.raises(ValueError):
        windows.validate(data)
    other = load("windows-compliant.json")
    other["collector"] = "linux"
    with pytest.raises(ValueError):
        evaluate(other, DEFAULT_ODP)


@pytest.mark.parametrize("mutate", [
    lambda d: d.pop("checks"),
    lambda d: d.update(checks=[]),
    lambda d: d["checks"]["bitlocker"].update(status="maybe"),
    lambda d: d["checks"]["bitlocker"].pop("status"),
    lambda d: d["checks"].update(bitlocker="nope"),
])
def test_malformed_collector_json_rejected(mutate):
    data = copy.deepcopy(load("windows-compliant.json"))
    mutate(data)
    with pytest.raises(ValueError):
        windows.validate(data)


def test_default_odp_values():
    assert DEFAULT_ODP == {
        "min_password_length": 12,
        "lockout_threshold": 10,
        "session_lock_minutes": 15,
        "password_history": 24,
        "audit_retention_days": 90,
    }


def test_audit_normalisation_is_language_independent_by_guid():
    data = load("windows-compliant.json")
    norm = windows.normalize(data)["audit_policy"]
    assert norm["logon"] == {"success": True, "failure": True}
    assert norm["account_lockout"] == {"success": False, "failure": True}
    german = load("windows-unavailable.json")
    assert windows.normalize(german)["audit_policy"]["logon"] == {}


def test_collect_parse_cli(capsys):
    from cmmcready.__main__ import main

    assert main(["collect-parse", "windows", str(FIXTURES / "windows-unavailable.json")]) == 0
    out = capsys.readouterr().out
    assert "unavailable" in out and "bitlocker" in out
    assert main(["collect-parse", "windows", str(FIXTURES / "windows-compliant.json")]) == 0


def test_collect_parse_cli_rejects_bad_input(tmp_path, capsys):
    from cmmcready.__main__ import main

    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert main(["collect-parse", "windows", str(bad)]) == 1
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"collector": "windows", "version": 9, "checks": {}}), encoding="utf-8")
    assert main(["collect-parse", "windows", str(wrong)]) == 1
    assert main(["collect-parse", "windows", str(tmp_path / "missing.json")]) == 1
    assert "error" in capsys.readouterr().err


def test_collector_script_is_read_only():
    script = (Path(__file__).resolve().parents[2] / "collectors" / "collect-windows.ps1").read_text(encoding="utf-8")
    code = "\n".join(line for line in script.splitlines() if not line.strip().startswith("#"))
    code = re.sub(r"<#.*?#>", "", code, flags=re.S)
    code = re.sub(r"'[^'\n]*'|\"[^\"\n]*\"", "''", code)  # ignore string contents
    cmdlets = set(re.findall(r"\b([A-Z][a-z]+-[A-Z][A-Za-z]+)\b", code))
    allowed_verbs = {"Get", "Test", "ConvertTo", "ConvertFrom", "Select", "Where", "ForEach", "Sort",
                     "Measure", "Join", "Split", "Out", "Write", "Format", "Import", "Compare"}
    allowed_other = {"New-Object", "New-Guid", "Remove-Item", "Set-StrictMode"}
    own = set(re.findall(r"^function\s+([A-Za-z]+-[A-Za-z]+)", code, re.M))
    for name in cmdlets - allowed_other - own:
        assert name.split("-")[0] in allowed_verbs, f"state-changing cmdlet? {name}"
    # The only deletion is the temporary secedit export.
    assert len(re.findall(r"Remove-Item", code)) == 1
    assert "/configure" not in code.lower()
    assert not re.search(r"\breg(\.exe)?\s+(add|delete|import)\b", code, re.I)
