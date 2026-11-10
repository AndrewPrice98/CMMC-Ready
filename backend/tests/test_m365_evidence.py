"""Microsoft 365 / Entra ID collector parsing and the evidence engine."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest
import yaml

from cmmcready.catalog import load_catalog
from cmmcready.evidence import m365
from cmmcready.evidence.engine import (
    DEFAULT_ODP,
    RULES_FILE,
    combine,
    evaluate,
    expand_objective_spec,
    load_rules,
)
from cmmcready.scoring import score

FIXTURES = Path(__file__).parent / "fixtures"
REPO = Path(__file__).resolve().parents[2]
CATALOG = load_catalog()

# Objectives one tenant setting can only support (never decide as met).
SUPPORTING = {"3.5.3[b]", "3.1.12[c]", "3.1.11[a]", "3.1.11[b]", "3.1.5[a]", "3.1.5[b]", "3.1.5[d]", "3.1.6[b]"}


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def results(data: dict, odp: dict | None = None) -> dict[str, str]:
    return {oid: f.result for oid, f in combine(evaluate(data, odp or DEFAULT_ODP)).items()}


def ca_policies(data: dict) -> list[dict]:
    return data["checks"]["conditional_access"]["value"]["policies"]


def mfa_policy(data: dict) -> dict:
    return next(p for p in ca_policies(data) if p["displayName"].startswith("CA001"))


def test_compliant_fixture():
    findings = evaluate(load("m365-compliant.json"), DEFAULT_ODP)
    combined = combine(findings)
    got = {oid: f.result for oid, f in combined.items()}
    for oid in ("3.5.3[c]", "3.5.3[d]", "3.3.1[c]"):
        assert got[oid] == "met", f"{oid}: {combined[oid].detail}"
    for oid in SUPPORTING:
        assert got[oid] == "not_assessed", oid
    for oid in ("3.1.11[b]", "3.1.5[b]", "3.1.12[c]", "3.5.3[b]"):
        assert "Supporting evidence" in combined[oid].detail, oid
    assert not any(f.result == "not_met" for f in findings)
    assert all(f.partial_hint is None for f in findings)


def test_noncompliant_fixture():
    findings = evaluate(load("m365-noncompliant.json"), DEFAULT_ODP)
    got = results(load("m365-noncompliant.json"))
    # Report-only MFA and a disabled legacy block do not count.
    for oid in ("3.5.3[c]", "3.5.3[d]", "3.1.11[b]", "3.1.5[b]", "3.1.5[d]"):
        assert got[oid] == "not_met", oid
    # Evidence that cannot fail an objective on its own stays undecided.
    for oid in ("3.5.3[b]", "3.1.12[c]", "3.1.6[b]", "3.1.11[a]", "3.3.1[c]"):
        assert got[oid] == "not_assessed", oid
    for f in findings:
        if f.result == "not_met":
            assert "observed" in f.detail and "expected" in f.detail, f.detail
            assert f.observed is not None and f.expected
    ga = next(f for f in findings if f.rule_id == "global_admin_limit")
    assert ga.observed == {"global_admin_count": 7}
    assert all(f.partial_hint is None for f in findings)


def test_report_only_and_disabled_policies_never_count():
    data = load("m365-compliant.json")
    for p in ca_policies(data):
        if p["displayName"].startswith(("CA001", "CA004")):
            p["state"] = "enabledForReportingButNotEnforced"
    got = results(data)
    assert got["3.5.3[d]"] == "not_met"
    assert got["3.5.3[c]"] == "not_met"
    data = load("m365-compliant.json")
    for p in ca_policies(data):
        p["state"] = "disabled"
    for p in data["checks"]["session_controls"]["value"]["policies"]:
        p["state"] = "disabled"
    got = results(data)
    assert got["3.5.3[d]"] == "not_met"
    assert got["3.1.11[b]"] == "not_assessed"  # no session policy in force: inconclusive


def test_mfa_security_defaults_counts():
    findings = evaluate(load("m365-security-defaults.json"), DEFAULT_ODP)
    got = {oid: f.result for oid, f in combine(findings).items()}
    assert got["3.5.3[d]"] == "met" and got["3.5.3[c]"] == "met"
    mfa = next(f for f in findings if f.rule_id == "general_users")
    assert mfa.observed["all_users"] is True


def test_mfa_admins_only_is_not_met_with_partial_hint():
    findings = evaluate(load("m365-admin-mfa-only.json"), DEFAULT_ODP)
    combined = combine(findings)
    assert combined["3.5.3[d]"].result == "not_met"
    assert combined["3.5.3[d]"].partial_hint == "mfa_remote_privileged_only"
    assert combined["3.5.3[c]"].result == "met"
    assert combined["3.5.3[c]"].partial_hint is None
    hinted = [f for f in findings if f.partial_hint]
    assert [f.objective_id for f in hinted] == ["3.5.3[d]"]
    assert "mfa_remote_privileged_only" in CATALOG.by_id("3.5.3").partial


def test_partial_hint_not_applied_automatically():
    findings = evaluate(load("m365-admin-mfa-only.json"), DEFAULT_ODP)
    combined = combine(findings)
    assert combined["3.5.3[d]"].partial_hint == "mfa_remote_privileged_only"
    answers = {o.id: "unanswered" for r in CATALOG.requirements for o in r.objectives}
    for oid, finding in combined.items():
        if finding.result in ("met", "not_met"):
            answers[oid] = finding.result
    # Nothing in the findings selects the partial credit: the full deduction applies...
    result = score(CATALOG, answers, {})
    d353 = [d for d in result.deductions if d.req_id == "3.5.3"]
    assert d353 and d353[0].points == 5 and "partial" not in d353[0].reason
    # ...until the assessor picks the choice themselves.
    chosen = score(CATALOG, answers, {"3.5.3": "mfa_remote_privileged_only"})
    assert [d.points for d in chosen.deductions if d.req_id == "3.5.3"] == [3]


def test_only_non_compliant_side_carries_a_hint():
    data = load("m365-admin-mfa-only.json")
    # Admins-only MFA: the general-user objective is not_met and carries the hint.
    assert combine(evaluate(data, DEFAULT_ODP))["3.5.3[d]"].partial_hint == "mfa_remote_privileged_only"
    # No MFA at all: not_met, but nothing partial to suggest.
    none = load("m365-noncompliant.json")
    assert combine(evaluate(none, DEFAULT_ODP))["3.5.3[d]"].partial_hint is None


def test_unavailable_checks_do_not_decide():
    data = load("m365-unavailable.json")
    findings = evaluate(data, DEFAULT_ODP)
    got = results(data)
    for oid in ("3.5.3[c]", "3.5.3[d]", "3.5.3[b]", "3.1.12[c]", "3.1.11[a]", "3.1.11[b]",
                "3.1.5[a]", "3.1.5[b]", "3.1.5[d]", "3.1.6[b]"):
        assert got[oid] == "not_assessed", oid
    for f in findings:
        if f.check_id in ("mfa", "legacy_auth", "session_timeout", "privileged_roles"):
            assert f.result == "not_assessed" and f.observed is None
    detail = next(f for f in findings if f.check_id == "mfa").detail
    assert detail.startswith("Not assessed by collector")
    assert "Entra ID P1" in detail or "Policy.Read.All" in detail
    # The one readable check still counts.
    assert got["3.3.1[c]"] == "met"


def test_one_unreadable_source_leaves_mfa_unknown():
    data = load("m365-compliant.json")
    data["checks"]["conditional_access"] = copy.deepcopy(load("m365-unavailable.json")["checks"]["conditional_access"])
    got = results(data)
    # Security defaults read as off, but the policies could not be read: nothing can be concluded.
    assert got["3.5.3[d]"] == "not_assessed" and got["3.5.3[c]"] == "not_assessed"
    # Security defaults ON settles it without the policies.
    data["checks"]["security_defaults"]["value"]["isEnabled"] = True
    assert results(data)["3.5.3[d]"] == "met"


def test_garbled_values_are_not_assessed():
    data = load("m365-compliant.json")
    data["checks"]["security_defaults"]["value"] = "garbage"
    data["checks"]["conditional_access"]["value"] = {"policies": "nope"}
    data["checks"]["role_assignments"]["value"] = {"role_definitions": [], "assignments": 3}
    data["checks"]["audit_log"]["value"] = {"entries_found": "yes"}
    del data["checks"]["session_controls"]
    got = results(data)
    for oid in ("3.5.3[c]", "3.5.3[d]", "3.1.12[c]", "3.1.11[b]", "3.1.5[b]", "3.3.1[c]"):
        assert got[oid] == "not_assessed", oid


def test_broad_mfa_exclusions():
    data = load("m365-compliant.json")
    policy = mfa_policy(data)
    # Three excluded accounts is more than a break-glass pair.
    policy["conditions"]["users"]["excludeUsers"] = [f"00000000-0000-0000-0000-0000000b000{i}" for i in range(1, 4)]
    assert results(data)["3.5.3[d]"] == "not_met"
    # Two is the allowed break-glass pair.
    policy["conditions"]["users"]["excludeUsers"] = policy["conditions"]["users"]["excludeUsers"][:2]
    assert results(data)["3.5.3[d]"] == "met"
    # Excluding administrator roles leaves privileged accounts uncovered.
    policy["conditions"]["users"]["excludeRoles"] = ["62e90394-69f5-4237-9190-012177145e10"]
    assert results(data)["3.5.3[c]"] == "not_met"


def test_group_exclusion_and_narrowed_policies_are_inconclusive():
    got = results(load("m365-mfa-group-exclusion.json"))
    assert got["3.5.3[d]"] == "not_assessed"
    assert got["3.5.3[c]"] == "not_assessed"
    data = load("m365-compliant.json")
    mfa_policy(data)["grantControls"] = {"operator": "OR", "builtInControls": ["mfa", "compliantDevice"],
                                         "customAuthenticationFactors": [], "termsOfUse": [],
                                         "authenticationStrength": None}
    assert results(data)["3.5.3[d]"] == "not_assessed"
    data = load("m365-compliant.json")
    mfa_policy(data)["conditions"]["applications"]["includeApplications"] = ["00000003-0000-0000-c000-000000000000"]
    assert results(data)["3.5.3[d]"] == "not_assessed"
    data = load("m365-compliant.json")
    mfa_policy(data)["conditions"]["userRiskLevels"] = ["high"]
    assert results(data)["3.5.3[d]"] == "not_assessed"


def test_authentication_strength_counts_as_mfa():
    data = load("m365-compliant.json")
    mfa_policy(data)["grantControls"] = {
        "operator": "OR", "builtInControls": [], "customAuthenticationFactors": [], "termsOfUse": [],
        "authenticationStrength": {"id": "00000000-0000-0000-0000-000000000002", "displayName": "Multifactor authentication"}}
    assert results(data)["3.5.3[d]"] == "met"


def test_legacy_authentication():
    data = load("m365-compliant.json")
    block = next(p for p in ca_policies(data) if p["displayName"].startswith("CA004"))
    block["state"] = "disabled"
    got = results(data)
    # MFA can be bypassed through legacy protocols.
    assert got["3.5.3[d]"] == "not_met"
    assert got["3.1.12[c]"] == "not_assessed"
    # A geo-block that merely mentions "block" is not a legacy block.
    block["state"] = "enabled"
    block["conditions"]["clientAppTypes"] = ["all"]
    block["conditions"]["locations"] = {"includeLocations": ["All"], "excludeLocations": ["trusted"]}
    assert results(data)["3.5.3[d]"] == "not_assessed"


def test_odp_changes_outcome():
    data = load("m365-compliant.json")  # sign-in frequency is 8 hours
    assert results(data, {**DEFAULT_ODP, "max_signin_frequency_hours": 12})["3.1.11[b]"] == "not_assessed"
    assert results(data, {**DEFAULT_ODP, "max_signin_frequency_hours": 4})["3.1.11[b]"] == "not_met"
    assert results(data, {**DEFAULT_ODP, "max_signin_frequency_hours": 8})["3.1.11[b]"] == "not_assessed"
    for bad in (0, -1, "12"):
        with pytest.raises(ValueError):
            evaluate(data, {"max_signin_frequency_hours": bad})


def test_sign_in_frequency_in_days_and_most_restrictive_wins():
    data = load("m365-compliant.json")
    freq = next(p for p in data["checks"]["session_controls"]["value"]["policies"]
                if p["displayName"].startswith("CA005"))["sessionControls"]["signInFrequency"]
    freq.update(value=1, type="days")  # 24 hours
    assert results(data)["3.1.11[b]"] == "not_met"
    extra = copy.deepcopy(next(p for p in data["checks"]["session_controls"]["value"]["policies"]
                               if p["displayName"].startswith("CA005")))
    extra["id"] = "00000000-0000-0000-0000-0000000c0099"
    extra["sessionControls"]["signInFrequency"].update(value=4, type="hours")
    data["checks"]["session_controls"]["value"]["policies"].append(extra)
    assert results(data)["3.1.11[b]"] == "not_assessed"


def test_global_admin_count_boundaries():
    data = load("m365-compliant.json")
    value = data["checks"]["role_assignments"]["value"]
    ga_def = next(d["id"] for d in value["role_definitions"] if d["templateId"] == m365.GLOBAL_ADMIN_TEMPLATE_ID)

    def with_admins(n: int) -> dict:
        d = copy.deepcopy(data)
        others = [a for a in d["checks"]["role_assignments"]["value"]["assignments"] if a["roleDefinitionId"] != ga_def]
        mine = [{"id": f"x{i}", "roleDefinitionId": ga_def, "principalId": f"p{i}", "directoryScopeId": "/",
                 "appScopeId": None, "principal": {"@odata.type": "#microsoft.graph.user", "displayName": f"u{i}"}}
                for i in range(n)]
        d["checks"]["role_assignments"]["value"]["assignments"] = others + mine
        return d

    assert results(with_admins(4))["3.1.5[b]"] == "not_assessed"  # supporting, not met
    assert results(with_admins(5))["3.1.5[b]"] == "not_met"
    assert results(with_admins(5))["3.1.5[d]"] == "not_met"
    assert results(with_admins(5))["3.1.6[b]"] == "not_assessed"
    # The same person assigned twice counts once.
    twice = with_admins(3)
    twice["checks"]["role_assignments"]["value"]["assignments"] += [
        dict(a, id=a["id"] + "-dup") for a in twice["checks"]["role_assignments"]["value"]["assignments"]
        if a["roleDefinitionId"] == ga_def]
    assert results(twice)["3.1.5[b]"] == "not_assessed"
    # No Global Administrator assignment at all is implausible: unread, never "zero admins".
    assert results(with_admins(0))["3.1.5[b]"] == "not_assessed"


def test_group_assigned_admins_hide_the_real_count():
    got = results(load("m365-mfa-group-exclusion.json"))
    assert got["3.1.5[b]"] == "not_assessed"  # a group's members are not listed
    data = load("m365-mfa-group-exclusion.json")
    value = data["checks"]["role_assignments"]["value"]
    ga_def = value["assignments"][0]["roleDefinitionId"]
    for i in range(5):
        value["assignments"].append({"id": f"x{i}", "roleDefinitionId": ga_def, "principalId": f"p{i}",
                                     "directoryScopeId": "/", "principal": {"@odata.type": "#microsoft.graph.user"}})
    assert results(data)["3.1.5[b]"] == "not_met"  # five or more users is enough on its own


def test_audit_log():
    data = load("m365-compliant.json")
    assert results(data)["3.3.1[c]"] == "met"
    data["checks"]["audit_log"]["value"]["entries_found"] = False
    # A quiet tenant has no recent entries: inconclusive, never a failure.
    assert results(data)["3.3.1[c]"] == "not_assessed"


def test_rules_reference_real_objectives():
    raw = yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))
    known = {o.id for r in CATALOG.requirements for o in r.objectives}
    seen = 0
    for check_id, check in raw["m365"]["checks"].items():
        assert check["rules"], check_id
        for rule in check["rules"]:
            assert rule["rationale"].strip() and "\n" not in rule["rationale"].strip()
            for spec in rule["objectives"]:
                for oid in expand_objective_spec(spec):
                    assert oid in known, f"{check_id}: {oid}"
                    seen += 1
    assert seen >= 12
    assert set(raw["m365"]["checks"]) == set(m365.CHECK_IDS)
    assert set(load_rules("m365")) == set(m365.CHECK_IDS)
    # Windows rules are untouched by the new section.
    assert "password_policy" in load_rules()


def test_brief_mappings_are_present():
    mapped: dict[str, set[str]] = {}
    for rules in load_rules("m365").values():
        for rule in rules:
            for oid in rule.objectives:
                mapped.setdefault(oid, set()).add(rule.check_id)
    assert {"mfa", "legacy_auth"} <= mapped["3.5.3[d]"]
    assert "legacy_auth" in mapped["3.1.12[c]"]
    assert "privileged_roles" in mapped["3.1.5[b]"] and "privileged_roles" in mapped["3.1.6[b]"]
    assert "session_timeout" in mapped["3.1.11[b]"]
    assert "audit_log" in mapped["3.3.1[c]"]


def test_supporting_rules_are_declarative():
    rules = {r.id: r for rs in load_rules("m365").values() for r in rs}
    for rule_id in ("global_admin_limit", "non_privileged_use", "frequency_enforced", "remote_control",
                    "privileged_local"):
        assert rules[rule_id].met_result == "not_assessed", rule_id
    assert rules["general_users"].partial_hint == "mfa_remote_privileged_only"


def test_default_odp_includes_signin_frequency():
    assert DEFAULT_ODP["max_signin_frequency_hours"] == 12


def test_unknown_version_and_collector_rejected():
    data = load("m365-compliant.json")
    data["version"] = 2
    with pytest.raises(ValueError):
        evaluate(data, DEFAULT_ODP)
    with pytest.raises(ValueError):
        m365.validate(data)
    other = load("m365-compliant.json")
    other["collector"] = "windows"
    with pytest.raises(ValueError):
        m365.validate(other)
    other["collector"] = "linux"
    with pytest.raises(ValueError):
        evaluate(other, DEFAULT_ODP)


@pytest.mark.parametrize("mutate", [
    lambda d: d.pop("checks"),
    lambda d: d.update(checks=[]),
    lambda d: d["checks"]["audit_log"].update(status="maybe"),
    lambda d: d["checks"]["audit_log"].pop("status"),
    lambda d: d["checks"].update(audit_log="nope"),
])
def test_malformed_collector_json_rejected(mutate):
    data = copy.deepcopy(load("m365-compliant.json"))
    mutate(data)
    with pytest.raises(ValueError):
        m365.validate(data)


def test_fixtures_use_graph_response_shapes():
    data = load("m365-compliant.json")
    sd = data["checks"]["security_defaults"]["value"]
    assert set(sd) >= {"id", "displayName", "isEnabled"}
    policy = ca_policies(data)[0]
    assert set(policy) >= {"id", "displayName", "state", "conditions", "grantControls", "sessionControls"}
    assert set(policy["conditions"]) >= {"users", "applications", "clientAppTypes"}
    assert set(policy["conditions"]["users"]) >= {"includeUsers", "excludeUsers", "includeRoles", "excludeGroups"}
    assert {p["state"] for p in ca_policies(data)} <= {"enabled", "disabled", "enabledForReportingButNotEnforced"}
    methods = data["checks"]["auth_methods"]["value"]
    assert methods["id"] == "authenticationMethodsPolicy" and methods["authenticationMethodConfigurations"]
    assignment = data["checks"]["role_assignments"]["value"]["assignments"][0]
    assert set(assignment) >= {"id", "roleDefinitionId", "principalId", "directoryScopeId"}
    for name in FIXTURES.glob("m365-*.json"):
        text = name.read_text(encoding="utf-8")
        assert "contoso.com" not in text and "@" not in re.sub(r'"@odata[^"]*"', "", text)


def test_normalize_unavailable_maps_to_none():
    values = m365.normalize(load("m365-unavailable.json"))
    assert values["conditional_access"] is None and values["mfa"] is None
    assert values["privileged_roles"] is None and values["audit_log"] is not None
    assert m365.summarize(load("m365-unavailable.json"))["unavailable"]["conditional_access"]


def test_collect_parse_cli(capsys):
    from cmmcready.__main__ import main

    assert main(["collect-parse", "m365", str(FIXTURES / "m365-unavailable.json")]) == 0
    out = capsys.readouterr().out
    assert "unavailable" in out and "conditional_access" in out and "m365 collector" in out
    assert main(["collect-parse", "m365", str(FIXTURES / "m365-compliant.json")]) == 0
    assert main(["collect-parse", "m365", str(FIXTURES / "m365-compliant.json"), "--min-ok", "6"]) == 0
    assert main(["collect-parse", "m365", str(FIXTURES / "m365-unavailable.json"), "--min-ok", "4"]) == 1
    assert "at least 4" in capsys.readouterr().err


def test_collect_parse_cli_rejects_wrong_collector(capsys):
    from cmmcready.__main__ import main

    assert main(["collect-parse", "m365", str(FIXTURES / "windows-compliant.json")]) == 1
    assert main(["collect-parse", "windows", str(FIXTURES / "m365-compliant.json")]) == 1
    assert "error" in capsys.readouterr().err


def _script() -> str:
    return (REPO / "collectors" / "collect-m365.ps1").read_text(encoding="utf-8")


def _code(script: str) -> str:
    code = re.sub(r"<#.*?#>", "", script, flags=re.S)  # help block first: its closing line starts with '#'
    return "\n".join(line for line in code.splitlines() if not line.strip().startswith("#"))


def test_collector_script_is_read_only():
    raw_code = _code(_script())
    code = re.sub(r"'[^'\n]*'|\"[^\"\n]*\"", "''", raw_code)  # ignore string contents
    cmdlets = set(re.findall(r"\b([A-Z][a-z]+-[A-Z][A-Za-z]+)\b", code))
    allowed_verbs = {"Get", "Test", "ConvertTo", "ConvertFrom", "Select", "Where", "ForEach", "Sort",
                     "Measure", "Join", "Split", "Out", "Write", "Format", "Import"}
    allowed_other = {"New-Object", "Set-StrictMode", "Connect-MgGraph", "Disconnect-MgGraph",
                     "Invoke-MgGraphRequest"}
    own = set(re.findall(r"^function\s+([A-Za-z]+-[A-Za-z]+)", code, re.M))
    for name in cmdlets - allowed_other - own:
        assert name.split("-")[0] in allowed_verbs, f"state-changing cmdlet? {name}"
    assert "Remove-Item" not in code
    # Every Graph call is an explicit GET.
    calls = re.findall(r"Invoke-MgGraphRequest[^\n]*", raw_code)
    assert calls
    for call in calls:
        assert "-Method GET" in call, call
    assert not re.search(r"-Method\s+(POST|PATCH|PUT|DELETE)", raw_code, re.I)
    assert not re.search(r"\bMg[A-Za-z]*\s+-Body\b|-Body\b", raw_code)
    # Only read-only scopes are requested.
    scopes = re.search(r"\$Scopes\s*=\s*@\(([^)]*)\)", raw_code)
    assert scopes
    requested = re.findall(r"'([^']+)'", scopes.group(1))
    assert sorted(requested) == sorted(["Policy.Read.All", "Directory.Read.All", "AuditLog.Read.All",
                                        "RoleManagement.Read.Directory"])
    assert all(".Read" in s and "ReadWrite" not in s for s in requested)
    assert "-NoWelcome" in raw_code
    for secret in ("ClientSecret", "-Credential", "AccessToken", "SecureString", "-CertificateThumbprint"):
        assert secret not in raw_code, secret


def test_collector_script_conventions():
    script = _script()
    assert "[switch]$RedactNames" in script and "$OutFile" in script
    assert "collector    = 'm365'" in script and "version      = 1" in script
    code = _code(script)
    for check_id in m365.RAW_CHECK_IDS:
        assert f"Invoke-Check '{check_id}'" in code, check_id
    assert "status = 'unavailable'" in code


# --- fix round 1: privileged coverage, unknown conditions, guest exclusions -----------------

GA = m365.GLOBAL_ADMIN_TEMPLATE_ID
HELPDESK = "729827e3-9c14-49f7-bb1b-9608f156bbb8"
USER_ADMIN = "fe930be7-5e62-47db-91af-98c3a49a38b1"


def role_policy(data: dict, roles: list[str]) -> dict:
    p = mfa_policy(data)
    p["conditions"]["users"].update(includeUsers=["None"], includeRoles=roles)
    return p


def test_helpdesk_only_policy_does_not_cover_privileged_accounts():
    data = load("m365-compliant.json")
    role_policy(data, [HELPDESK])
    got = results(data)
    assert got["3.5.3[c]"] == "not_met" and got["3.5.3[d]"] == "not_met"


def test_role_policy_needs_global_admin_and_every_assigned_role():
    data = load("m365-compliant.json")  # GA, User Admin and Helpdesk all have assignments
    role_policy(data, [GA])
    assert results(data)["3.5.3[c]"] == "not_met"  # User Admin and Helpdesk uncovered
    role_policy(data, [GA, USER_ADMIN])
    assert results(data)["3.5.3[c]"] == "not_met"
    role_policy(data, [GA, USER_ADMIN, HELPDESK])
    findings = combine(evaluate(data, DEFAULT_ODP))
    assert findings["3.5.3[c]"].result == "met"
    assert findings["3.5.3[d]"].result == "not_met"
    assert findings["3.5.3[d]"].partial_hint == "mfa_remote_privileged_only"
    # Roles with no assignment in the tenant need not be listed (admin-only fixture: only GA assigned).
    assert results(load("m365-admin-mfa-only.json"))["3.5.3[c]"] == "met"


def test_role_policy_exclusions():
    data = load("m365-admin-mfa-only.json")
    policy = next(p for p in ca_policies(data) if p["displayName"].startswith("CA002"))
    policy["conditions"]["users"]["excludeGroups"] = ["00000000-0000-0000-0000-0000000a0a01"]
    assert results(data)["3.5.3[c]"] == "not_assessed"
    policy["conditions"]["users"]["excludeGroups"] = []
    policy["conditions"]["users"]["excludeUsers"] = [f"00000000-0000-0000-0000-0000000b000{i}" for i in range(1, 4)]
    assert results(data)["3.5.3[c]"] == "not_met"
    policy["conditions"]["users"]["excludeUsers"] = policy["conditions"]["users"]["excludeUsers"][:2]
    assert results(data)["3.5.3[c]"] == "met"
    policy["conditions"]["users"]["excludeRoles"] = [GA]
    assert results(data)["3.5.3[c]"] == "not_met"


def test_role_policy_without_role_export_is_unverifiable():
    data = load("m365-admin-mfa-only.json")
    data["checks"]["role_assignments"] = copy.deepcopy(load("m365-unavailable.json")["checks"]["role_assignments"])
    got = results(data)
    assert got["3.5.3[c]"] == "not_assessed"  # Global Admin alone is not enough without the export
    assert got["3.5.3[d]"] == "not_assessed"  # nothing conclusive about general users either


@pytest.mark.parametrize("condition", [
    {"authenticationFlows": {"transferMethods": "deviceCodeFlow"}},
    {"clientApplications": {"includeServicePrincipals": ["ServicePrincipalsInMyTenant"], "excludeServicePrincipals": []}},
    {"insiderRiskLevels": "elevated"},
    {"times": {"includedRanges": ["08:00-17:00"]}},
    {"someFutureCondition": {"mode": "x"}},
])
def test_unknown_condition_keys_narrow_the_policy(condition):
    data = load("m365-compliant.json")
    mfa_policy(data)["conditions"].update(condition)
    got = results(data)
    assert got["3.5.3[d]"] == "not_assessed" and got["3.5.3[c]"] == "not_assessed"
    # Empty values for the same keys are not narrowing.
    data = load("m365-compliant.json")
    mfa_policy(data)["conditions"].update({k: ([] if isinstance(v, list) else None) for k, v in condition.items()})
    assert results(data)["3.5.3[d]"] == "met"


def test_user_actions_narrow_the_policy():
    data = load("m365-compliant.json")
    mfa_policy(data)["conditions"]["applications"]["includeUserActions"] = ["urn:user:registersecurityinfo"]
    assert results(data)["3.5.3[d]"] == "not_assessed"


def test_all_users_policy_excluding_guests_still_covers_privileged():
    data = load("m365-compliant.json")
    mfa_policy(data)["conditions"]["users"]["excludeGuestsOrExternalUsers"] = {
        "guestOrExternalUserTypes": "b2bCollaborationGuest", "externalTenants": {"membershipKind": "all"}}
    findings = combine(evaluate(data, DEFAULT_ODP))
    assert findings["3.5.3[d]"].result == "not_met"
    assert findings["3.5.3[d]"].partial_hint == "mfa_remote_privileged_only"
    assert findings["3.5.3[c]"].result == "met"


def test_collector_records_service_error_body():
    code = _code(_script())
    assert "ErrorDetails.Message" in code
    assert "Get-ErrorText $_" in code
