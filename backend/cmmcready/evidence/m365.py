"""Parse and normalise the output of ``collectors/collect-m365.ps1``.

The collector stores Microsoft Graph v1.0 responses as they came back
(``identitySecurityDefaultsEnforcementPolicy``, ``conditionalAccessPolicy``,
``authenticationMethodsPolicy``, ``unifiedRoleAssignment``). Anything that
has to be interpreted is derived here into small *derived checks*: ``mfa``,
``legacy_auth``, ``session_timeout`` and ``privileged_roles``.

Derivation never guesses. Only enabled Conditional Access policies count
(report-only and disabled ones are ignored). A policy that looks like it
covers everyone but is narrowed by a group exclusion, a location, a platform,
a risk level, an app list or an "OR" with other grant controls is
*unverifiable*: the affected values are left out, so the engine reads them as
unknown and the objective stays "Not assessed". A value is only reported as
``False`` when the data was read and nothing plausible could cover it.
"""

from __future__ import annotations

from typing import Any

COLLECTOR = "m365"
SUPPORTED_VERSION = 1

# Checks the collector writes.
RAW_CHECK_IDS = (
    "security_defaults", "conditional_access", "auth_methods",
    "role_assignments", "session_controls", "audit_log",
)
# Checks the rules are written against (raw ones that need no derivation plus derived ones).
CHECK_IDS = ("mfa", "legacy_auth", "session_timeout", "privileged_roles", "auth_methods", "audit_log")

GLOBAL_ADMIN_TEMPLATE_ID = "62e90394-69f5-4237-9190-012177145e10"
MAX_BREAK_GLASS_EXCLUSIONS = 2
MAX_GLOBAL_ADMINS = 4

# What each derived check reads.
_DERIVED = {
    "mfa": ("security_defaults", "conditional_access"),
    "legacy_auth": ("security_defaults", "conditional_access"),
    "session_timeout": ("session_controls",),
    "privileged_roles": ("role_assignments",),
}


def validate(data: Any) -> dict:
    """Check the collector envelope. Raises ``ValueError`` when it is unusable."""
    if not isinstance(data, dict):
        raise ValueError("collector output must be a JSON object")
    if data.get("collector") != COLLECTOR:
        raise ValueError(f"not a Microsoft 365 collector file (collector={data.get('collector')!r})")
    if data.get("version") != SUPPORTED_VERSION:
        raise ValueError(f"unsupported Microsoft 365 collector version {data.get('version')!r}")
    checks = data.get("checks")
    if not isinstance(checks, dict):
        raise ValueError("collector output has no 'checks' object")
    for check_id, check in checks.items():
        if not isinstance(check, dict):
            raise ValueError(f"check {check_id!r} must be an object")
        if check.get("status") not in ("ok", "unavailable"):
            raise ValueError(f"check {check_id!r} has an invalid status {check.get('status')!r}")
    return data


# --- helpers ----------------------------------------------------------------

def _list(x: Any) -> list:
    return x if isinstance(x, list) else []


def _dict(x: Any) -> dict:
    return x if isinstance(x, dict) else {}


def _value(checks: dict, check_id: str) -> dict | None:
    """The check's value when it was read successfully and is an object."""
    check = checks.get(check_id)
    if isinstance(check, dict) and check.get("status") == "ok" and isinstance(check.get("value"), dict):
        return check["value"]
    return None


def _policies(value: dict | None) -> list[dict] | None:
    if value is None or not isinstance(value.get("policies"), list):
        return None
    return [p for p in value["policies"] if isinstance(p, dict)]


def _security_defaults_on(checks: dict) -> bool | None:
    value = _value(checks, "security_defaults")
    if value is None or not isinstance(value.get("isEnabled"), bool):
        return None
    return value["isEnabled"]


def _empty(value: Any) -> bool:
    if value is None or value == "" or value == [] or value == {}:
        return True
    if isinstance(value, dict):
        return all(_empty(v) for v in value.values())
    if isinstance(value, list):
        return all(_empty(v) for v in value)
    return False


def _assigned_templates(checks: dict) -> set[str] | None:
    """Template IDs of roles that have at least one assignment, or None when the export is unreadable."""
    value = _value(checks, "role_assignments")
    if value is None or not isinstance(value.get("role_definitions"), list)             or not isinstance(value.get("assignments"), list):
        return None
    used = {a.get("roleDefinitionId") for a in value["assignments"] if isinstance(a, dict)}
    return {d.get("templateId") for d in value["role_definitions"]
            if isinstance(d, dict) and d.get("id") in used and d.get("templateId")}


def _targets(policy: dict, assigned: set[str] | None = None) -> dict[str, bool]:
    """Who a policy applies to: all users, privileged roles, external users, or unverifiable.

    ``assigned`` is the set of role template IDs that have assignments in the
    tenant. A role-targeted policy covers privileged accounts only when it
    lists Global Administrator and every other assigned role.
    """
    users = _dict(_dict(policy.get("conditions")).get("users"))
    include = _list(users.get("includeUsers"))
    out = {"all": False, "privileged": False, "external": False, "unverifiable": False}
    if _list(users.get("excludeRoles")) or len(_list(users.get("excludeUsers"))) > MAX_BREAK_GLASS_EXCLUSIONS:
        return out  # admins carved out, or more than a break-glass pair: a real gap, not coverage
    if "All" in include:
        if _list(users.get("excludeGroups")):
            out["unverifiable"] = True  # a group may be a break-glass group or half the company
        elif users.get("excludeGuestsOrExternalUsers"):
            out["privileged"] = True  # guests are a gap for general users; internal admins are covered
        else:
            out["all"] = True
        return out
    roles = _list(users.get("includeRoles"))
    if roles:
        if _list(users.get("excludeGroups")):
            out["unverifiable"] = True
        elif GLOBAL_ADMIN_TEMPLATE_ID in roles:
            if assigned is None:
                out["unverifiable"] = True  # cannot tell which other roles are in use
            elif assigned <= set(roles) | {GLOBAL_ADMIN_TEMPLATE_ID}:
                out["privileged"] = True
    if users.get("includeGuestsOrExternalUsers"):
        out["external"] = True
    if not any(out.values()) and (
            _list(users.get("includeGroups")) or [u for u in include if u != "None"]):
        out["unverifiable"] = True  # specific groups or users: size unknown
    return out


# Condition keys handled explicitly in _narrowed; any other non-empty key narrows the policy.
_KNOWN_CONDITIONS = {"users", "applications", "clientAppTypes", "platforms", "locations"}


def _narrowed(policy: dict, client_types: tuple[str, ...]) -> bool:
    """True when something other than the user list narrows the policy."""
    cond = _dict(policy.get("conditions"))
    apps = _dict(cond.get("applications"))
    if "All" not in _list(apps.get("includeApplications")) or _list(apps.get("excludeApplications")):
        return True
    if _list(apps.get("includeUserActions")) or _list(apps.get("includeAuthenticationContextClassReferences")):
        return True
    types = set(_list(cond.get("clientAppTypes")))
    if "all" not in types and not set(client_types) <= types:
        return True
    # Unknown or future condition keys (authenticationFlows, clientApplications, times, risk
    # levels, device filters, ...) narrow the policy whenever they hold anything.
    if any(not _empty(v) for k, v in cond.items() if k not in _KNOWN_CONDITIONS):
        return True
    platforms = cond.get("platforms")
    if platforms and "all" not in _list(_dict(platforms).get("includePlatforms")):
        return True
    locations = _dict(cond.get("locations"))
    if locations and not (_list(locations.get("includeLocations")) == ["All"]
                          and not _list(locations.get("excludeLocations"))):
        return True
    return False


def _requires_mfa(policy: dict) -> bool | None:
    """True: MFA is required. None: MFA is one option among others. False: no MFA."""
    grant = _dict(policy.get("grantControls"))
    controls = _list(grant.get("builtInControls"))
    strength = grant.get("authenticationStrength")
    if "mfa" not in controls and not strength:
        return False
    options = len(controls) + (1 if strength else 0)
    if grant.get("operator") == "AND" or options == 1:
        return True
    return None


def _enabled(policies: list[dict]) -> list[dict]:
    """Report-only (enabledForReportingButNotEnforced) and disabled policies never count."""
    return [p for p in policies if p.get("state") == "enabled"]


def _tri(found: bool, unknown: bool, readable: bool) -> bool | None:
    if found:
        return True
    if unknown or not readable:
        return None
    return False


def _derive_mfa(checks: dict) -> dict | None:
    sd = _security_defaults_on(checks)
    policies = _policies(_value(checks, "conditional_access"))
    if sd is None and policies is None:
        return None
    if sd:
        return {"all_users": True, "privileged_covered": True, "external_covered": True,
                "via": "security_defaults"}
    assigned = _assigned_templates(checks)
    all_users = privileged = external = unknown = False
    for p in _enabled(policies or []):
        required = _requires_mfa(p)
        if required is False:
            continue
        t = _targets(p, assigned)
        if not (t["all"] or t["privileged"] or t["external"] or t["unverifiable"]):
            continue
        if required is None or _narrowed(p, ("browser", "mobileAppsAndDesktopClients")):
            unknown = True
            continue
        all_users |= t["all"]
        privileged |= t["all"] or t["privileged"]
        external |= t["all"] or t["external"]
        unknown |= t["unverifiable"]
    readable = policies is not None and sd is False  # both sources read: absence means absence
    out: dict[str, Any] = {}
    for key, found in (("all_users", all_users), ("privileged_covered", privileged),
                       ("external_covered", external)):
        verdict = _tri(found, unknown, readable)
        if verdict is not None:
            out[key] = verdict
    out["via"] = "conditional_access" if (all_users or privileged or external) else "none"
    return out


def _derive_legacy(checks: dict) -> dict | None:
    sd = _security_defaults_on(checks)
    policies = _policies(_value(checks, "conditional_access"))
    if sd is None and policies is None:
        return None
    if sd:
        return {"blocked": True, "via": "security_defaults"}
    blocked = unknown = False
    for p in _enabled(policies or []):
        if "block" not in _list(_dict(p.get("grantControls")).get("builtInControls")):
            continue
        t = _targets(p)
        if t["unverifiable"]:
            unknown = True
            continue
        if not t["all"]:
            continue
        if _narrowed(p, ("exchangeActiveSync", "other")):
            unknown = True
            continue
        blocked = True
    readable = policies is not None and sd is False
    verdict = _tri(blocked, unknown, readable)
    out: dict[str, Any] = {"via": "conditional_access" if blocked else "none"}
    if verdict is not None:
        out["blocked"] = verdict
    return out


def _signin_hours(frequency: dict) -> float | None:
    if frequency.get("isEnabled") is not True:
        return None
    if frequency.get("frequencyInterval") == "everyTime":
        return 0
    value, kind = frequency.get("value"), frequency.get("type")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    if kind == "hours":
        return value
    if kind == "days":
        return value * 24
    return None


def _derive_session(checks: dict) -> dict | None:
    policies = _policies(_value(checks, "session_controls"))
    if policies is None:
        return None
    hours: list[float] = []
    for p in _enabled(policies):
        apps = _dict(_dict(p.get("conditions")).get("applications"))
        if not _targets(p)["all"] or "All" not in _list(apps.get("includeApplications")):
            continue
        h = _signin_hours(_dict(_dict(p.get("sessionControls")).get("signInFrequency")))
        if h is not None:
            hours.append(h)
    # The most restrictive all-user policy wins; null means "not configured".
    return {"sign_in_frequency_hours": min(hours) if hours else None}


def _derive_roles(checks: dict) -> dict | None:
    value = _value(checks, "role_assignments")
    if value is None or not isinstance(value.get("role_definitions"), list) \
            or not isinstance(value.get("assignments"), list):
        return None
    definitions = [d for d in value["role_definitions"] if isinstance(d, dict)]
    assignments = [a for a in value["assignments"] if isinstance(a, dict)]
    ga_ids = {d.get("id") for d in definitions if d.get("templateId") == GLOBAL_ADMIN_TEMPLATE_ID}
    out: dict[str, Any] = {}
    roles_with_members = {a.get("roleDefinitionId") for a in assignments if a.get("roleDefinitionId")}
    if roles_with_members:
        out["assigned_role_count"] = len(roles_with_members)
    if not ga_ids:
        return out
    ga = [a for a in assignments
          if a.get("roleDefinitionId") in ga_ids and a.get("directoryScopeId") in (None, "/")]
    principals = {a.get("principalId") for a in ga if a.get("principalId")}
    groups = {a.get("principalId") for a in ga
              if _dict(a.get("principal")).get("@odata.type") == "#microsoft.graph.group"}
    out["global_admin_group_count"] = len(groups)
    # No assignments at all is implausible (a tenant always has one): treat it as unread.
    # Members of a group-assigned role are not counted, so a low count is then unverifiable.
    if principals and (len(principals) > MAX_GLOBAL_ADMINS or not groups):
        out["global_admin_count"] = len(principals)
    return out


def _derive_auth_methods(value: dict) -> dict:
    configs = [c for c in _list(value.get("authenticationMethodConfigurations")) if isinstance(c, dict)]
    enabled = sorted(str(c.get("id")) for c in configs if c.get("state") == "enabled")
    return {"enabled_methods": enabled, "method_count": len(configs)}


# --- public interface --------------------------------------------------------

def _derive_all(checks: dict) -> dict[str, dict | None]:
    return {
        "mfa": _derive_mfa(checks),
        "legacy_auth": _derive_legacy(checks),
        "session_timeout": _derive_session(checks),
        "privileged_roles": _derive_roles(checks),
    }


def effective_checks(data: dict) -> dict:
    """Raw checks plus the derived ones, each with a status and reason like a collected check.

    A derived check is ``unavailable`` when the checks it reads were not
    readable, and its reason names them.
    """
    checks = data["checks"]
    derived = _derive_all(checks)
    out = dict(checks)
    for check_id, sources in _DERIVED.items():
        command = "derived from " + ", ".join(sources)
        if derived[check_id] is not None:
            out[check_id] = {"status": "ok", "value": derived[check_id], "reason": None, "command": command}
            continue
        reasons = []
        for source in sources:
            raw = checks.get(source)
            if raw is None:
                reasons.append(f"{source} was not collected")
            elif raw.get("status") != "ok":
                reasons.append(f"{source} was unavailable: {raw.get('reason') or 'no reason given'}")
            else:
                reasons.append(f"{source} returned a value that cannot be read")
        out[check_id] = {"status": "unavailable", "value": None, "reason": "; ".join(reasons),
                         "command": command}
    return out


def normalize(data: dict) -> dict[str, dict | None]:
    """Return ``{check_id: value}`` for every check that was read successfully.

    Unavailable checks (or values that are not objects) map to ``None``: the
    engine never rules on them.
    """
    checks = data["checks"]
    values: dict[str, dict | None] = {}
    for check_id, check in checks.items():
        value = check.get("value")
        usable = check.get("status") == "ok" and isinstance(value, dict)
        values[check_id] = None if not usable else (
            _derive_auth_methods(value) if check_id == "auth_methods" else value)
    values.update(_derive_all(checks))
    return values


def summarize(data: dict) -> dict:
    """Counts and reasons for the CLI and the UI."""
    checks = data["checks"]
    ok = sorted(c for c, v in checks.items() if v["status"] == "ok")
    unavailable = {c: v.get("reason") or "no reason given" for c, v in sorted(checks.items())
                   if v["status"] == "unavailable"}
    tenant = data.get("tenant") if isinstance(data.get("tenant"), dict) else {}
    return {
        "tenant_id": tenant.get("id"),
        "collected_at": data.get("collected_at"),
        "redacted": tenant.get("names_redacted"),
        "ok": ok,
        "unavailable": unavailable,
        "missing": [c for c in RAW_CHECK_IDS if c not in checks],
    }
