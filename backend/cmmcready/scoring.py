"""SPRS scoring: requirement roll-up, score, POA&M eligibility, gap ranking.

Status and score are always derived from objective answers, never stored.
Rules follow the DoD Assessment Methodology v1.2.1 and 32 CFR 170.21.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .catalog import Catalog, Requirement

ObjectiveAnswer = Literal["met", "not_met", "na", "unanswered"]
RequirementStatus = Literal["met", "not_met", "na", "not_assessed"]

MAX_SCORE = 110
CONDITIONAL_THRESHOLD = 88  # 80% of 110
SSP_REQUIREMENT = "3.12.4"
FIPS_REQUIREMENT = "3.13.11"
FIPS_PARTIAL_CHOICE = "encryption_not_fips"


@dataclass(frozen=True)
class Deduction:
    req_id: str
    points: int
    reason: str


@dataclass
class ScoreResult:
    score: int
    max: int = MAX_SCORE
    deductions: list[Deduction] = field(default_factory=list)
    provisional: bool = False
    ssp_missing: bool = False
    conditional_eligible: bool = False
    poam_eligible_ids: list[str] = field(default_factory=list)
    not_assessed: int = 0


def requirement_status(
    req: Requirement, answers: dict[str, ObjectiveAnswer]
) -> RequirementStatus:
    """Roll objective answers up to a requirement status.

    A missing objective counts as unanswered. A requirement is Met only when
    every objective is Met or N/A (at least one Met).
    """
    values = [answers.get(o.id, "unanswered") for o in req.objectives]
    if not values:
        return "not_assessed"
    if all(v == "na" for v in values):
        return "na"
    if all(v in ("met", "na") for v in values):
        return "met"
    if all(v == "unanswered" for v in values):
        return "not_assessed"
    return "not_met"


def _partial_points(
    req: Requirement, partial_choices: dict[str, str]
) -> tuple[int, str | None]:
    """Points to deduct and the partial choice used (None = full weight)."""
    choice = partial_choices.get(req.id)
    if req.partial and choice in req.partial:
        return req.partial[choice], choice
    return req.weight, None


def poam_rule_allows(req: Requirement, choice: str | None) -> bool:
    """Whether 32 CFR 170.21 lets this requirement be on a POA&M with this partial choice."""
    if not req.poam_allowed:
        return False
    if req.id == FIPS_REQUIREMENT:
        return choice == FIPS_PARTIAL_CHOICE
    return True


def score(
    catalog: Catalog,
    answers: dict[str, ObjectiveAnswer],
    partial_choices: dict[str, str],
) -> ScoreResult:
    deductions: list[Deduction] = []
    eligible_ids: list[str] = []
    all_gaps_eligible = True
    not_assessed = 0
    ssp_missing = False

    for req in catalog.requirements:
        status = requirement_status(req, answers)
        if req.id == SSP_REQUIREMENT and status != "met":
            ssp_missing = True  # N/A may not satisfy the SSP requirement
        if status == "not_assessed":
            not_assessed += 1
        if status not in ("not_met", "not_assessed"):
            continue
        points, choice = _partial_points(req, partial_choices)
        if points:
            reason = (
                "Not assessed" if status == "not_assessed" else "Not met"
            ) + (f" (partial: {choice})" if choice else "")
            deductions.append(Deduction(req.id, points, reason))
        if poam_rule_allows(req, choice):
            eligible_ids.append(req.id)
        else:
            all_gaps_eligible = False

    final = MAX_SCORE - sum(d.points for d in deductions)
    return ScoreResult(
        score=final,
        max=MAX_SCORE,
        deductions=deductions,
        provisional=ssp_missing or not_assessed > 0,
        ssp_missing=ssp_missing,
        conditional_eligible=final >= CONDITIONAL_THRESHOLD and all_gaps_eligible,
        poam_eligible_ids=eligible_ids,
        not_assessed=not_assessed,
    )


def _id_key(req_id: str) -> tuple[int, ...]:
    return tuple(int(p) for p in req_id.split("."))


def top_gaps(result: ScoreResult, n: int = 10) -> list[Deduction]:
    """Largest deductions first, ties broken by requirement ID."""
    ranked = sorted(result.deductions, key=lambda d: (-d.points, _id_key(d.req_id)))
    return ranked[: max(n, 0)]
