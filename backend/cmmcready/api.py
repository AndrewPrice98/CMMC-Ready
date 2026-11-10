"""REST API for the CMMC Ready dashboard. All routes live under /api."""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import date
from functools import lru_cache
from typing import Annotated, Any, Iterator, Literal

from fastapi import (APIRouter, Body, Depends, FastAPI, File, HTTPException, Query, Request,
                     Response, UploadFile)
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import __version__, auth, config, db, demo, exports, poam
from .catalog import Requirement, load_catalog
from .evidence.engine import DEFAULT_ODP, ODP_DESCRIPTIONS
from .scoring import ScoreResult, requirement_status, top_gaps
from .uploads import EVIDENCE_MAX_LINE_CHARS, UploadError, decode_json_upload


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if config.demo_mode():
        await run_in_threadpool(demo.ensure_seeded)
    yield


app = FastAPI(
    lifespan=lifespan,
    title="CMMC Ready API",
    version=__version__,
    description="CMMC Level 2 / NIST SP 800-171 Rev 2 self-assessment aid. "
                "It does not certify compliance or replace an assessment by a C3PAO or DIBCAC.",
)

log = logging.getLogger("cmmcready.api")

STATUSES = ("met", "not_met", "na", "not_assessed")
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# Same headers as MiniSIEM's vercel.json.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
        "form-action 'self'"),
}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    for key, value in SECURITY_HEADERS.items():
        response.headers.setdefault(key, value)
    return response


MULTIPART_OVERHEAD = 64 * 1024


@app.middleware("http")
async def reject_oversize(request: Request, call_next):
    """Refuse an announced body over the upload cap before reading any of it."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > config.max_upload_bytes() + MULTIPART_OVERHEAD:
        return JSONResponse(
            {"detail": f"Request too large (max {config.max_upload_bytes() // (1024 * 1024)} MB)"},
            status_code=413)
    return await call_next(request)


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = db.connect()
    try:
        if config.demo_mode() and db.get_organization(conn) is None:
            # Normally seeded at startup; this covers a cold or reset database.
            try:
                demo.seed(conn)
            except Exception:
                conn.rollback()
                log.exception("Demo seeding failed; serving the request anyway")
        yield conn
    finally:
        conn.close()


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
Writer = Depends(auth.require_writer)


# -- catalog lookups and ID validation ------------------------------------------------------

@lru_cache(maxsize=1)
def _req_index() -> dict[str, Requirement]:
    return {r.id: r for r in load_catalog().requirements}


@lru_cache(maxsize=1)
def _objective_index() -> dict[str, Requirement]:
    return {o.id: r for r in load_catalog().requirements for o in r.objectives}


@lru_cache(maxsize=1)
def _family_codes() -> tuple[str, ...]:
    return tuple(f.code for f in load_catalog().families())


_DIGITS = re.compile(r"^[0-9]{1,9}$")


def _int_id(raw: str, what: str) -> int:
    """Junk IDs are 404 without touching the database."""
    if not _DIGITS.match(raw):
        raise HTTPException(404, f"{what} not found")
    return int(raw)


def requirement_dep(req_id: str) -> Requirement:
    req = _req_index().get(req_id)
    if req is None:
        raise HTTPException(404, "requirement not found")
    return req


def assessment_dep(assessment_id: str, conn: Conn) -> dict:
    """The assessment, only if it belongs to the single organization."""
    found = db.get_assessment(conn, _int_id(assessment_id, "assessment"))
    org = db.get_organization(conn)
    if found is None or org is None or found["org_id"] != org["id"]:
        raise HTTPException(404, "assessment not found")
    return found


Assessment = Annotated[dict, Depends(assessment_dep)]
Req = Annotated[Requirement, Depends(requirement_dep)]


# -- shared computation ---------------------------------------------------------------------

class State:
    """Answers, requirement statuses and score for one assessment, computed once."""

    def __init__(self, conn: sqlite3.Connection, assessment: dict):
        self.assessment = assessment
        self.answers = db.get_answers(conn, assessment["id"])
        self.result: ScoreResult = db.current_score(conn, assessment["id"])
        self.catalog = load_catalog()
        self.status = {r.id: requirement_status(r, self.answers) for r in self.catalog.requirements}
        self.lost = {d.req_id: d.points for d in self.result.deductions}


def _conflict_objectives(conn: sqlite3.Connection, assessment_id: int) -> set[str]:
    rows = conn.execute(
        "SELECT DISTINCT f.objective_id FROM findings f JOIN evidence e ON e.id = f.evidence_id "
        "WHERE e.assessment_id = ?", (assessment_id,)).fetchall()
    return {r["objective_id"] for r in rows
            if db.objective_view(conn, assessment_id, r["objective_id"])["conflict"]}


# -- public endpoints -------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"status": "ok", "version": __version__, "auth_configured": auth.is_configured(),
            "demo": config.demo_mode(), "guest": config.guest_enabled()}


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


def _set_session_cookie(response: Response, token: str, expires) -> None:
    response.set_cookie(
        auth.COOKIE_NAME, token, expires=expires,
        httponly=True, secure=config.cookie_secure(), samesite="strict", path="/api",
    )


@app.post("/api/auth/login")
def login(body: LoginRequest, request: Request, response: Response):
    if not auth.is_configured():
        raise HTTPException(503, "Authentication is not configured. Run: python -m cmmcready create-admin")
    ip = auth.client_ip(request)
    wait = auth.limiter.retry_after(ip)
    if wait:
        raise HTTPException(429, "Too many failed logins. Try again later.",
                            headers={"Retry-After": str(wait)})
    if not auth.check_credentials(body.username, body.password):
        auth.limiter.record_failure(ip)
        raise HTTPException(401, "Invalid username or password")
    auth.limiter.reset(ip)
    token, expires = auth.issue_token(body.username)
    _set_session_cookie(response, token, expires)
    return {"username": body.username, "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "token": token}


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(auth.COOKIE_NAME, path="/api", httponly=True,
                           secure=config.cookie_secure(), samesite="strict")
    return {"ok": True}


# -- authenticated endpoints ------------------------------------------------------------------

protected = APIRouter(dependencies=[Depends(auth.require_user)])


@protected.get("/api/auth/me")
def me(user: Annotated[str, Depends(auth.require_user)]):
    return {"username": user, "guest": user == auth.GUEST_USER}


CAGE = re.compile(r"^[A-Za-z0-9]{5}$")


def _org_out(org: dict | None) -> dict | None:
    if org is None:
        return None
    codes = [c.strip() for c in org["cage_codes"].split(",") if c.strip()]
    return {**org, "cage_codes": codes}


@protected.get("/api/organization")
def organization(conn: Conn):
    return _org_out(db.get_organization(conn))


class OrganizationBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    cage_codes: list[str] = Field(default_factory=list, max_length=20)
    description: str = Field(default="", max_length=5000)
    cui_boundary: str = Field(default="", max_length=10000)


@protected.put("/api/organization")
def put_organization(_w: Annotated[str, Writer], body: OrganizationBody, conn: Conn):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "name must not be blank")
    codes = [c.strip().upper() for c in body.cage_codes]
    if not all(CAGE.match(c) for c in codes):
        raise HTTPException(422, "each CAGE code must be 5 letters or digits")
    joined = ", ".join(dict.fromkeys(codes))
    conn.commit()  # no transaction may be open when taking the write lock
    conn.execute("BEGIN IMMEDIATE")  # read-then-write is atomic: two first PUTs cannot both insert
    try:
        existing = db.get_organization(conn)
        if existing is None:
            conn.execute("INSERT INTO organization (name, cage_codes, description, cui_boundary) "
                         "VALUES (?, ?, ?, ?)", (name, joined, body.description, body.cui_boundary))
        else:
            conn.execute("UPDATE organization SET name = ?, cage_codes = ?, description = ?, "
                         "cui_boundary = ? WHERE id = ?",
                         (name, joined, body.description, body.cui_boundary, existing["id"]))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return _org_out(db.get_organization(conn))


def _need_org(conn: sqlite3.Connection) -> dict:
    org = db.get_organization(conn)
    if org is None:
        raise HTTPException(409, "Create the organization first (PUT /api/organization)")
    return org


@protected.get("/api/assets")
def assets(conn: Conn):
    org = db.get_organization(conn)
    if org is None:
        return []
    rows = conn.execute("SELECT id, name, category, description FROM assets WHERE org_id = ? ORDER BY id",
                        (org["id"],)).fetchall()
    return [dict(r) for r in rows]


class AssetBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: Literal["cui", "spa", "crma", "specialized", "out_of_scope"]
    description: str = Field(default="", max_length=5000)


def _asset(conn: sqlite3.Connection, org: dict, raw_id: str) -> dict:
    row = conn.execute("SELECT id, name, category, description FROM assets WHERE id = ? AND org_id = ?",
                       (_int_id(raw_id, "asset"), org["id"])).fetchone()
    if row is None:
        raise HTTPException(404, "asset not found")
    return dict(row)


@protected.post("/api/assets", status_code=201)
def create_asset(_w: Annotated[str, Writer], body: AssetBody, conn: Conn):
    org = _need_org(conn)
    if not body.name.strip():
        raise HTTPException(422, "name must not be blank")
    with conn:
        cur = conn.execute("INSERT INTO assets (org_id, name, category, description) VALUES (?, ?, ?, ?)",
                           (org["id"], body.name.strip(), body.category, body.description))
    return _asset(conn, org, str(cur.lastrowid))


@protected.put("/api/assets/{asset_id}")
def update_asset(_w: Annotated[str, Writer], asset_id: str, body: AssetBody, conn: Conn):
    org = _need_org(conn)
    current = _asset(conn, org, asset_id)
    if not body.name.strip():
        raise HTTPException(422, "name must not be blank")
    with conn:
        conn.execute("UPDATE assets SET name = ?, category = ?, description = ? WHERE id = ?",
                     (body.name.strip(), body.category, body.description, current["id"]))
    return _asset(conn, org, asset_id)


@protected.delete("/api/assets/{asset_id}")
def delete_asset(_w: Annotated[str, Writer], asset_id: str, conn: Conn):
    org = _need_org(conn)
    current = _asset(conn, org, asset_id)
    with conn:
        conn.execute("DELETE FROM assets WHERE id = ?", (current["id"],))
    return {"ok": True}


def _org_assessments(conn: sqlite3.Connection) -> list[dict]:
    org = db.get_organization(conn)
    if org is None:
        return []
    return [a for a in db.list_assessments(conn) if a["org_id"] == org["id"]]


@protected.get("/api/assessments")
def list_assessments(conn: Conn):
    out = []
    for a in _org_assessments(conn):
        result = db.current_score(conn, a["id"])
        out.append({"id": a["id"], "title": a["title"], "started_at": a["started_at"],
                    "completed_at": a["completed_at"], "odp": a["odp"],
                    "score": result.score, "max": result.max, "provisional": result.provisional})
    return out


_WHEN = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}Z)?$")


def _check_when(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    try:
        if not _WHEN.match(value):
            raise ValueError
        date.fromisoformat(value[:10])
    except ValueError:
        raise HTTPException(422, "completed_at must be YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ") from None
    return value


class AssessmentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    copy_from: int | None = Field(default=None, ge=1, le=999_999_999)


class AssessmentPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    completed_at: str | None = Field(default=None, max_length=20)


def _summary(conn: sqlite3.Connection, assessment_id: int) -> dict:
    a = db.get_assessment(conn, assessment_id)
    result = db.current_score(conn, assessment_id)
    return {"id": a["id"], "title": a["title"], "started_at": a["started_at"],
            "completed_at": a["completed_at"], "odp": a["odp"],
            "score": result.score, "max": result.max, "provisional": result.provisional}


@protected.post("/api/assessments", status_code=201)
def create_assessment(_w: Annotated[str, Writer], body: AssessmentCreate, conn: Conn):
    org = _need_org(conn)
    title = body.title.strip()
    if not title:
        raise HTTPException(422, "title must not be blank")
    source = None
    if body.copy_from is not None:
        source = db.get_assessment(conn, body.copy_from)
        if source is None or source["org_id"] != org["id"]:
            raise HTTPException(404, "assessment to copy not found")
    conn.commit()
    with conn:  # one transaction: the assessment and its copied answers, or nothing
        new_id = db.create_assessment(
            conn, org["id"], title, commit=False,
            odp=source["odp"] if source else None,
            partial_choices=source["partial_choices"] if source else None)
        if source:
            conn.execute(
                "INSERT INTO answers (assessment_id, objective_id, answer, note, justification, answered_at) "
                "SELECT ?, objective_id, answer, note, justification, answered_at FROM answers "
                "WHERE assessment_id = ?", (new_id, source["id"]))
    return _summary(conn, new_id)


@protected.patch("/api/assessments/{assessment_id}")
def patch_assessment(_w: Annotated[str, Writer], assessment: Assessment, body: AssessmentPatch, conn: Conn):
    sets, params = [], []
    if "title" in body.model_fields_set:
        if body.title is None or not body.title.strip():
            raise HTTPException(422, "title must not be blank")
        sets.append("title = ?")
        params.append(body.title.strip())
    if "completed_at" in body.model_fields_set:
        sets.append("completed_at = ?")
        params.append(_check_when(body.completed_at))
    if sets:
        with conn:
            conn.execute(f"UPDATE assessments SET {', '.join(sets)} WHERE id = ?",  # fixed column names
                         [*params, assessment["id"]])
    return _summary(conn, assessment["id"])


@protected.get("/api/assessments/{assessment_id}/overview")
def overview(assessment: Assessment, conn: Conn):
    st = State(conn, assessment)
    heatmap = []
    for fam in st.catalog.families():
        reqs = [r for r in st.catalog.requirements if r.family == fam.code]
        counts = {s: sum(1 for r in reqs if st.status[r.id] == s) for s in STATUSES}
        heatmap.append({"family": fam.code, "name": fam.name, **counts,
                        "points_lost": sum(st.lost.get(r.id, 0) for r in reqs)})
    return {
        "assessment": {"id": assessment["id"], "title": assessment["title"],
                       "started_at": assessment["started_at"],
                       "completed_at": assessment["completed_at"]},
        "score": asdict(st.result),
        "family_heatmap": heatmap,
        "top_gaps": [asdict(d) for d in top_gaps(st.result)],
        "provisional": st.result.provisional,
        "ssp_missing": st.result.ssp_missing,
        "conditional_eligible": st.result.conditional_eligible,
        "conflicts_count": len(_conflict_objectives(conn, assessment["id"])),
        "odp": assessment["odp"],
        "odp_descriptions": ODP_DESCRIPTIONS,
        "partial_choices": assessment["partial_choices"],
        "disclaimer": exports.DISCLAIMER,
    }


# -- requirements and answers -----------------------------------------------------------------

@protected.get("/api/assessments/{assessment_id}/requirements")
def list_requirements(
    assessment: Assessment, conn: Conn,
    family: Annotated[str | None, Query(max_length=8)] = None,
    status: Annotated[str | None, Query(max_length=16)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
):
    if family and family not in _family_codes():
        raise HTTPException(400, f"family must be one of {list(_family_codes())}")
    if status and status not in STATUSES:
        raise HTTPException(400, f"status must be one of {list(STATUSES)}")
    st = State(conn, assessment)
    needle = q.lower() if q else None  # matched literally, in memory: no SQL involved
    poam_reqs = {i["req_id"] for i in db.list_poam_items(conn, assessment["id"])}
    out = []
    for r in st.catalog.requirements:
        if family and r.family != family:
            continue
        if status and st.status[r.id] != status:
            continue
        if needle and needle not in r.id.lower() and needle not in r.text.lower():
            continue
        answered = sum(1 for o in r.objectives if st.answers.get(o.id))
        out.append({"id": r.id, "family": r.family, "family_name": r.family_name,
                    "basic": r.basic, "text": r.text, "weight": r.weight,
                    "status": st.status[r.id], "points_lost": st.lost.get(r.id, 0),
                    "objectives": len(r.objectives), "answered": answered,
                    "has_poam": r.id in poam_reqs})
    return {"total": len(out), "items": out}


@protected.get("/api/assessments/{assessment_id}/requirements/{req_id}")
def get_requirement(assessment: Assessment, req: Req, conn: Conn):
    st = State(conn, assessment)
    objectives = [{"id": o.id, "text": o.text, **db.objective_view(conn, assessment["id"], o.id)}
                  for o in req.objectives]
    item = next((i for i in db.list_poam_items(conn, assessment["id"]) if i["req_id"] == req.id), None)
    return {
        "requirement": {"id": req.id, "family": req.family, "family_name": req.family_name,
                        "basic": req.basic, "text": req.text, "discussion": req.discussion,
                        "weight": req.weight, "partial": req.partial,
                        "poam_allowed": req.poam_allowed, "footnotes": req.footnotes},
        "status": st.status[req.id],
        "points_lost": st.lost.get(req.id, 0),
        "partial_choice": assessment["partial_choices"].get(req.id),
        "poam_eligible": req.id in st.result.poam_eligible_ids,
        "objectives": objectives,
        "poam": item,
    }


class AnswerBody(BaseModel):
    answer: Literal["met", "not_met", "na", "unanswered"]
    note: str = Field(default="", max_length=5000)
    justification: str = Field(default="", max_length=5000)


@protected.put("/api/assessments/{assessment_id}/objectives/{obj_id}")
def put_objective(_w: Annotated[str, Writer], assessment: Assessment, obj_id: str,
                  body: AnswerBody, conn: Conn):
    req = _objective_index().get(obj_id)
    if req is None:
        raise HTTPException(404, "objective not found")
    if body.answer == "na" and not body.justification.strip():
        raise HTTPException(422, "Not applicable needs a justification")
    try:
        db.set_answer(conn, assessment["id"], obj_id, body.answer, body.note, body.justification)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    st = State(conn, assessment)
    return {"objective": {"id": obj_id, **db.objective_view(conn, assessment["id"], obj_id)},
            "requirement_status": st.status[req.id], "score": st.result.score,
            "provisional": st.result.provisional}


class PartialBody(BaseModel):
    choice: str | None = Field(default=None, max_length=64)


@protected.put("/api/assessments/{assessment_id}/partial/{req_id}")
def put_partial(_w: Annotated[str, Writer], assessment: Assessment, req: Req,
                body: PartialBody, conn: Conn):
    try:
        db.set_partial_choice(conn, assessment["id"], req.id, body.choice)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    result = db.current_score(conn, assessment["id"])
    return {"req_id": req.id, "choice": body.choice, "score": result.score,
            "poam_eligible_ids": result.poam_eligible_ids}


def _validate_odp(raw: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(raw) - set(DEFAULT_ODP))
    if unknown:
        raise HTTPException(422, f"unknown parameter(s): {', '.join(unknown)}")
    for name, value in raw.items():
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value <= 0):
            raise HTTPException(422, f"{name} must be a positive number")
    return raw


@protected.put("/api/assessments/{assessment_id}/odp")
def put_odp(_w: Annotated[str, Writer], assessment: Assessment,
            body: Annotated[dict[str, Any], Body()], conn: Conn):
    odp = _validate_odp(body)
    try:
        db.set_odp(conn, assessment["id"], {**assessment["odp"], **odp})
        reevaluated = db.reevaluate_evidence(conn, assessment["id"])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"odp": db.get_assessment(conn, assessment["id"])["odp"], "reevaluated": reevaluated}


# -- evidence ---------------------------------------------------------------------------------

def _findings_for(conn: sqlite3.Connection, evidence_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT objective_id, result, check_id, detail, rule_id, expected, observed_json, partial_hint "
        "FROM findings WHERE evidence_id = ? ORDER BY objective_id, check_id, rule_id",
        (evidence_id,)).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        item["observed"] = json.loads(item.pop("observed_json"))
        out.append(item)
    return out


@protected.get("/api/assessments/{assessment_id}/evidence")
def list_evidence(assessment: Assessment, conn: Conn):
    items = db.list_evidence(conn, assessment["id"])
    for item in items:
        counts = dict(conn.execute(
            "SELECT result, COUNT(*) FROM findings WHERE evidence_id = ? GROUP BY result",
            (item["id"],)).fetchall())
        item["findings"] = {k: counts.get(k, 0) for k in ("met", "not_met", "not_assessed")}
    return items


@protected.post("/api/assessments/{assessment_id}/evidence")
def upload_evidence(_w: Annotated[str, Writer], assessment: Assessment, conn: Conn,
                    file: Annotated[UploadFile, File(description="Collector output (.json)")]):
    limit = config.max_upload_bytes()
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"File too large (max {limit // (1024 * 1024)} MB)")
    try:
        text = decode_json_upload(data, EVIDENCE_MAX_LINE_CHARS)
    except UploadError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    try:
        parsed = json.loads(text)
    except (ValueError, RecursionError):
        raise HTTPException(400, "File is not valid JSON") from None
    try:
        evidence_id = db.add_evidence(conn, assessment["id"], parsed)
    except ValueError as exc:  # unknown collector/version or malformed envelope
        raise HTTPException(400, str(exc)) from None
    row = conn.execute("SELECT id, collector, collected_at, host, uploaded_at FROM evidence WHERE id = ?",
                       (evidence_id,)).fetchone()
    return {**dict(row), "assessment_id": assessment["id"],
            "findings": _findings_for(conn, evidence_id)}


# -- POA&M ------------------------------------------------------------------------------------

class Milestone(BaseModel):
    description: str = Field(max_length=1000)
    due: str | None = Field(default=None, max_length=10)
    done: bool = False


def _check_due(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise HTTPException(422, "due_date must be YYYY-MM-DD") from None


class PoamCreate(BaseModel):
    req_id: str = Field(max_length=16)
    weakness: str = Field(min_length=1, max_length=5000)
    remediation: str = Field(default="", max_length=5000)
    owner: str = Field(default="", max_length=255)
    milestones: list[Milestone] = Field(default_factory=list, max_length=50)
    due_date: str | None = Field(default=None, max_length=10)
    status: Literal["open", "in_progress", "closed"] = "open"


class PoamPatch(BaseModel):
    weakness: str | None = Field(default=None, min_length=1, max_length=5000)
    remediation: str | None = Field(default=None, max_length=5000)
    owner: str | None = Field(default=None, max_length=255)
    milestones: list[Milestone] | None = Field(default=None, max_length=50)
    due_date: str | None = Field(default=None, max_length=10)
    status: Literal["open", "in_progress", "closed"] | None = None


@protected.get("/api/assessments/{assessment_id}/poam")
def get_poam(assessment: Assessment, conn: Conn):
    st = State(conn, assessment)
    items = db.list_poam_items(conn, assessment["id"])
    drafts = poam.generate_poam(st.catalog, st.result, items, assessment["partial_choices"],
                                assessment["completed_at"] or assessment["started_at"])
    return {"items": items, "drafts": [asdict(d) for d in drafts],
            "eligible_ids": st.result.poam_eligible_ids}


@protected.post("/api/assessments/{assessment_id}/poam", status_code=201)
def create_poam_item(_w: Annotated[str, Writer], assessment: Assessment, body: PoamCreate, conn: Conn):
    req = _req_index().get(body.req_id)
    if req is None:
        raise HTTPException(404, "requirement not found")
    st = State(conn, assessment)
    if req.id not in st.result.poam_eligible_ids:
        if st.status[req.id] in ("met", "na"):
            reason = f"{req.id} is not a gap in this assessment, so it needs no POA&M item."
        else:
            reason = poam.ineligible_reason(st.catalog, req.id, assessment["partial_choices"].get(req.id))
        raise HTTPException(422, reason)
    if any(i["req_id"] == req.id for i in db.list_poam_items(conn, assessment["id"])):
        raise HTTPException(409, f"{req.id} already has a POA&M item")
    due = _check_due(body.due_date) or poam.default_due_date(
        assessment["completed_at"] or assessment["started_at"])
    item_id = db.add_poam_item(
        conn, assessment["id"], req.id, body.weakness, body.remediation, body.owner,
        [m.model_dump() for m in body.milestones], due, body.status)
    return db.get_poam_item(conn, assessment["id"], item_id)


@protected.patch("/api/assessments/{assessment_id}/poam/{item_id}")
def patch_poam_item(_w: Annotated[str, Writer], assessment: Assessment, item_id: str,
                    body: PoamPatch, conn: Conn):
    iid = _int_id(item_id, "POA&M item")
    if db.get_poam_item(conn, assessment["id"], iid) is None:
        raise HTTPException(404, "POA&M item not found")
    changes: dict[str, Any] = {}
    for key in body.model_fields_set:
        value = getattr(body, key)
        if value is None:
            if key != "due_date":
                raise HTTPException(422, f"{key} cannot be null")
        elif key == "milestones":
            value = [m.model_dump() for m in value]
        elif key == "due_date":
            value = _check_due(value)
        changes[key] = value
    db.update_poam_item(conn, assessment["id"], iid, changes)
    return db.get_poam_item(conn, assessment["id"], iid)


# -- exports ----------------------------------------------------------------------------------

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "org"


def _download(content: bytes | str, media_type: str, ext: str, conn: sqlite3.Connection,
              assessment: dict, name: str) -> Response:
    org = db.get_organization(conn) or {"name": ""}
    filename = f"{_slug(org['name'])}-{name}-{assessment['id']}.{ext}"
    body = content.encode("utf-8") if isinstance(content, str) else content
    return Response(body, media_type=media_type, headers={
        "Content-Disposition": f'attachment; filename="{filename}"'})


@protected.get("/api/assessments/{assessment_id}/exports/ssp.docx")
def export_ssp(assessment: Assessment, conn: Conn):
    return _download(exports.ssp_docx(conn, assessment["id"]), DOCX, "docx", conn, assessment, "ssp")


@protected.get("/api/assessments/{assessment_id}/exports/poam.docx")
def export_poam_docx(assessment: Assessment, conn: Conn):
    return _download(exports.poam_docx(conn, assessment["id"]), DOCX, "docx", conn, assessment, "poam")


@protected.get("/api/assessments/{assessment_id}/exports/poam.csv")
def export_poam_csv(assessment: Assessment, conn: Conn):
    return _download(exports.poam_csv(conn, assessment["id"]), "text/csv; charset=utf-8", "csv",
                     conn, assessment, "poam")


@protected.get("/api/assessments/{assessment_id}/exports/sprs.md")
def export_sprs(assessment: Assessment, conn: Conn):
    text = exports.sprs_markdown(exports.sprs_summary(conn, assessment["id"]))
    return _download(text, "text/markdown; charset=utf-8", "md", conn, assessment, "sprs")


# -- history ----------------------------------------------------------------------------------

def _status_map(conn: sqlite3.Connection, a: dict) -> dict[str, str]:
    answers = db.get_answers(conn, a["id"])
    return {r.id: requirement_status(r, answers) for r in load_catalog().requirements}


def _diff(before: dict[str, str], after: dict[str, str]) -> dict[str, list[str]]:
    gap = ("not_met", "not_assessed")
    out: dict[str, list[str]] = {"became_met": [], "regressed": [], "became_na": [], "no_longer_na": []}
    for req_id, now in after.items():
        was = before.get(req_id, "not_assessed")
        if now == "na" and was != "na":
            out["became_na"].append(req_id)
        elif was == "na" and now != "na":
            out["no_longer_na"].append(req_id)
        elif now == "met" and was in gap:
            out["became_met"].append(req_id)
        elif was == "met" and now in gap:
            out["regressed"].append(req_id)
    return out


@protected.get("/api/history")
def history(conn: Conn):
    items = sorted(_org_assessments(conn),
                   key=lambda a: ((a["completed_at"] or a["started_at"]), a["id"]))
    assessments, changes, previous = [], [], None
    for a in items:
        result = db.current_score(conn, a["id"])
        assessments.append({"id": a["id"], "title": a["title"],
                            "date": (a["completed_at"] or a["started_at"])[:10],
                            "score": result.score, "provisional": result.provisional})
        statuses = _status_map(conn, a)
        if previous is not None:
            changes.append({"from_id": previous[0]["id"], "to_id": a["id"],
                            **_diff(previous[1], statuses)})
        previous = (a, statuses)
    return {"assessments": assessments, "changes": changes}


# Registered last so every @protected route above is included.
app.include_router(protected)
