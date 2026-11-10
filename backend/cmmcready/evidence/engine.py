"""Map collector output to objective-level findings through ``rules.yml``.

A finding is "met" or "not_met" only when the collector read the underlying
value and the rule could interpret it. Anything else (check unavailable,
value missing or garbled, language-dependent text we do not understand)
yields "not_assessed": unreadable output never decides an objective.

Rule conditions are tri-state: True, False, or None (unknown). A leaf looks
up a dotted ``path`` (``name[]`` iterates a list and requires every element)
and applies ``ge``/``le``/``gt``/``lt``/``eq``/``ne``/``nonempty``
(``quant: any`` needs only one list element to satisfy it). A missing
key is unknown; an explicit ``null`` means "not configured" and never
satisfies a requirement. ``all``/``any`` combine leaves.

Per rule: ``met_if`` true -> met. Otherwise ``unmet_if`` (when given) true ->
not_met and anything else -> not_assessed; without ``unmet_if`` the result is
``fail_result`` (default not_met). ``met_result: not_assessed`` marks a rule
whose compliant value is only supporting evidence (reported as not_assessed).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Literal

import yaml

from cmmcready.catalog import load_catalog
from cmmcready.evidence import m365, windows

RULES_FILE = Path(__file__).with_name("rules.yml")

# Collector modules share one interface: COLLECTOR, validate(), effective_checks(), normalize().
_COLLECTORS = {windows.COLLECTOR: windows, m365.COLLECTOR: m365}

Result = Literal["met", "not_met", "not_assessed"]

# Organization-defined parameters: defaults, overridable per assessment.
DEFAULT_ODP: dict[str, int] = {
    "min_password_length": 12,
    "lockout_threshold": 10,
    "session_lock_minutes": 15,
    "password_history": 24,
    "audit_retention_days": 90,
    "max_patch_age_days": 35,
    "max_signin_frequency_hours": 12,
}

ODP_DESCRIPTIONS = {
    "min_password_length": "Minimum password length (characters)",
    "lockout_threshold": "Account lockout after this many failed attempts, or fewer",
    "session_lock_minutes": "Session lock after this many minutes of inactivity, or fewer",
    "password_history": "Passwords remembered before reuse, or more",
    "audit_retention_days": "Audit log retention (days), or more",
    "max_patch_age_days": "Newest installed hotfix may be at most this many days old",
    "max_signin_frequency_hours": "Cloud sign-in frequency (hours) may be at most this long",
}


@dataclass(frozen=True)
class EvidenceFinding:
    objective_id: str
    result: Result
    check_id: str
    detail: str
    observed: Any
    expected: str
    rule_id: str = ""
    rationale: str = ""
    # Optional pointer to a partial-credit choice in the catalog (for example
    # "mfa_remote_privileged_only"). It is a suggestion shown to the assessor
    # and is never applied to scoring automatically.
    partial_hint: str | None = None


@dataclass(frozen=True)
class Rule:
    id: str
    check_id: str
    objectives: tuple[str, ...]
    rationale: str
    met_if: dict | None = None
    unmet_if: dict | None = None
    fail_result: str = "not_met"
    met_result: str = "met"  # "not_assessed": a compliant value is only supporting evidence
    info: dict | None = None  # information-only rule: {"observe": [paths], "text": str}
    partial_hint: str | None = None  # attached to a not_met finding when partial_hint_if is true
    partial_hint_if: dict | None = None


_SPEC = re.compile(r"^(\d+\.\d+\.\d+)\[([a-z])(?:-([a-z]))?\]$")
_OPS = {"ge", "le", "gt", "lt", "eq", "ne", "nonempty"}
_SYMBOL = {"ge": ">=", "le": "<=", "gt": ">", "lt": "<", "eq": "=", "ne": "!=", "nonempty": "is non-empty"}


def expand_objective_spec(spec: str) -> list[str]:
    """``"3.1.10[a-c]"`` -> ``["3.1.10[a]", "3.1.10[b]", "3.1.10[c]"]``."""
    match = _SPEC.match(spec)
    if not match:
        raise ValueError(f"invalid objective reference {spec!r}")
    req, first, last = match.groups()
    last = last or first
    if last < first:
        raise ValueError(f"invalid objective range {spec!r}")
    return [f"{req}[{chr(c)}]" for c in range(ord(first), ord(last) + 1)]


# --- rule loading -----------------------------------------------------------

def _check_condition(cond: Any, where: str) -> None:
    if not isinstance(cond, dict):
        raise ValueError(f"{where}: condition must be a mapping")
    if "all" in cond or "any" in cond:
        key = "all" if "all" in cond else "any"
        if set(cond) != {key} or not isinstance(cond[key], list) or not cond[key]:
            raise ValueError(f"{where}: '{key}' takes a non-empty list")
        for sub in cond[key]:
            _check_condition(sub, where)
        return
    if "path" not in cond:
        raise ValueError(f"{where}: leaf condition needs a path")
    ops = set(cond) - {"path", "quant"}
    if not ops or not ops <= _OPS:
        raise ValueError(f"{where}: unknown operator in {sorted(ops)}")
    for op in ops & (_OPS - {"nonempty"}):
        arg = cond[op]
        if isinstance(arg, dict):
            if "odp" not in arg or arg["odp"] not in DEFAULT_ODP:
                raise ValueError(f"{where}: unknown ODP {arg!r}")


def _build_rules(raw: dict, collector: str) -> dict[str, list[Rule]]:
    catalog = load_catalog()
    known = {o.id for r in catalog.requirements for o in r.objectives}
    hints = {key for r in catalog.requirements for key in (r.partial or {})}
    section = raw.get(collector)
    if not isinstance(section, dict) or not isinstance(section.get("checks"), dict):
        raise ValueError(f"rules.yml needs {collector}.checks")
    rules: dict[str, list[Rule]] = {}
    for check_id, check in section["checks"].items():
        out: list[Rule] = []
        for item in check["rules"]:
            where = f"{check_id}/{item.get('id')}"
            objectives: list[str] = []
            for spec in item["objectives"]:
                for oid in expand_objective_spec(spec):
                    if oid not in known:
                        raise ValueError(f"{where}: unknown objective {oid}")
                    objectives.append(oid)
            rationale = str(item["rationale"]).strip()
            if not rationale:
                raise ValueError(f"{where}: rationale is required")
            info = item.get("info")
            if info is None:
                _check_condition(item.get("met_if"), where)
                if item.get("unmet_if") is not None:
                    _check_condition(item["unmet_if"], where)
            fail = item.get("fail_result", "not_met")
            if fail not in ("not_met", "not_assessed"):
                raise ValueError(f"{where}: bad fail_result {fail!r}")
            met_result = item.get("met_result", "met")
            if met_result not in ("met", "not_assessed"):
                raise ValueError(f"{where}: bad met_result {met_result!r}")
            hint = item.get("partial_hint")
            if hint is not None:
                if hint not in hints:
                    raise ValueError(f"{where}: unknown partial_hint {hint!r}")
                _check_condition(item.get("partial_hint_if"), where)
            out.append(Rule(item["id"], check_id, tuple(objectives), rationale,
                            item.get("met_if"), item.get("unmet_if"), fail, met_result, info,
                            hint, item.get("partial_hint_if")))
        rules[check_id] = out
    return rules


@cache
def load_rules(collector: str = windows.COLLECTOR) -> dict[str, list[Rule]]:
    raw = yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))
    return _build_rules(raw, collector)


# --- condition evaluation ---------------------------------------------------

def _resolve(value: Any, path: str) -> tuple[bool, Any, bool]:
    """Return (found, value-or-list, is_list)."""
    nodes = [value]
    iterated = False
    for token in path.split("."):
        each = token.endswith("[]")
        key = token[:-2] if each else token
        nxt: list[Any] = []
        for node in nodes:
            if not isinstance(node, dict) or key not in node:
                return False, None, False
            child = node[key]
            if each:
                if not isinstance(child, list) or not child:
                    return False, None, False
                nxt.extend(child)
                iterated = True
            else:
                nxt.append(child)
        nodes = nxt
    return True, (nodes if iterated else nodes[0]), iterated


def _arg(arg: Any, odp: dict[str, int]) -> Any:
    if isinstance(arg, dict):
        return odp[arg["odp"]] * arg.get("mul", 1)
    return arg


def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _test(op: str, actual: Any, expected: Any) -> bool | None:
    if actual is None:  # explicitly "not configured"
        return False
    if op == "nonempty":
        return bool(actual.strip()) if isinstance(actual, str) else None
    if op in ("ge", "le", "gt", "lt"):
        if not (_is_num(actual) and _is_num(expected)):
            return None
        return {"ge": actual >= expected, "le": actual <= expected,
                "gt": actual > expected, "lt": actual < expected}[op]
    same_kind = (isinstance(actual, bool) and isinstance(expected, bool)) or \
                (_is_num(actual) and _is_num(expected)) or \
                (isinstance(actual, str) and isinstance(expected, str))
    if not same_kind:
        return None
    return (actual == expected) if op == "eq" else (actual != expected)


def _tri_all(items: list[bool | None]) -> bool | None:
    if any(i is False for i in items):
        return False
    return None if any(i is None for i in items) else True


def _tri_any(items: list[bool | None]) -> bool | None:
    if any(i is True for i in items):
        return True
    return None if any(i is None for i in items) else False


def _eval(cond: dict, value: dict, odp: dict[str, int]) -> bool | None:
    if "all" in cond:
        return _tri_all([_eval(c, value, odp) for c in cond["all"]])
    if "any" in cond:
        return _tri_any([_eval(c, value, odp) for c in cond["any"]])
    found, got, iterated = _resolve(value, cond["path"])
    if not found:
        return None
    elements = got if iterated else [got]
    per_element = []
    for element in elements:
        ops = []
        for op in _OPS & set(cond):
            expected = None if op == "nonempty" else _arg(cond[op], odp)
            ops.append(_test(op, element, expected))
        per_element.append(_tri_all(ops))
    return _tri_any(per_element) if cond.get("quant") == "any" else _tri_all(per_element)


def _paths(cond: dict) -> list[str]:
    if "all" in cond or "any" in cond:
        out: list[str] = []
        for sub in cond.get("all", cond.get("any")):
            for p in _paths(sub):
                if p not in out:
                    out.append(p)
        return out
    return [cond["path"]]


def _describe(cond: dict, odp: dict[str, int]) -> str:
    if "all" in cond or "any" in cond:
        key, glue = ("all", " and ") if "all" in cond else ("any", " or ")
        parts = [_describe(c, odp) for c in cond[key]]
        return glue.join(parts) if len(parts) == 1 else "(" + glue.join(parts) + ")"
    parts = []
    for op in ("ge", "le", "gt", "lt", "eq", "ne", "nonempty"):
        if op not in cond:
            continue
        if op == "nonempty":
            parts.append(f"{cond['path']} is non-empty")
            continue
        arg = cond[op]
        shown = _arg(arg, odp)
        if isinstance(arg, dict):
            shown = f"{shown} ({arg['odp']})"
        parts.append(f"{cond['path']} {_SYMBOL[op]} {shown}")
    return " and ".join(parts)


def _observe(paths: list[str], value: dict) -> dict:
    out = {}
    for path in paths:
        found, got, _ = _resolve(value, path)
        out[path.replace("[]", "")] = got if found else "not reported"
    return out


def _show(observed: dict) -> str:
    return ", ".join(f"{k}={v!r}" if isinstance(v, str) else f"{k}={v}" for k, v in observed.items())


# --- evaluation -------------------------------------------------------------

def _finding(rule: Rule, oid: str, result: Result, detail: str, observed: Any, expected: str,
             hint: str | None = None) -> EvidenceFinding:
    return EvidenceFinding(oid, result, rule.check_id, detail, observed, expected, rule.id, rule.rationale, hint)


def _eval_rule(rule: Rule, raw_check: dict | None, value: dict | None, odp: dict[str, int]) -> list[EvidenceFinding]:
    def emit(result: Result, detail: str, observed: Any, expected: str) -> list[EvidenceFinding]:
        hint = None
        if (result == "not_met" and rule.partial_hint and value is not None
                and _eval(rule.partial_hint_if, value, odp) is True):
            hint = rule.partial_hint
        return [_finding(rule, oid, result, detail, observed, expected, hint) for oid in rule.objectives]

    if rule.info is not None:
        expected = rule.info["text"]
        if value is None:
            return emit("not_assessed", f"{rule.check_id}: not read by the collector; {expected}", None, expected)
        observed = _observe(rule.info["observe"], value)
        return emit("not_assessed", f"observed {_show(observed)}; {expected}", observed, expected)

    expected = _describe(rule.met_if, odp)
    if raw_check is None:
        return emit("not_assessed", f"{rule.check_id} was not collected; expected {expected}", None, expected)
    if raw_check.get("status") != "ok":
        reason = raw_check.get("reason") or "no reason given"
        command = raw_check.get("command")
        suffix = f" (command: {command})" if command else ""
        return emit("not_assessed",
                    f"Not assessed by collector: {rule.check_id} was unavailable: {reason}{suffix}; "
                    f"expected {expected}", None, expected)
    if value is None:
        return emit("not_assessed", f"{rule.check_id} returned a value the engine cannot read; "
                    f"expected {expected}", None, expected)

    observed = _observe(_paths(rule.met_if) + (_paths(rule.unmet_if) if rule.unmet_if else []), value)
    met = _eval(rule.met_if, value, odp)
    if met is None:
        return emit("not_assessed", f"observed {_show(observed)} cannot be interpreted; expected {expected}",
                    observed, expected)
    if met and rule.met_result == "not_assessed":
        return emit("not_assessed", f"Supporting evidence: observed {_show(observed)}; expected {expected}. "
                    "One host setting does not show the organization-level objective is met.", observed, expected)
    if met:
        return emit("met", f"observed {_show(observed)}; expected {expected}", observed, expected)
    if rule.unmet_if is not None:
        unmet = _eval(rule.unmet_if, value, odp)
        if unmet is True:
            return emit("not_met", f"observed {_show(observed)}; expected {expected}", observed, expected)
        return emit("not_assessed", f"observed {_show(observed)} is inconclusive; expected {expected}",
                    observed, expected)
    if rule.fail_result == "not_assessed":
        return emit("not_assessed", f"observed {_show(observed)} does not show the setting, which alone does not "
                    f"fail the objective; expected {expected}", observed, expected)
    return emit("not_met", f"observed {_show(observed)}; expected {expected}", observed, expected)


def evaluate(collector_json: dict, odp: dict | None = None) -> list[EvidenceFinding]:
    """Evaluate collector output. One finding per (rule, objective).

    Raises ``ValueError`` for unknown collectors or versions. Use
    :func:`combine` for one result per objective.
    """
    module = _COLLECTORS.get(collector_json.get("collector")) if isinstance(collector_json, dict) else None
    if module is None:
        raise ValueError("not a recognised collector file")
    module.validate(collector_json)
    merged = {**DEFAULT_ODP, **(odp or {})}
    for name, val in merged.items():
        if name in DEFAULT_ODP and (not _is_num(val) or val <= 0):
            raise ValueError(f"ODP {name} must be a positive number")
    values = module.normalize(collector_json)
    checks = module.effective_checks(collector_json)
    findings: list[EvidenceFinding] = []
    for check_id, rules in load_rules(module.COLLECTOR).items():
        for rule in rules:
            try:
                findings.extend(_eval_rule(rule, checks.get(check_id), values.get(check_id), merged))
            except Exception as exc:  # a malformed value must never decide an objective
                findings.extend(_finding(rule, oid, "not_assessed",
                                         f"{check_id} could not be evaluated ({type(exc).__name__})", None, "")
                                for oid in rule.objectives)
    return findings


def collected_checks(collector_json: dict) -> dict[str, dict]:
    """Every check the rules see for this file, collected or derived, each with its
    ``status``, ``reason``, ``value`` and the exact ``command`` it ran. For display only."""
    module = _COLLECTORS.get(collector_json.get("collector")) if isinstance(collector_json, dict) else None
    if module is None:
        raise ValueError("not a recognised collector file")
    return module.effective_checks(collector_json)


def combine(findings: list[EvidenceFinding]) -> dict[str, EvidenceFinding]:
    """One finding per objective: any not_met -> not_met; all met -> met; else not_assessed."""
    grouped: dict[str, list[EvidenceFinding]] = {}
    for f in findings:
        grouped.setdefault(f.objective_id, []).append(f)
    out: dict[str, EvidenceFinding] = {}
    for oid, group in grouped.items():
        results = {f.result for f in group}
        result: Result = ("not_met" if "not_met" in results
                          else "met" if results == {"met"} else "not_assessed")
        if len(group) == 1:
            out[oid] = group[0]
            continue
        checks = sorted({f.check_id for f in group})
        out[oid] = EvidenceFinding(
            oid, result, ",".join(checks),
            " | ".join(f"{f.check_id}: {f.detail}" for f in group),
            {f.check_id: f.observed for f in group},
            "; ".join(f.expected for f in group if f.expected),
            ",".join(f.rule_id for f in group),
            " ".join(f.rationale for f in group),
            next((f.partial_hint for f in group if f.result == "not_met" and f.partial_hint), None),
        )
    return out
