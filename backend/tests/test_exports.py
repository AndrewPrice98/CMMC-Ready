import csv
import io
import time

import pytest
from docx import Document

from cmmcready import db, demo, exports
from cmmcready.catalog import load_catalog


@pytest.fixture
def seeded(conn):
    demo.seed(conn)
    titles = {a["title"]: a["id"] for a in db.list_assessments(conn)}
    current = next(i for t, i in titles.items() if t.startswith("Annual"))
    previous = next(i for t, i in titles.items() if t.startswith("Initial"))
    return conn, current, previous


def test_ssp_docx_structure(seeded):
    conn, current, _ = seeded
    start = time.perf_counter()
    data = exports.ssp_docx(conn, current)
    assert time.perf_counter() - start < 2
    doc = Document(io.BytesIO(data))
    assert doc.paragraphs[0].text == exports.DISCLAIMER
    headings = {p.text: p.style.name for p in doc.paragraphs if p.style.name.startswith("Heading")}
    for text in ("1. System identification and boundary", "2. Asset inventory",
                 "3. Security requirements", "4. Organization-defined parameters"):
        assert headings[text] == "Heading 1"
    assert sum(1 for s in headings.values() if s == "Heading 2") >= 14
    ids = sorted(r.id for r in load_catalog().requirements)
    h3 = [p.text.split()[0] for p in doc.paragraphs if p.style.name == "Heading 3"]
    assert sorted(h3) == ids and len(ids) == 110
    cells = "".join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    assert "Harlan Ridge" in cells and "DEMO1" in cells
    assert "TOC" in doc.element.xml
    assert any("Minimum password length" in r.cells[0].text for r in doc.tables[-1].rows)


def test_ssp_evidence_and_na(seeded):
    conn, current, _ = seeded
    doc = Document(io.BytesIO(exports.ssp_docx(conn, current)))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Evidence references" in text and "collector, collected" in text
    assert "Not applicable justification" in text


def test_poam_csv_columns(seeded):
    conn, current, _ = seeded
    rows = list(csv.reader(io.StringIO(exports.poam_csv(conn, current))))
    assert rows[0] == [exports.DISCLAIMER]
    assert rows[1] == exports.POAM_COLUMNS
    count = conn.execute("SELECT COUNT(*) FROM poam_items WHERE assessment_id = ?",
                         (current,)).fetchone()[0]
    assert len(rows) - 2 == count > 0
    assert all(len(r) == len(exports.POAM_COLUMNS) for r in rows[1:])


def test_poam_docx(seeded):
    conn, current, previous = seeded
    doc = Document(io.BytesIO(exports.poam_docx(conn, current)))
    assert doc.paragraphs[0].text == exports.DISCLAIMER
    assert len(doc.tables[0].rows) > 1
    empty = Document(io.BytesIO(exports.poam_docx(conn, previous)))
    assert "No POA&M items." in [p.text for p in empty.paragraphs]


def test_exports_escape_text(seeded):
    conn, current, _ = seeded
    nasty = "<b>x</b> & \"q\" 😀 bell\x07 nul\x00 ctl\x1b " + "é" * 5000
    clean_text = nasty.replace("\x07", "").replace("\x00", "").replace("\x1b", "")
    obj = load_catalog().by_id("3.1.3").objectives[0].id
    db.set_answer(conn, current, obj, "met", note=nasty)
    conn.execute("UPDATE poam_items SET weakness = ?, owner = '=cmd|x' "
                 "WHERE assessment_id = ? AND req_id = '3.1.3'", (nasty, current))
    conn.commit()
    doc = Document(io.BytesIO(exports.ssp_docx(conn, current)))
    body = "\n".join(p.text for p in doc.paragraphs)
    assert clean_text in body
    assert "\x07" not in body and "\x00" not in body
    pdoc = Document(io.BytesIO(exports.poam_docx(conn, current)))
    assert clean_text in [c.text for r in pdoc.tables[0].rows for c in r.cells]
    rows = list(csv.reader(io.StringIO(exports.poam_csv(conn, current))))
    row = next(r for r in rows[2:] if r[1] == "3.1.3")
    assert row[2] == clean_text and row[4] == "'=cmd|x"


def test_sprs_summary(seeded):
    conn, current, previous = seeded
    s = exports.sprs_summary(conn, current)
    assert s["assessment_date"] == "2026-10-12" and s["ssp_version"] == "v2"
    assert s["ssp_name"] == "System Security Plan — Harlan Ridge Aerospace Components (fictional) — v2"
    assert s["scope"]["cage_codes"] == "DEMO1" and not s["provisional"]
    open_due = [r[0] for r in conn.execute(
        "SELECT due_date FROM poam_items WHERE assessment_id = ? AND status != 'closed'", (current,))]
    assert s["poam_completion_date"] == max(open_due)
    p = exports.sprs_summary(conn, previous)
    assert p["ssp_version"] == "v1" and p["provisional"] and p["provisional_note"]
    assert p["poam_completion_date"] == "None"
    md = exports.sprs_markdown(s)
    assert md.startswith(exports.DISCLAIMER) and "Planned POA&M completion date" in md
