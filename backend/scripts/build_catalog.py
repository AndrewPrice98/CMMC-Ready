"""Build backend/data/nist_800_171r2.json from the official NIST publications.

Inputs (download them into a directory of their own):

  1. SP 800-171 Rev 2 security requirements CSV, listed on
     https://csrc.nist.gov/pubs/sp/800/171/r2/upd1/final
     https://csrc.nist.gov/files/pubs/sp/800/171/r2/upd1/final/docs/sp800-171r2-security-reqs.csv
  2. SP 800-171A PDF converted to text with pdftotext (xpdf 4.06 was used):
     https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-171a.pdf
     pdftotext -raw -enc UTF-8 NIST.SP.800-171a.pdf sp800-171a.txt

The SP 800-171 Rev 2 PDF is the authoritative text
(https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-171r2.pdf).
The CSV matches it word for word apart from the differences corrected below
(TEXT_PERIOD, DISCUSSION_FIXES). Objectives are read from the SP 800-171A PDF
because NIST's 800-171A CSV (and the CPRT export) carry an older wording for
33 of the 320 objectives.

Weights are transcribed from Annex A of the DoD Assessment Methodology v1.2.1
(WEIGHTS below); they are not parsed from a file.

Usage (from the repository root):

  python -I backend/scripts/build_catalog.py R2_CSV A_TXT backend/data/nist_800_171r2.json

Every correction is asserted, so a changed input stops the build instead of
silently producing different data.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

RETRIEVED = "2026-11-09"

FAMILIES = {  # SP 800-171 Rev 2 family number -> (code, name)
    "3.1": ("AC", "Access Control"),
    "3.2": ("AT", "Awareness and Training"),
    "3.3": ("AU", "Audit and Accountability"),
    "3.4": ("CM", "Configuration Management"),
    "3.5": ("IA", "Identification and Authentication"),
    "3.6": ("IR", "Incident Response"),
    "3.7": ("MA", "Maintenance"),
    "3.8": ("MP", "Media Protection"),
    "3.9": ("PS", "Personnel Security"),
    "3.10": ("PE", "Physical Protection"),
    "3.11": ("RA", "Risk Assessment"),
    "3.12": ("CA", "Security Assessment"),
    "3.13": ("SC", "System and Communications Protection"),
    "3.14": ("SI", "System and Information Integrity"),
}

# DoD Assessment Methodology v1.2.1, Annex A "Value" column. Every requirement
# not listed here is worth 1. 3.5.3 and 3.13.11 are "3 to 5" (stored as 5 with a
# partial value of 3); 3.12.4 is "NA" (stored as 0).
WEIGHTS = {
    5: """3.1.1 3.1.2 3.1.12 3.1.13 3.1.16 3.1.17 3.1.18 3.2.1 3.2.2 3.3.1 3.3.5
          3.4.1 3.4.2 3.4.5 3.4.6 3.4.7 3.4.8 3.5.1 3.5.2 3.5.3 3.5.10 3.6.1 3.6.2
          3.7.2 3.7.5 3.8.3 3.8.7 3.9.2 3.10.1 3.10.2 3.11.2 3.12.1 3.12.3 3.13.1
          3.13.2 3.13.5 3.13.6 3.13.11 3.13.15 3.14.1 3.14.2 3.14.3 3.14.4
          3.14.6""".split(),
    3: """3.1.5 3.1.19 3.3.2 3.7.1 3.7.4 3.8.1 3.8.2 3.8.8 3.9.1 3.11.1 3.12.2
          3.13.8 3.14.5 3.14.7""".split(),
    0: ["3.12.4"],
}
PARTIAL = {
    "3.5.3": {"mfa_remote_privileged_only": 3},
    "3.13.11": {"encryption_not_fips": 3},
}
# 32 CFR 170.21(a)(2)(iii): weight-1 requirements that may not be on a POA&M.
POAM_EXCLUDED = {"3.1.20", "3.1.22", "3.10.3", "3.10.4", "3.10.5", "3.12.4"}

# Requirement statements whose CSV text lacks the closing period the PDF has.
TEXT_PERIOD = {
    "3.1.6", "3.1.10", "3.1.16", "3.1.17", "3.3.1", "3.3.7", "3.5.11", "3.8.2",
    "3.9.2", "3.11.1",
}
# Discussion text where the CSV differs from the PDF: (old, new), each old
# string must occur exactly once. The PDF wording is kept, including its slips.
DISCUSSION_FIXES = {
    "3.1.9": ("approval of warning banner content", "approval of warning banner content."),
    "3.1.11": ("restrictions on system use", "restrictions on system use."),
    "3.1.16": ("[SP 800-97] provides guidance", "[SP 800-97] provide guidance"),
    "3.3.9": ("with audit-related privileges", "with audit-related privileges."),
    "3.4.1": ("established baseline configuration.", "established baseline configuration"),
    "3.5.8": ("do not apply to temporary passwords", "do not apply to temporary passwords."),
    "3.8.2": ("or a controlled media library", "or a controlled media library."),
    "3.13.5": ("security for virtualization technologies", "security for virtualization technologies."),
    "3.13.9": ("for specific network accesses", "for specific network accesses."),
    "3.14.3": ("peer or supporting organizations.", "peer or supporting organizations"),
}

SOURCE = {
    "description": (
        "NIST SP 800-171 Rev 2 security requirements, discussion and footnotes; "
        "NIST SP 800-171A assessment objectives; DoD Assessment Methodology v1.2.1 "
        "point values; 32 CFR 170.21 POA&M rules. U.S. Government works, included "
        "with attribution."
    ),
    "retrieved": RETRIEVED,
    "documents": [
        {
            "title": "NIST SP 800-171 Revision 2, Protecting Controlled Unclassified "
                     "Information in Nonfederal Systems and Organizations (February 2020, "
                     "includes updates as of January 28, 2021)",
            "url": "https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-171r2.pdf",
            "page": "https://csrc.nist.gov/pubs/sp/800/171/r2/upd1/final",
            "used_for": "authoritative text; the CSV below was checked against it word for word",
        },
        {
            "title": "NIST SP 800-171 Revision 2 security requirements (CSV)",
            "url": "https://csrc.nist.gov/files/pubs/sp/800/171/r2/upd1/final/docs/"
                   "sp800-171r2-security-reqs.csv",
            "used_for": "requirement text, discussion paragraphs, footnotes, basic/derived",
        },
        {
            "title": "NIST SP 800-171A, Assessing Security Requirements for Controlled "
                     "Unclassified Information (June 2018)",
            "url": "https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-171a.pdf",
            "page": "https://csrc.nist.gov/pubs/sp/800/171/a/final",
            "used_for": "assessment objectives",
        },
        {
            "title": "DoD NIST SP 800-171 Assessment Methodology, Version 1.2.1 "
                     "(June 24, 2020), Section 5 and Annex A",
            "url": "https://www.acq.osd.mil/asda/dpc/cp/cyber/docs/safeguarding/"
                   "NIST-SP-800-171-Assessment-Methodology-Version-1.2.1-6.24.2020.pdf",
            "used_for": "weight and partial values",
        },
        {
            "title": "32 CFR 170.21, Plan of Action and Milestones requirements",
            "url": "https://www.ecfr.gov/api/versioner/v1/full/2025-01-01/"
                   "title-32.xml?part=170&section=170.21",
            "used_for": "poam_allowed",
        },
    ],
    "notes": [
        "Whitespace is normalized. A double space in the NIST CSV discussion marks a "
        "paragraph break in the PDF; paragraphs are separated by a blank line.",
        "Footnote markers such as [24] are removed from requirement text, and each "
        "footnote is attached to the requirement that references it (footnotes field).",
        "Where the Rev 2 CSV differs from the Rev 2 PDF, the PDF wording is used: a "
        "closing period is restored to the requirement text of "
        + ", ".join(sorted(TEXT_PERIOD, key=lambda i: [int(p) for p in i.split(".")]))
        + "; discussion text is corrected for "
        + ", ".join(DISCUSSION_FIXES) + ".",
        "Objectives are read from the SP 800-171A PDF. A single objective, which the "
        "PDF prints without a letter, is given the ID [a]; the leading 'Determine if' "
        "is removed from every objective.",
        "weight 0 for 3.12.4: Annex A value 'NA'. weight 5 plus a partial value of 3 "
        "for 3.5.3 and 3.13.11: Annex A value '3 to 5' (Section 5(e)).",
    ],
}

WS = re.compile(r"\s+")
MARKER = re.compile(r"\[(\d+)\]")
FOOTNOTE_START = re.compile(r"\n\s*\[(\d+)\]\s*")
PAGE_FURNITURE = re.compile(
    r"^(NIST SP 800-171A ASSESSING SECURITY REQUIREMENTS"
    r"|_{10,}$"
    r"|(CHAPTER THREE|APPENDIX A) PAGE \d+$"
    r"|This publication is available free of charge"
    r"|3\.\d+ [A-Z ,]+$)"  # family heading
)


def squash(text: str) -> str:
    return WS.sub(" ", text).strip()


def id_key(req_id: str) -> tuple[int, ...]:
    return tuple(int(p) for p in req_id.split("."))


def join_lines(lines: list[str]) -> str:
    """Join PDF text lines. A line ending in a hyphen continues the same word."""
    out = ""
    for line in lines:
        if not line:
            continue
        if out.endswith("-") or not out:
            out += line
        else:
            out += " " + line
    return out


def split_discussion(raw: str) -> tuple[str, dict[int, str]]:
    """Return (discussion with paragraphs, {footnote number: text})."""
    parts = FOOTNOTE_START.split(raw)
    body, rest = parts[0], parts[1:]
    footnotes = {int(num): squash(text) for num, text in zip(rest[0::2], rest[1::2])}
    assert "\n" not in body.strip(), "unexpected line break in discussion body"
    paragraphs = [squash(p) for p in re.split(r"(?<=[.)\]])  +(?=\S)", body.strip())]
    return "\n\n".join(p for p in paragraphs if p), footnotes


def requirement_text(req_id: str, raw: str) -> tuple[str, list[int]]:
    markers = [int(n) for n in MARKER.findall(raw)]
    text = squash(MARKER.sub("", raw))
    text = re.sub(r"\.\s*\.$", ".", text)
    if not text.endswith("."):
        assert req_id in TEXT_PERIOD, f"{req_id}: unexpected text ending {text[-20:]!r}"
        text += "."
    else:
        assert req_id not in TEXT_PERIOD, f"{req_id}: period no longer missing"
    return text, markers


def fix_discussion(req_id: str, discussion: str) -> str:
    if req_id not in DISCUSSION_FIXES:
        return discussion
    old, new = DISCUSSION_FIXES[req_id]
    assert discussion.count(old) == 1, f"{req_id}: {old!r} not found exactly once"
    if new.startswith(old):  # restoring a final period: must be at the end
        assert discussion.endswith(old), f"{req_id}: {old!r} is not at the end"
    return discussion.replace(old, new)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [{k.strip(): v for k, v in row.items()} for row in csv.DictReader(f)]


def read_objectives(path: Path) -> dict[str, list[dict[str, str]]]:
    """Parse assessment objectives from `pdftotext -raw` output of SP 800-171A."""
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    start = next(i for i, l in enumerate(lines) if l == "3.1 ACCESS CONTROL" and i > 300)
    end = next(i for i, l in enumerate(lines) if l == "APPENDIX A" and i > start)

    blocks: dict[str, list[str]] = {}
    current = None
    for line in lines[start:end]:
        if PAGE_FURNITURE.match(line):
            continue
        m = re.fullmatch(r"(3\.\d+\.\d+) SECURITY REQUIREMENT", line)
        if m:
            current = m.group(1)
            blocks[current] = []
        elif current:
            blocks[current].append(line)

    objectives: dict[str, list[dict[str, str]]] = {}
    for req_id, block in blocks.items():
        first = block.index("ASSESSMENT OBJECTIVE") + 1
        last = block.index("POTENTIAL ASSESSMENT METHODS AND OBJECTS")
        text = squash(join_lines(block[first:last]))
        if text.startswith("Determine if:"):
            parts = re.split(r"(3\.\d+\.\d+)\.?\[([a-z])\]\s*", text[len("Determine if:"):].strip())
            assert parts[0] == "", f"{req_id}: text before first objective"
            found = []
            for i in range(1, len(parts), 3):
                obj_req, letter, obj_text = parts[i], parts[i + 1], parts[i + 2].strip()
                assert obj_req == req_id, f"{req_id}: stray objective {obj_req}"
                assert letter == chr(ord("a") + len(found)), f"{req_id}[{letter}] out of order"
                assert obj_text, f"{req_id}[{letter}] is empty"
                found.append({"id": f"{req_id}[{letter}]", "text": obj_text})
            objectives[req_id] = found
        else:
            assert text.startswith("Determine if "), f"{req_id}: {text[:40]!r}"
            objectives[req_id] = [{"id": f"{req_id}[a]", "text": text[len("Determine if "):]}]
    return objectives


def build(r2_csv: Path, a_txt: Path) -> dict:
    rows = read_csv(r2_csv)
    objectives = read_objectives(a_txt)
    weights = {rid: w for w, ids in WEIGHTS.items() for rid in ids}

    all_footnotes: dict[int, str] = {}
    parsed = []
    for row in rows:
        rid = row["Identifier"].strip()
        text, markers = requirement_text(rid, row["Security Requirement"])
        discussion, footnotes = split_discussion(row["Discussion"])
        all_footnotes.update(footnotes)
        parsed.append((rid, row, text, markers, fix_discussion(rid, discussion)))

    requirements = []
    used_footnotes: set[int] = set()
    for rid, row, text, markers, discussion in parsed:
        code, name = FAMILIES[rid.rsplit(".", 1)[0]]
        assert squash(row["Family"]).lower() == name.lower(), (rid, row["Family"])
        kind = row["Basic/Derived Security Requirement"].strip()
        assert kind in {"Basic", "Derived"}, (rid, kind)
        weight = weights.get(rid, 1)
        used_footnotes.update(markers)
        requirements.append({
            "id": rid,
            "family": code,
            "family_name": name,
            "basic": kind == "Basic",
            "text": text,
            "discussion": discussion,
            "footnotes": [all_footnotes[n] for n in markers],
            "weight": weight,
            "partial": PARTIAL.get(rid),
            "poam_allowed": (weight == 1 and rid not in POAM_EXCLUDED) or rid == "3.13.11",
            "objectives": objectives.pop(rid),
        })

    assert used_footnotes == set(all_footnotes), "unreferenced or missing footnotes"
    assert not objectives, f"objectives without a requirement: {sorted(objectives)}"
    assert set(weights) <= {r["id"] for r in requirements}, "weight for unknown requirement"
    ids = [r["id"] for r in requirements]
    assert ids == sorted(ids, key=id_key) and len(ids) == 110
    assert sum(len(r["objectives"]) for r in requirements) == 320
    assert sum(r["weight"] for r in requirements) == 313
    return {"source": SOURCE, "requirements": requirements}


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    r2_csv, a_txt, out = (Path(a) for a in argv)
    data = build(r2_csv, a_txt)
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
