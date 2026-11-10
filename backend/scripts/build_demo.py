"""Build backend/data/demo_fixture.json, the fictional demo organization.

Deterministic: running it twice gives identical output, and a test checks
that the committed fixture equals a fresh build. Everything here is invented.
The two Windows hosts and the Microsoft 365 export are derived from the
synthetic collector fixtures in backend/tests/fixtures with new host names.

    python scripts/build_demo.py            # write the fixture
    python scripts/build_demo.py --check    # exit 1 if the committed file is stale
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import date, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cmmcready.catalog import load_catalog  # noqa: E402
from cmmcready.evidence.engine import DEFAULT_ODP  # noqa: E402
from demo_notes import (  # noqa: E402
    GAPS, NA_JUSTIFICATIONS, OBJ_NOTES, POAM, PREV_DEFAULT_GAP_NOTE, PREV_EXTRA_GAPS,
    PREV_NOTES_MET, PREV_PARTIAL_NOTE, REQ_NOTES,
)

OUT = BACKEND / "data" / "demo_fixture.json"
FIXTURES = BACKEND / "tests" / "fixtures"

CURRENT_START = date(2026, 10, 12)
PREVIOUS_START = date(2026, 6, 1)
PREVIOUS_END = date(2026, 6, 19)

ORGANIZATION = {
    "name": "Harlan Ridge Aerospace Components (fictional)",
    "cage_codes": "DEMO1",
    "description": (
        "A fictional 48-person machine shop that makes brackets and housings for aerospace "
        "prime contractors. Invented for this demo; it is not a real company."
    ),
    "cui_boundary": (
        "The CUI boundary covers the engineering workstations, the CUI file server FS-01, the "
        "company's Microsoft 365 GCC High tenant and the PLM vault. Identity, firewall and "
        "logging systems are security protection assets. The managed service provider's remote "
        "support tool and the badge system are contractor risk managed assets. CNC machine "
        "controllers are specialized assets. Guest Wi-Fi and back-office finance PCs are "
        "outside the boundary."
    ),
}

ASSETS = [
    ("Engineering workstations (ENG-WS-01 to ENG-WS-12)", "cui", "Windows 11 workstations used to create and edit CUI drawings and models."),
    ("CUI file server FS-01", "cui", "Windows Server 2022 file server holding controlled drawings and program data."),
    ("Microsoft 365 GCC High tenant", "cui", "Exchange Online, SharePoint and Teams, including the CUI SharePoint site."),
    ("PLM vault", "cui", "Product lifecycle management application and database for released drawings."),
    ("Identity services (DC-01, Entra ID)", "spa", "Active Directory domain controller and Entra ID tenant that authenticate all users."),
    ("Perimeter firewall pair (FW-01, FW-02)", "spa", "Next-generation firewalls that separate the VLANs and terminate the VPN."),
    ("Log server LOG-01", "spa", "Collects Windows, firewall and Microsoft 365 audit logs and raises alerts."),
    ("Managed service provider remote support tool", "crma", "Remote administration tool used by the outsourced IT provider under a signed responsibility matrix."),
    ("Badge and door controller", "crma", "Cloud-managed physical access control for the building, engineering office and server room."),
    ("CNC machine controllers and CMM inspection station", "specialized", "Operational technology on an isolated shop-floor VLAN that receives program files from FS-01."),
    ("Guest Wi-Fi", "out_of_scope", "Landlord-provided internet for visitors on a separate line. No path to the company network."),
    ("Back-office finance PCs", "out_of_scope", "Accounting and payroll computers that never handle CUI and sit on their own VLAN."),
]

NA_REQS = set(NA_JUSTIFICATIONS)  # N/A in both assessments
PARTIAL_CURRENT = {"3.5.3": "mfa_remote_privileged_only"}


def _stamp(d: date, hour: int = 14, minute: int = 0) -> str:
    return f"{d.isoformat()}T{hour:02d}:{minute:02d}:00Z"


def _ids(req, letters):
    """Objective IDs of a requirement that a gap covers (None = all)."""
    return [o.id for o in req.objectives
            if letters is None or o.id.split("[")[1][:-1] in letters]


def _plan(current: bool) -> dict[str, tuple[tuple[str, ...] | None, str | None]]:
    """requirement -> (not-met letters or None for all, note for the first not-met objective)."""
    if current:
        plan = dict(GAPS)
        plan["3.5.3"] = (("d",), None)
        return plan
    plan = {req: (None, PREV_DEFAULT_GAP_NOTE) for req in GAPS}
    plan.update(PREV_EXTRA_GAPS)
    plan["3.5.3"] = (("b", "c", "d"), PREV_PARTIAL_NOTE)
    return plan


def _answers(catalog, start: date, *, current: bool) -> list[dict]:
    plan = _plan(current)
    rows = []
    for index, req in enumerate(catalog.requirements):
        not_met: dict[str, str] = {}
        if req.id in plan:
            letters, note = plan[req.id]
            for n, oid in enumerate(_ids(req, letters)):
                not_met[oid] = note or "" if n == 0 else ""
        answered = _stamp(start + timedelta(days=index % 18))
        for n, obj in enumerate(req.objectives):
            note = justification = ""
            if req.id in NA_REQS:
                answer = "na"
                justification = NA_JUSTIFICATIONS[req.id]
            elif obj.id in not_met:
                answer, note = "not_met", not_met[obj.id]
            else:
                answer = "met"
                if n == 0:
                    note = (REQ_NOTES.get(req.id, "") if current
                            else PREV_NOTES_MET.get(req.id, ""))
            if current and obj.id in OBJ_NOTES:
                note = OBJ_NOTES[obj.id]
            rows.append({
                "objective_id": obj.id, "answer": answer, "note": note,
                "justification": justification, "answered_at": answered,
            })
    return rows


def _load(name: str) -> dict:
    with open(FIXTURES / name, encoding="utf-8") as handle:
        return json.load(handle)


def _evidence() -> list[dict]:
    base = _load("windows-compliant.json")
    broken = _load("windows-noncompliant.json")

    eng = copy.deepcopy(base)
    eng["host"]["name"] = "ENG-WS-01"

    fs = copy.deepcopy(base)
    fs["host"].update({"name": "FS-01", "os": "Microsoft Windows Server 2022 Standard",
                       "build": "20348"})
    fs["collected_at"] = "2026-11-01T14:20:00Z"
    # Settings that disagree with what the assessor recorded (deliberate conflicts).
    for check in ("screen_lock", "smb1", "usb_storage"):
        fs["checks"][check] = copy.deepcopy(broken["checks"][check])

    m365 = _load("m365-admin-mfa-only.json")
    return [
        {"collector": "windows", "collected_at": eng["collected_at"], "host": "ENG-WS-01",
         "uploaded_at": "2026-11-03T15:00:00Z", "raw": eng},
        {"collector": "windows", "collected_at": fs["collected_at"], "host": "FS-01",
         "uploaded_at": "2026-11-03T15:05:00Z", "raw": fs},
        {"collector": "m365", "collected_at": m365["collected_at"], "host": m365["tenant"]["id"],
         "uploaded_at": "2026-11-03T15:10:00Z", "raw": m365},
    ]


def _poam() -> list[dict]:
    return [{
        "req_id": item["req"], "weakness": item["weakness"], "remediation": item["remediation"],
        "owner": item["owner"], "due_date": item["due"], "status": item["status"],
        "milestones": [{"description": d, "due": due, "done": done}
                       for d, due, done in item["milestones"]],
    } for item in POAM]


def build() -> dict:
    catalog = load_catalog()
    odp = dict(DEFAULT_ODP)
    return {
        "organization": ORGANIZATION,
        "assets": [{"name": n, "category": c, "description": d} for n, c, d in ASSETS],
        "assessments": [
            {
                "key": "previous",
                "title": "Initial self-assessment, June 2026",
                "started_at": _stamp(PREVIOUS_START, 13),
                "completed_at": _stamp(PREVIOUS_END, 16),
                "odp": {**odp, "min_password_length": 12, "lockout_threshold": 10},
                "partial_choices": {},
                "answers": _answers(catalog, PREVIOUS_START, current=False),
                "evidence": [],
                "poam": [],
            },
            {
                "key": "current",
                "title": "Annual self-assessment, autumn 2026",
                "started_at": _stamp(CURRENT_START, 13),
                "completed_at": None,
                "odp": odp,
                "partial_choices": dict(PARTIAL_CURRENT),
                "answers": _answers(catalog, CURRENT_START, current=True),
                "evidence": _evidence(),
                "poam": _poam(),
            },
        ],
    }


def render() -> str:
    return json.dumps(build(), indent=1, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the committed fixture is stale")
    args = parser.parse_args()
    text = render()
    if args.check:
        current = OUT.read_text(encoding="utf-8").replace("\r\n", "\n") if OUT.exists() else ""
        if current != text:
            print("demo_fixture.json is out of date; run scripts/build_demo.py", file=sys.stderr)
            return 1
        return 0
    with open(OUT, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
