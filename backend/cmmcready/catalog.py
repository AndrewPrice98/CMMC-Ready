"""NIST SP 800-171 Rev 2 control catalog: load and validate.

The data lives in ``backend/data/nist_800_171r2.json`` and is built from the
official NIST CSV files by ``backend/scripts/build_catalog.py``. The file's
``source`` field cites every publication it was built from.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "nist_800_171r2.json"

# Requirement counts per family (SP 800-171 Rev 2, Chapter 3), in family order.
FAMILY_COUNTS = {
    "AC": 22, "AT": 3, "AU": 9, "CM": 9, "IA": 11, "IR": 3, "MA": 6,
    "MP": 9, "PS": 2, "PE": 6, "RA": 3, "CA": 4, "SC": 16, "SI": 7,
}
EXPECTED_OBJECTIVES = 320  # SP 800-171A determination statements
TOTAL_WEIGHT = 313  # DoD Assessment Methodology v1.2.1: 110 - 313 = -203
UNSCORED = {"3.12.4"}  # Annex A value "NA"
PARTIAL = {
    "3.5.3": {"mfa_remote_privileged_only": 3},
    "3.13.11": {"encryption_not_fips": 3},
}
# 32 CFR 170.21(a)(2)(iii): may never be on a POA&M despite a weight of 1.
POAM_EXCLUDED = {"3.1.20", "3.1.22", "3.10.3", "3.10.4", "3.10.5", "3.12.4"}


@dataclass(frozen=True)
class Objective:
    id: str
    text: str


@dataclass(frozen=True)
class Requirement:
    id: str
    family: str
    family_name: str
    basic: bool
    text: str
    discussion: str
    weight: int
    partial: dict[str, int] | None
    poam_allowed: bool
    objectives: list[Objective]
    footnotes: list[str] = field(default_factory=list)

    @property
    def family_number(self) -> str:
        return self.id.rsplit(".", 1)[0]


@dataclass(frozen=True)
class Family:
    code: str
    number: str
    name: str


@dataclass(frozen=True)
class Catalog:
    requirements: list[Requirement]
    source: dict

    def by_id(self, req_id: str) -> Requirement:
        for req in self.requirements:
            if req.id == req_id:
                return req
        raise KeyError(req_id)

    def families(self) -> list[Family]:
        seen: dict[str, Family] = {}
        for req in self.requirements:
            if req.family not in seen:
                seen[req.family] = Family(req.family, req.family_number, req.family_name)
        return list(seen.values())

    @property
    def objective_count(self) -> int:
        return sum(len(r.objectives) for r in self.requirements)

    @property
    def total_weight(self) -> int:
        return sum(r.weight for r in self.requirements)


def _requirement(raw: dict) -> Requirement:
    return Requirement(
        id=raw["id"],
        family=raw["family"],
        family_name=raw["family_name"],
        basic=raw["basic"],
        text=raw["text"],
        discussion=raw["discussion"],
        weight=raw["weight"],
        partial=raw["partial"],
        poam_allowed=raw["poam_allowed"],
        objectives=[Objective(o["id"], o["text"]) for o in raw["objectives"]],
        footnotes=list(raw.get("footnotes", [])),
    )


def _load(path: Path) -> Catalog:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Catalog(
        requirements=[_requirement(r) for r in data["requirements"]],
        source=data["source"],
    )


@cache
def _load_default() -> Catalog:
    return _load(DATA_FILE)


def load_catalog(path: Path | str | None = None) -> Catalog:
    """Load the catalog. The bundled file is read once and cached."""
    if path is None:
        return _load_default()
    return _load(Path(path))


def _id_key(req_id: str) -> tuple[int, ...]:
    return tuple(int(part) for part in req_id.split("."))


def validate(catalog: Catalog) -> list[str]:
    """Return a list of problems with the catalog data (empty when valid)."""
    problems: list[str] = []
    reqs = catalog.requirements
    ids = [r.id for r in reqs]

    counts = Counter(r.family for r in reqs)
    if dict(counts) != FAMILY_COUNTS:
        problems.append(f"family counts {dict(counts)} != {FAMILY_COUNTS}")
    if [f.code for f in catalog.families()] != list(FAMILY_COUNTS):
        problems.append("families are not in SP 800-171 order")
    if len(ids) != len(set(ids)):
        problems.append("duplicate requirement IDs")
    try:
        if ids != sorted(ids, key=_id_key):
            problems.append("requirements are not in numeric order")
    except ValueError:
        problems.append("malformed requirement ID")

    obj_ids = [o.id for r in reqs for o in r.objectives]
    if len(obj_ids) != len(set(obj_ids)):
        problems.append("duplicate objective IDs")
    if len(obj_ids) != EXPECTED_OBJECTIVES:
        problems.append(f"{len(obj_ids)} objectives, expected {EXPECTED_OBJECTIVES}")

    for r in reqs:
        if not r.text or not r.discussion:
            problems.append(f"{r.id}: missing text or discussion")
        if not r.objectives:
            problems.append(f"{r.id}: no objectives")
        letters = [o.id[len(r.id):] for o in r.objectives]
        if letters != [f"[{chr(ord('a') + i)}]" for i in range(len(letters))]:
            problems.append(f"{r.id}: objectives not lettered [a], [b], ... in order")
        if any(not o.text for o in r.objectives):
            problems.append(f"{r.id}: empty objective text")

        expected_weights = {0} if r.id in UNSCORED else {1, 3, 5}
        if r.weight not in expected_weights:
            problems.append(f"{r.id}: weight {r.weight} not in {sorted(expected_weights)}")
        if r.partial != PARTIAL.get(r.id):
            problems.append(f"{r.id}: partial {r.partial} != {PARTIAL.get(r.id)}")
        poam = (r.weight == 1 and r.id not in POAM_EXCLUDED) or r.id == "3.13.11"
        if r.poam_allowed != poam:
            problems.append(f"{r.id}: poam_allowed should be {poam}")

    if catalog.total_weight != TOTAL_WEIGHT:
        problems.append(f"total weight {catalog.total_weight}, expected {TOTAL_WEIGHT}")
    return problems
