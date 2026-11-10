"""Parse and normalise the output of ``collectors/collect-windows.ps1``.

The collector reports raw facts. Anything that has to be interpreted (audit
policy settings, patch age) is turned into a comparable form here. A value
that cannot be interpreted is left out, never guessed: the engine reads a
missing value as "unknown" and the objective stays "Not assessed".
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

COLLECTOR = "windows"
SUPPORTED_VERSION = 1

CHECK_IDS = (
    "password_policy", "lockout_policy", "audit_policy", "event_log_retention",
    "bitlocker", "firewall_profiles", "screen_lock", "smb_signing", "smb1",
    "local_admins", "rdp", "defender", "autoplay", "usb_storage", "patch_level",
    "fips_mode", "logon_banner", "guest_account",
)

# Audit subcategories are identified by GUID because their names are localised.
_SUFFIX = "-69AE-11D9-BED3-505054503030"
AUDIT_SUBCATEGORIES = {
    "{0CCE9215" + _SUFFIX + "}": "logon",
    "{0CCE9216" + _SUFFIX + "}": "logoff",
    "{0CCE9217" + _SUFFIX + "}": "account_lockout",
    "{0CCE921B" + _SUFFIX + "}": "special_logon",
    "{0CCE922B" + _SUFFIX + "}": "process_creation",
    "{0CCE922F" + _SUFFIX + "}": "audit_policy_change",
    "{0CCE9235" + _SUFFIX + "}": "user_account_management",
    "{0CCE9237" + _SUFFIX + "}": "security_group_management",
    "{0CCE923F" + _SUFFIX + "}": "credential_validation",
}

# auditpol prints these in the display language. Only English is understood;
# any other text leaves the setting unknown.
_AUDIT_SETTINGS = {
    "success and failure": {"success": True, "failure": True},
    "success": {"success": True, "failure": False},
    "failure": {"success": False, "failure": True},
    "no auditing": {"success": False, "failure": False},
}


def validate(data: Any) -> dict:
    """Check the collector envelope. Raises ``ValueError`` when it is unusable."""
    if not isinstance(data, dict):
        raise ValueError("collector output must be a JSON object")
    if data.get("collector") != COLLECTOR:
        raise ValueError(f"not a Windows collector file (collector={data.get('collector')!r})")
    if data.get("version") != SUPPORTED_VERSION:
        raise ValueError(f"unsupported Windows collector version {data.get('version')!r}")
    checks = data.get("checks")
    if not isinstance(checks, dict):
        raise ValueError("collector output has no 'checks' object")
    for check_id, check in checks.items():
        if not isinstance(check, dict):
            raise ValueError(f"check {check_id!r} must be an object")
        if check.get("status") not in ("ok", "unavailable"):
            raise ValueError(f"check {check_id!r} has an invalid status {check.get('status')!r}")
    return data


def effective_checks(data: dict) -> dict:
    """The checks the rules are evaluated against (Windows has no derived checks)."""
    return data["checks"]


def _parse_when(text: Any) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _normalize_audit(value: dict) -> dict:
    subs = value.get("subcategories")
    out: dict[str, dict] = {key: {} for key in AUDIT_SUBCATEGORIES.values()}
    if not isinstance(subs, dict):
        return out
    for guid, entry in subs.items():
        key = AUDIT_SUBCATEGORIES.get(str(guid).upper())
        setting = entry.get("setting") if isinstance(entry, dict) else None
        if key and isinstance(setting, str):
            flags = _AUDIT_SETTINGS.get(setting.strip().lower())
            if flags:
                out[key] = dict(flags)
    return out


def _normalize_patch(value: dict, collected_at: Any) -> dict:
    out = dict(value)
    out.pop("days_since_latest", None)
    installed = value.get("latest_installed_on")
    when = _parse_when(collected_at)
    try:
        installed_date = date.fromisoformat(installed[:10]) if isinstance(installed, str) else None
    except ValueError:
        installed_date = None
    if installed_date and when:
        out["days_since_latest"] = (when.date() - installed_date).days
    return out


def normalize(data: dict) -> dict[str, dict | None]:
    """Return ``{check_id: value}`` for every check that was read successfully.

    Checks that are unavailable (or whose value is not an object) map to
    ``None``: the engine never rules on them.
    """
    values: dict[str, dict | None] = {}
    for check_id, check in data["checks"].items():
        value = check.get("value")
        if check.get("status") != "ok" or not isinstance(value, dict):
            values[check_id] = None
        elif check_id == "audit_policy":
            values[check_id] = _normalize_audit(value)
        elif check_id == "patch_level":
            values[check_id] = _normalize_patch(value, data.get("collected_at"))
        else:
            values[check_id] = value
    return values


def summarize(data: dict) -> dict:
    """Counts and reasons for the CLI and the UI."""
    checks = data["checks"]
    ok = sorted(c for c, v in checks.items() if v["status"] == "ok")
    unavailable = {c: v.get("reason") or "no reason given" for c, v in sorted(checks.items())
                   if v["status"] == "unavailable"}
    host = data.get("host") if isinstance(data.get("host"), dict) else {}
    return {
        "os": host.get("os"),
        "build": host.get("build"),
        "elevated": host.get("elevated"),
        "collected_at": data.get("collected_at"),
        "ok": ok,
        "unavailable": unavailable,
        "missing": [c for c in CHECK_IDS if c not in checks],
    }
