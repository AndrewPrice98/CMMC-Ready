"""POA&M draft generation under 32 CFR 170.21.

A draft is proposed for every not-met requirement that has no POA&M item yet.
Eligibility comes from the catalog (``poam_allowed``) plus the 3.13.11 rule:
that requirement may be on a POA&M only when it is scored at the partial
``encryption_not_fips`` value. The closeout window is 180 days.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from .catalog import Catalog
from .scoring import FIPS_PARTIAL_CHOICE, FIPS_REQUIREMENT, ScoreResult

CLOSEOUT_DAYS = 180
POAM_STATUSES = ("open", "in_progress", "closed")
CITATION = "32 CFR §170.21(a)(2)"


@dataclass
class PoamDraft:
    req_id: str
    weakness: str
    remediation: str = ""
    owner: str = ""
    milestones: list[dict] = field(default_factory=list)
    due_date: str = ""
    status: str = "open"
    points: int = 0
    allowed: bool = True
    reason: str = ""


def parse_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def default_due_date(assessment_date: str | date) -> str:
    return (parse_date(assessment_date) + timedelta(days=CLOSEOUT_DAYS)).isoformat()


def _existing_ids(existing: list) -> set[str]:
    ids = set()
    for item in existing or []:
        ids.add(item if isinstance(item, str) else
                item["req_id"] if isinstance(item, dict) else item.req_id)
    return ids


def ineligible_reason(catalog: Catalog, req_id: str, choice: str | None) -> str:
    req = catalog.by_id(req_id)
    if req_id == FIPS_REQUIREMENT and req.poam_allowed:
        return (f"Not eligible under {CITATION}: {req_id} may be on a POA&M only when "
                "encryption is used but is not FIPS-validated (a 3-point deduction).")
    if req.weight > 1:
        return (f"Not eligible under {CITATION}: a requirement weighted {req.weight} "
                "may not be on a POA&M; only weight-1 requirements may.")
    return (f"Not eligible under {CITATION}: {req_id} is excluded from POA&Ms by name "
            "even though its weight is 1.")


def generate_poam(
    catalog: Catalog, result: ScoreResult, existing: list,
    partial_choices: dict[str, str] | None = None,
    assessment_date: str | date | None = None,
) -> list[PoamDraft]:
    """Drafts for each not-met requirement without an item, in requirement order.

    Requirements that are only "not assessed" are skipped: an unanswered gap is
    not yet a finding. ``assessment_date`` defaults to today.
    """
    choices = partial_choices or {}
    due = default_due_date(assessment_date or date.today())
    have = _existing_ids(existing)
    eligible = set(result.poam_eligible_ids)
    gaps = {d.req_id: d for d in result.deductions if d.reason.startswith("Not met")}
    drafts: list[PoamDraft] = []
    for req in catalog.requirements:
        gap = gaps.get(req.id)
        if gap is None or req.id in have:
            continue
        allowed = req.id in eligible
        if req.id == FIPS_REQUIREMENT:  # defensive: never rely on the id list alone
            allowed = allowed and choices.get(req.id) == FIPS_PARTIAL_CHOICE
        drafts.append(PoamDraft(
            req_id=req.id,
            weakness=f"Requirement {req.id} is not met: {req.text}",
            due_date=due, points=gap.points, allowed=allowed,
            reason="" if allowed else ineligible_reason(catalog, req.id, choices.get(req.id)),
        ))
    return drafts
