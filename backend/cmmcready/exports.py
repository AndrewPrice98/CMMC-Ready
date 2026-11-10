"""Document exports: SSP (DOCX), POA&M (DOCX, CSV) and the SPRS summary (Markdown).

Every export opens with the disclaimer. All text is passed through ``clean`` so
control characters that XML forbids are dropped instead of crashing the build.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
from collections import defaultdict

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from . import db
from .catalog import Requirement, load_catalog
from .poam import parse_date
from .scoring import requirement_status

DISCLAIMER = (
    "CMMC Ready is a self-assessment aid. It does not certify compliance or replace an "
    "assessment by a C3PAO or DIBCAC."
)

CATEGORY_LABELS = {
    "cui": "CUI assets",
    "spa": "Security protection assets",
    "crma": "Contractor risk managed assets",
    "specialized": "Specialized assets",
    "out_of_scope": "Out-of-scope assets",
}
STATUS_LABELS = {
    "met": "Implemented", "not_met": "Not implemented",
    "na": "Not applicable", "not_assessed": "Not assessed",
}
ODP_LABELS = {
    "min_password_length": ("Minimum password length", "characters"),
    "lockout_threshold": ("Lockout threshold (maximum failed attempts)", "attempts"),
    "session_lock_minutes": ("Session lock (maximum inactivity)", "minutes"),
    "password_history": ("Password history (minimum remembered)", "passwords"),
    "audit_retention_days": ("Audit log retention (minimum)", "days"),
    "max_patch_age_days": ("Maximum patch age", "days"),
    "max_signin_frequency_hours": ("Maximum sign-in frequency", "hours"),
}
POAM_COLUMNS = ["POA&M ID", "Requirement", "Weakness", "Remediation", "Owner",
                "Milestones", "Scheduled completion", "Status"]

# XML 1.0 forbids these; lone surrogates cannot be encoded at all.
_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")


def clean(value: object) -> str:
    return _ILLEGAL.sub("", "" if value is None else str(value))


# -- data gathering ---------------------------------------------------------------------------

def _context(conn: sqlite3.Connection, assessment_id: int) -> dict:
    assessment = db.get_assessment(conn, assessment_id)
    if assessment is None:
        raise ValueError("unknown assessment")
    org = conn.execute("SELECT * FROM organization WHERE id = ?",
                       (assessment["org_id"],)).fetchone()
    org = dict(org) if org else {"name": "", "cage_codes": "", "description": "",
                                 "cui_boundary": "", "id": assessment["org_id"]}
    ordinal = conn.execute(
        "SELECT COUNT(*) FROM assessments WHERE org_id = ? AND "
        "(started_at < ? OR (started_at = ? AND id <= ?))",
        (assessment["org_id"], assessment["started_at"], assessment["started_at"],
         assessment_id)).fetchone()[0]
    when = parse_date(assessment["completed_at"] or assessment["started_at"])
    return {"assessment": assessment, "org": org, "version": f"v{ordinal}", "date": when}


def _poam_items(conn: sqlite3.Connection, assessment_id: int) -> list[dict]:
    rows = conn.execute("SELECT * FROM poam_items WHERE assessment_id = ? ORDER BY id",
                        (assessment_id,)).fetchall()
    items = []
    for r in rows:
        item = dict(r)
        try:
            item["milestones"] = json.loads(item.pop("milestone_json") or "[]")
        except ValueError:
            item["milestones"] = []
        items.append(item)
    return sorted(items, key=lambda i: (tuple(int(p) for p in i["req_id"].split(".")), i["id"]))


def _milestone_text(m: object) -> str:
    if not isinstance(m, dict):
        return clean(m)
    text = clean(m.get("description", ""))
    extra = ", ".join(x for x in (f"due {m['due']}" if m.get("due") else "",
                                  "done" if m.get("done") else "") if x)
    return f"{text} ({extra})" if extra else text


def sprs_summary(conn: sqlite3.Connection, assessment_id: int) -> dict:
    ctx = _context(conn, assessment_id)
    result = db.current_score(conn, assessment_id)
    open_due = [i["due_date"] for i in _poam_items(conn, assessment_id)
                if i["status"] != "closed" and i["due_date"]]
    note = ""
    if result.provisional:
        parts = []
        if result.ssp_missing:
            parts.append("requirement 3.12.4 (system security plan) is not met")
        if result.not_assessed:
            parts.append(f"{result.not_assessed} requirement(s) are not yet assessed")
        note = "Provisional: " + "; ".join(parts) + "."
    org = ctx["org"]
    return {
        "assessment_date": ctx["date"].isoformat(),
        "score": result.score,
        "max_score": result.max,
        "provisional": result.provisional,
        "provisional_note": note,
        "scope": {"organization": org["name"], "cage_codes": org["cage_codes"]},
        "ssp_name": f"System Security Plan — {org['name']} — {ctx['version']}",
        "ssp_version": ctx["version"],
        "poam_completion_date": max(open_due) if open_due else "None",
    }


def sprs_markdown(summary: dict) -> str:
    score = f"{summary['score']} (maximum {summary['max_score']})"
    if summary["provisional"]:
        score += " — provisional"
    lines = [
        DISCLAIMER, "", "# SPRS summary", "",
        "Values to enter in SPRS for this self-assessment.", "",
        f"- **Assessment date:** {summary['assessment_date']}",
        f"- **Score:** {score}",
    ]
    if summary["provisional_note"]:
        lines.append(f"- **Note:** {summary['provisional_note']}")
    lines += [
        f"- **Scope:** {summary['scope']['organization']}; CAGE code(s): "
        f"{summary['scope']['cage_codes'] or 'none recorded'}",
        f"- **System Security Plan:** {summary['ssp_name']} (version {summary['ssp_version']})",
        f"- **Planned POA&M completion date:** {summary['poam_completion_date']}",
        "",
    ]
    return "\n".join(lines)


# -- POA&M CSV ---------------------------------------------------------------------------------

def _csv_safe(value: object) -> str:
    """Neutralise spreadsheet formulas in untrusted text."""
    text = clean(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def poam_csv(conn: sqlite3.Connection, assessment_id: int) -> str:
    items = _poam_items(conn, assessment_id)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow([DISCLAIMER])
    writer.writerow(POAM_COLUMNS)
    for i in items:
        writer.writerow([_csv_safe(v) for v in (
            i["id"], i["req_id"], i["weakness"], i["remediation"], i["owner"],
            "; ".join(_milestone_text(m) for m in i["milestones"]),
            i["due_date"] or "", i["status"])])
    return out.getvalue()


# -- DOCX helpers ------------------------------------------------------------------------------

def _new_document(landscape: bool = False):
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)
    for name, size in (("Title", 26), ("Heading 1", 16), ("Heading 2", 13), ("Heading 3", 11.5)):
        style = doc.styles[name]
        style.font.name = "Calibri"
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)
    section = doc.sections[0]
    if landscape:
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width, section.page_height = section.page_height, section.page_width
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run("Page ")
    _field(p, "PAGE", "1")
    return doc


def _field(paragraph, instruction: str, placeholder: str = "") -> None:
    def mark(kind):
        run = paragraph.add_run()
        el = OxmlElement("w:fldChar")
        el.set(qn("w:fldCharType"), kind)
        run._r.append(el)

    mark("begin")
    run = paragraph.add_run()
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" {instruction} "
    run._r.append(instr)
    mark("separate")
    paragraph.add_run(placeholder)
    mark("end")


def _disclaimer(doc) -> None:
    run = doc.add_paragraph().add_run(DISCLAIMER)
    run.italic = True
    run.bold = True


def _table(doc, header: list[str], rows: list[list[str]]):
    table = doc.add_table(rows=1, cols=len(header))
    table.style = "Table Grid"
    for cell, text in zip(table.rows[0].cells, header):
        cell.paragraphs[0].add_run(clean(text)).bold = True
        shade = OxmlElement("w:shd")
        shade.set(qn("w:val"), "clear")
        shade.set(qn("w:fill"), "D9E2F3")
        cell._tc.get_or_add_tcPr().append(shade)
    flag = OxmlElement("w:tblHeader")  # repeat the header row on each page
    flag.set(qn("w:val"), "true")
    table.rows[0]._tr.get_or_add_trPr().append(flag)
    for row in rows:
        for cell, text in zip(table.add_row().cells, row):
            cell.text = clean(text)
    return table


def _short(text: str, n: int = 80) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _to_bytes(doc) -> bytes:
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# -- SSP ---------------------------------------------------------------------------------------

def _evidence_by_objective(conn: sqlite3.Connection, assessment_id: int) -> dict[str, list[dict]]:
    rows = conn.execute(
        "SELECT f.objective_id, e.host, e.collector, e.collected_at, f.check_id, f.result "
        "FROM findings f JOIN evidence e ON e.id = f.evidence_id "
        "WHERE e.assessment_id = ? ORDER BY e.id, f.check_id", (assessment_id,)).fetchall()
    grouped: dict[str, dict[tuple, dict]] = defaultdict(dict)
    for r in rows:
        key = (r["host"], r["collector"], r["collected_at"])
        entry = grouped[r["objective_id"]].setdefault(
            key, {"host": r["host"], "collector": r["collector"],
                  "collected_at": r["collected_at"], "checks": []})
        label = f"{r['check_id']} ({r['result']})"
        if label not in entry["checks"]:
            entry["checks"].append(label)
    return {obj: list(v.values()) for obj, v in grouped.items()}


def _requirement_section(doc, req: Requirement, status: str, points: int,
                         choice: str | None, answers: dict, evidence: dict) -> None:
    doc.add_heading(clean(f"{req.id} {_short(req.text)}"), level=3)
    doc.add_paragraph(clean(req.text))
    met = sum(1 for o in req.objectives if o.id in answers and answers[o.id]["answer"] == "met")
    na = sum(1 for o in req.objectives if o.id in answers and answers[o.id]["answer"] == "na")
    rows = [
        ["Status", STATUS_LABELS[status]],
        ["Objectives", f"{met} met, {na} not applicable, {len(req.objectives)} total"],
        ["Weight", str(req.weight)],
        ["Points deducted", str(points)],
    ]
    if choice:
        rows.append(["Partial credit", choice.replace("_", " ")])
    _table(doc, ["Item", "Value"], rows)

    doc.add_paragraph().add_run("Implementation statement").bold = True
    statements = [(o.id, answers[o.id]["note"]) for o in req.objectives
                  if o.id in answers and answers[o.id]["note"].strip()]
    if statements:
        for obj_id, note in statements:
            doc.add_paragraph(clean(f"{obj_id[len(req.id):]} {note}"), style="List Bullet")
    else:
        doc.add_paragraph("No implementation statement recorded.")

    refs = [(o.id, ref) for o in req.objectives for ref in evidence.get(o.id, [])]
    if refs:
        doc.add_paragraph().add_run("Evidence references").bold = True
        for obj_id, ref in refs:
            doc.add_paragraph(clean(
                f"{obj_id[len(req.id):]} {ref['host']} — {ref['collector']} collector, "
                f"collected {ref['collected_at']}; checks: {', '.join(ref['checks'])}"),
                style="List Bullet")

    nas = [(o.id, answers[o.id]["justification"]) for o in req.objectives
           if o.id in answers and answers[o.id]["answer"] == "na"]
    if nas:
        doc.add_paragraph().add_run("Not applicable justification").bold = True
        for obj_id, text in nas:
            doc.add_paragraph(clean(f"{obj_id[len(req.id):]} {text}"), style="List Bullet")


def ssp_docx(conn: sqlite3.Connection, assessment_id: int) -> bytes:
    ctx = _context(conn, assessment_id)
    assessment, org = ctx["assessment"], ctx["org"]
    catalog = load_catalog()
    result = db.current_score(conn, assessment_id)
    answers = {r["objective_id"]: r for r in conn.execute(
        "SELECT * FROM answers WHERE assessment_id = ?", (assessment_id,))}
    plain = {k: v["answer"] for k, v in answers.items()}
    evidence = _evidence_by_objective(conn, assessment_id)
    deducted = {d.req_id: d.points for d in result.deductions}
    choices = assessment["partial_choices"]

    doc = _new_document()
    # Title page: the disclaimer is the first paragraph of the document.
    _disclaimer(doc)
    doc.add_paragraph()
    doc.add_paragraph(clean("System Security Plan"), style="Title")
    doc.add_paragraph().add_run(clean(org["name"])).font.size = Pt(16)
    _table(doc, ["Item", "Value"], [
        ["Organization", org["name"]],
        ["CAGE code(s)", org["cage_codes"] or "none recorded"],
        ["Assessment", assessment["title"]],
        ["Assessment date", ctx["date"].isoformat()],
        ["Version", ctx["version"]],
        ["SPRS score", f"{result.score} of {result.max}"
                       + (" (provisional)" if result.provisional else "")],
    ])
    doc.add_page_break()

    doc.add_heading("Table of contents", level=1)
    _field(doc.add_paragraph(), 'TOC \\o "1-3" \\h \\z \\u',
           "Right-click and choose Update Field to build the table of contents.")
    doc.add_page_break()

    doc.add_heading("1. System identification and boundary", level=1)
    doc.add_heading("Organization", level=2)
    doc.add_paragraph(clean(org["description"] or "No description recorded."))
    doc.add_heading("CUI boundary", level=2)
    doc.add_paragraph(clean(org["cui_boundary"] or "No boundary description recorded."))

    doc.add_heading("2. Asset inventory", level=1)
    assets = conn.execute("SELECT * FROM assets WHERE org_id = ? ORDER BY id",
                          (org["id"],)).fetchall()
    for cat, label in CATEGORY_LABELS.items():
        group = [a for a in assets if a["category"] == cat]
        doc.add_heading(label, level=2)
        if group:
            _table(doc, ["Asset", "Description"], [[a["name"], a["description"]] for a in group])
        else:
            doc.add_paragraph("None recorded.")

    doc.add_heading("3. Security requirements", level=1)
    for family in catalog.families():
        doc.add_heading(clean(f"{family.number} {family.name} ({family.code})"), level=2)
        for req in catalog.requirements:
            if req.family == family.code:
                _requirement_section(doc, req, requirement_status(req, plain),
                                     deducted.get(req.id, 0), choices.get(req.id),
                                     answers, evidence)

    doc.add_heading("4. Organization-defined parameters", level=1)
    doc.add_paragraph("Values chosen for this assessment; automated checks compare "
                      "collected evidence against them.")
    rows = []
    for name, value in assessment["odp"].items():
        label, unit = ODP_LABELS.get(name, (name.replace("_", " ").capitalize(), ""))
        rows.append([label, f"{value} {unit}".strip()])
    _table(doc, ["Parameter", "Value"], rows)
    return _to_bytes(doc)


# -- POA&M DOCX --------------------------------------------------------------------------------

def poam_docx(conn: sqlite3.Connection, assessment_id: int) -> bytes:
    ctx = _context(conn, assessment_id)
    org = ctx["org"]
    items = _poam_items(conn, assessment_id)
    doc = _new_document(landscape=True)
    _disclaimer(doc)
    doc.add_paragraph(clean("Plan of Action and Milestones"), style="Title")
    doc.add_paragraph(clean(f"{org['name']} — CAGE {org['cage_codes'] or 'none recorded'} — "
                            f"{ctx['date'].isoformat()} — {ctx['version']}"))
    doc.add_heading("Items", level=1)
    if items:
        _table(doc, POAM_COLUMNS, [[
            str(i["id"]), i["req_id"], i["weakness"], i["remediation"], i["owner"],
            "\n".join(_milestone_text(m) for m in i["milestones"]),
            i["due_date"] or "", i["status"]] for i in items])
    else:
        doc.add_paragraph("No POA&M items.")
    return _to_bytes(doc)
