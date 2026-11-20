from __future__ import annotations

import csv
import io
import itertools
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import os

from dotenv import load_dotenv

load_dotenv(os.environ.get("COWRITE_ENV_FILE") or Path(__file__).resolve().parent.parent / ".env")

from fastapi import Depends, FastAPI, HTTPException, Request, Response  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from . import auth, db, llm  # noqa: E402
from .importer import RecordError, build_content, iter_records  # noqa: E402
from .tasks import STUDY_CONDITIONS, STUDY_TASKS, TASKS  # noqa: E402

app = FastAPI(title="CoWrite revision review")
db.init()

EVENT_TYPES = {
    "session_start", "writing_start", "next_task", "view", "pin", "unpin", "confirm", "correct_start", "correct_submit",
    "correct_redo", "correct_fail", "undo", "session_end",
}
# Written by the server only: draft_submit, enhance_done, enhance_fail.


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def load_session(conn, session_id: str) -> dict:
    s = db.row_to_dict(conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone())
    if s is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return s


def insert_event(conn, session: dict, type_: str, actor: str, *, client_ts=None, edit_id=None, payload=None) -> None:
    conn.execute(
        "INSERT INTO events (session_id, client_ts, server_ts, type, edit_id, payload, stage, actor)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (session["id"], client_ts, now(), type_, edit_id, db.dumps(payload) if payload is not None else None,
         session["stage"], actor),
    )


def word_count(text: str) -> int:
    return len(text.split())


def sequence_info(conn, s: dict) -> dict | None:
    """Position in the participant's task order. The next task's link is only handed out once this
    session has reached review, so a participant can't skip ahead."""
    if not s.get("group_id"):
        return None
    rows = conn.execute("SELECT id, seq, participant_token FROM sessions WHERE group_id = ? ORDER BY seq",
                        (s["group_id"],)).fetchall()
    nxt = next((r for r in rows if r["seq"] > s["seq"]), None)
    return {
        "index": s["seq"],
        "total": len(rows),
        "next": {"id": nxt["id"], "token": nxt["participant_token"]} if nxt and s["stage"] == "review" else None,
    }


def participant_view(conn, s: dict, role: str) -> dict:
    """What the participant page receives. Judge results and raw model output stay server-side."""
    view: dict[str, Any] = {
        "id": s["id"],
        "participantId": s["participant_id"],
        "stage": s["stage"],
        "task": TASKS.get(s["task_id"] or ""),
        "role": role,
        "sequence": sequence_info(conn, s),
    }
    if s["stage"] != "review":
        view["draft"] = s["draft"]
        return view
    edits = {eid: {k: v for k, v in e.items() if k != "judge"} for eid, e in s["edits"].items()}
    if s.get("condition") == "noReasons":
        # Withheld here, not just hidden in the UI, so the explanations never reach the browser.
        edits = {eid: {**e, "explanation": None} for eid, e in edits.items()}
    decisions = {
        r["edit_id"]: {"editId": r["edit_id"], "type": r["type"], "modality": r["modality"], "text": r["text"], "ts": r["ts"]}
        for r in conn.execute("SELECT * FROM decisions WHERE session_id = ?", (s["id"],))
    }
    view.update(original=s["original"], revised=s["revised"], segments=s["segments"], edits=edits, decisions=decisions)
    return view


# ---------- Auth ----------

class LoginBody(BaseModel):
    password: str


@app.post("/api/auth/login")
def login(body: LoginBody, response: Response):
    if not auth.check_password(body.password):
        raise HTTPException(status_code=401, detail="Wrong password.")
    response.set_cookie(auth.COOKIE, auth.admin_cookie_value(), httponly=True, samesite="lax", max_age=auth.TTL_SECONDS)
    return {"role": "admin"}


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(auth.COOKIE)
    return {"role": None}


@app.get("/api/auth/me")
def me(request: Request):
    return {"role": "admin" if auth.is_admin(request) else None}


# ---------- Participant session ----------

@app.get("/api/sessions/{session_id}")
def get_session(session_id: str, request: Request, t: str | None = None):
    with db.connect() as conn:
        s = load_session(conn, session_id)
        role = auth.session_role(request, s, t)
        return participant_view(conn, s, role)


class DraftIn(BaseModel):
    text: str = Field(max_length=20000)


@app.put("/api/sessions/{session_id}/draft")
def save_draft(session_id: str, body: DraftIn, request: Request, t: str | None = None):
    with db.connect() as conn:
        s = load_session(conn, session_id)
        auth.session_role(request, s, t)
        if s["stage"] != "writing":
            raise HTTPException(status_code=409, detail="The draft can no longer be changed.")
        conn.execute("UPDATE sessions SET draft = ? WHERE id = ?", (body.text, session_id))
        return {"ok": True}


@app.post("/api/sessions/{session_id}/enhance")
def enhance(session_id: str, body: DraftIn, request: Request, t: str | None = None):
    with db.connect() as conn:
        s = load_session(conn, session_id)
        role = auth.session_role(request, s, t)
        if s["stage"] == "review":
            return participant_view(conn, s, role)
        if s["stage"] != "writing":
            raise HTTPException(status_code=409, detail="The AI is already revising this draft.")
        task = TASKS.get(s["task_id"] or "")
        draft = llm.normalize(body.text)
        if task is None or not draft:
            raise HTTPException(status_code=400, detail="Write your draft first.")
        if word_count(draft) < task.get("minWords", 0):
            raise HTTPException(status_code=400, detail=f"Write at least {task['minWords']} words first.")
        conn.execute("UPDATE sessions SET draft = ?, stage = 'enhancing' WHERE id = ?", (draft, session_id))
        s["stage"] = "writing"
        insert_event(conn, s, "draft_submit", role, payload={"words": word_count(draft), "chars": len(draft)})

    # The model call happens outside the DB transaction.
    try:
        content = llm.enhance(task, draft)
    except Exception as e:  # noqa: BLE001 - any failure returns the participant to writing
        with db.connect() as conn:
            s = load_session(conn, session_id)
            conn.execute("UPDATE sessions SET stage = 'writing' WHERE id = ?", (session_id,))
            s["stage"] = "writing"
            insert_event(conn, s, "enhance_fail", role, payload={"error": str(e)[:500]})
        detail = str(e) if isinstance(e, llm.LLMError) else "AI revision failed."
        raise HTTPException(status_code=502, detail=detail)

    with db.connect() as conn:
        conn.execute(
            "UPDATE sessions SET stage = 'review', original = ?, revised = ?, segments = ?, edits = ?, meta = ?, enhanced_at = ?"
            " WHERE id = ?",
            (content["original"], content["revised"], db.dumps(content["segments"]), db.dumps(content["edits"]),
             db.dumps(content["meta"]), now(), session_id),
        )
        s = load_session(conn, session_id)
        kinds = [e["kind"] for e in s["edits"].values()]
        insert_event(conn, s, "enhance_done", role, payload={
            "edits": len(kinds), "grammar": kinds.count("grammar"), "content": kinds.count("content"),
            "latencySeconds": content["meta"]["latencySeconds"],
        })
        return participant_view(conn, s, role)


class EventIn(BaseModel):
    ts: str
    type: str
    editId: str | None = None
    payload: dict[str, Any] | None = None


class EventBatch(BaseModel):
    events: list[EventIn] = Field(max_length=1000)


@app.post("/api/sessions/{session_id}/events")
def post_events(session_id: str, batch: EventBatch, request: Request, t: str | None = None):
    with db.connect() as conn:
        s = load_session(conn, session_id)
        role = auth.session_role(request, s, t)
        stored = 0
        for ev in batch.events:
            if ev.type not in EVENT_TYPES:
                continue
            insert_event(conn, s, ev.type, role, client_ts=ev.ts, edit_id=ev.editId, payload=ev.payload)
            stored += 1
        return {"stored": stored}


class DecisionIn(BaseModel):
    editId: str
    type: Literal["confirmed", "corrected"]
    modality: Literal["voice", "text"] | None = None
    text: str | None = None
    ts: str


def review_session(conn, session_id: str, request: Request, t: str | None) -> dict:
    s = load_session(conn, session_id)
    auth.session_role(request, s, t)
    if s["stage"] != "review":
        raise HTTPException(status_code=409, detail="This session is not in review yet.")
    return s


@app.post("/api/sessions/{session_id}/decisions")
def post_decision(session_id: str, d: DecisionIn, request: Request, t: str | None = None):
    with db.connect() as conn:
        s = review_session(conn, session_id, request, t)
        edit = s["edits"].get(d.editId)
        if edit is None or edit["kind"] == "grammar":
            raise HTTPException(status_code=400, detail="Unknown edit.")
        if d.type == "corrected" and not (d.text or "").strip():
            raise HTTPException(status_code=400, detail="A correction needs text.")
        conn.execute(
            "INSERT OR REPLACE INTO decisions (session_id, edit_id, type, modality, text, audio_ref, ts) VALUES (?, ?, ?, ?, ?, NULL, ?)",
            (session_id, d.editId, d.type, d.modality, (d.text or "").strip() or None, d.ts),
        )
        return {"ok": True}


@app.delete("/api/sessions/{session_id}/decisions/{edit_id}")
def delete_decision(session_id: str, edit_id: str, request: Request, t: str | None = None):
    with db.connect() as conn:
        review_session(conn, session_id, request, t)
        conn.execute("DELETE FROM decisions WHERE session_id = ? AND edit_id = ?", (session_id, edit_id))
        return {"ok": True}


# ---------- Demo ----------

def demo_enabled() -> bool:
    return os.environ.get("COWRITE_DEMO", "").strip().lower() in ("1", "true", "yes")


@app.post("/api/demo")
def start_demo():
    """Creates a fresh writing session without login. Off unless COWRITE_DEMO=1."""
    if not demo_enabled():
        raise HTTPException(status_code=404, detail="Demo mode is off (set COWRITE_DEMO=1 in backend/.env).")
    with db.connect() as conn:
        s = insert_task_sequence(conn, f"demo-{secrets.token_hex(2)}")[0]
        return {"id": s["id"], "token": s["participant_token"]}


# ---------- Admin ----------

def session_summary(conn, s: dict) -> dict:
    counts = conn.execute(
        "SELECT (SELECT COUNT(*) FROM decisions WHERE session_id = :id) AS decisions,"
        " (SELECT COUNT(*) FROM events WHERE session_id = :id) AS events", {"id": s["id"]}
    ).fetchone()
    edits = (s["edits"] or {}).values()
    return {
        "id": s["id"],
        "participantId": s["participant_id"],
        "taskId": s["task_id"],
        "source": s["source"],
        "stage": s["stage"],
        "sourceId": s["source_id"],
        "draftWords": word_count(s["draft"] or s["original"] or ""),
        "editCount": sum(1 for e in edits if e["kind"] != "grammar"),
        "grammarCount": sum(1 for e in edits if e["kind"] == "grammar"),
        "decisionCount": counts["decisions"],
        "eventCount": counts["events"],
        "warnings": s["warnings"],
        "token": s["participant_token"],
        "createdAt": s["created_at"],
        "groupId": s.get("group_id"),
        "seq": s.get("seq"),
        "condition": s.get("condition"),
    }


def insert_session(conn, **fields) -> dict:
    s = {
        "id": secrets.token_hex(4), "task_id": None, "draft": "", "original": None, "revised": None,
        "segments": None, "edits": None, "meta": {}, "source_id": None, "warnings": [],
        "participant_token": auth.new_participant_token(), "created_at": now(), "enhanced_at": None,
        "group_id": None, "seq": None, "condition": None, **fields,
    }
    cols = list(s)
    conn.execute(
        f"INSERT INTO sessions ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
        [db.dumps(s[c]) if c in db.JSON_COLUMNS and s[c] is not None else s[c] for c in cols],
    )
    return s


@app.get("/api/admin/sessions", dependencies=[Depends(auth.require_admin)])
def list_sessions():
    with db.connect() as conn:
        rows = [db.row_to_dict(r) for r in conn.execute("SELECT * FROM sessions ORDER BY created_at DESC, group_id, seq, id")]
        return {
            "sessions": [session_summary(conn, s) for s in rows],
            "tasks": {k: v["title"] for k, v in TASKS.items()},
            "studyTasks": STUDY_TASKS,
            "studyConditions": STUDY_CONDITIONS,
            "aiConfigured": bool(llm.configured_providers()),
            "aiModel": " → ".join(f"{p['name']}:{p['model']}" for p in llm.configured_providers()),
        }


Assignment = tuple[tuple[str, str], ...]  # ((task_id, condition), ...) in the order they are written


def pick_assignment(conn) -> Assignment:
    """Task order and which task gets which explanation condition, randomized and counterbalanced.

    The candidates are every task order crossed with every condition order (2 x 2 = 4 for two tasks).
    Each participant gets a random choice among the candidates used least so far, so every block of
    four participants covers all four once: each task comes first and gets explanations equally often.
    """
    candidates = [tuple(zip(tasks, conds)) for tasks in itertools.permutations(STUDY_TASKS)
                  for conds in itertools.permutations(STUDY_CONDITIONS)]
    groups: dict[str, list[tuple[str, str]]] = {}
    for r in conn.execute("SELECT group_id, task_id, condition FROM sessions WHERE group_id IS NOT NULL ORDER BY group_id, seq"):
        groups.setdefault(r["group_id"], []).append((r["task_id"], r["condition"]))
    used = {c: 0 for c in candidates}
    for rows in groups.values():
        if tuple(rows) in used:
            used[tuple(rows)] += 1
    fewest = min(used.values())
    return secrets.choice([c for c in candidates if used[c] == fewest])


def insert_task_sequence(conn, participant_id: str) -> list[dict]:
    """One writing session per study task, linked by group_id, with a counterbalanced random assignment."""
    group = secrets.token_hex(4)
    return [
        insert_session(conn, participant_id=participant_id, task_id=task_id, source="task", stage="writing",
                       group_id=group, seq=n, condition=condition)
        for n, (task_id, condition) in enumerate(pick_assignment(conn), start=1)
    ]


class CreateBody(BaseModel):
    participantIds: list[str] = Field(min_length=1, max_length=500)
    # None: every study task in a random order (the study setup). A task id: that task alone (for piloting).
    taskId: str | None = None
    # Only with taskId: the explanation condition for that single session (default: explanations shown).
    condition: str | None = None


@app.post("/api/admin/sessions", dependencies=[Depends(auth.require_admin)])
def create_sessions(body: CreateBody):
    if body.taskId is not None and body.taskId not in TASKS:
        raise HTTPException(status_code=400, detail=f"Unknown task {body.taskId!r}.")
    if body.condition is not None and body.condition not in STUDY_CONDITIONS:
        raise HTTPException(status_code=400, detail=f"Unknown condition {body.condition!r}.")
    with db.connect() as conn:
        created = []
        for pid in body.participantIds:
            pid = pid.strip()
            if not pid:
                continue
            if body.taskId is None:
                created += [session_summary(conn, s) for s in insert_task_sequence(conn, pid)]
            else:
                s = insert_session(conn, participant_id=pid, task_id=body.taskId, source="task", stage="writing",
                                   condition=body.condition)
                created.append(session_summary(conn, s))
        return {"created": created}


class ImportBody(BaseModel):
    data: Any


def import_records(data: Any) -> dict:
    try:
        records = iter_records(data)
    except RecordError as e:
        raise HTTPException(status_code=400, detail=str(e))
    created, failed = [], []
    with db.connect() as conn:
        for index, (source_id, record) in enumerate(records):
            try:
                content, warnings = build_content(record)
            except RecordError as e:
                failed.append({"index": index, "sourceId": source_id, "error": str(e)})
                continue
            task_id = record.get("taskId") if record.get("taskId") in TASKS else None
            participant = str(record.get("participantId") or source_id or f"P-{secrets.token_hex(2)}")
            s = insert_session(
                conn, participant_id=participant, task_id=task_id, source="import", stage="review",
                draft=content["original"], **content, source_id=None if source_id is None else str(source_id),
                warnings=warnings, enhanced_at=now(),
            )
            created.append(session_summary(conn, s))
    return {"created": created, "failed": failed}


@app.post("/api/admin/import", dependencies=[Depends(auth.require_admin)])
def import_sessions(body: ImportBody):
    return import_records(body.data)


@app.post("/api/admin/sessions/{session_id}/reset", dependencies=[Depends(auth.require_admin)])
def reset_session(session_id: str):
    """Imported sessions: clear review data. Task sessions: back to an empty draft."""
    with db.connect() as conn:
        s = load_session(conn, session_id)
        conn.execute("DELETE FROM decisions WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM events WHERE session_id = ?", (session_id,))
        if s["source"] == "task":
            conn.execute(
                "UPDATE sessions SET stage = 'writing', draft = '', original = NULL, revised = NULL, segments = NULL,"
                " edits = NULL, meta = '{}', enhanced_at = NULL WHERE id = ?", (session_id,))
        return {"ok": True}


@app.post("/api/admin/sessions/{session_id}/link", dependencies=[Depends(auth.require_admin)])
def regenerate_link(session_id: str):
    with db.connect() as conn:
        load_session(conn, session_id)
        token = auth.new_participant_token()
        conn.execute("UPDATE sessions SET participant_token = ? WHERE id = ?", (token, session_id))
        return {"token": token}


@app.delete("/api/admin/sessions/{session_id}", dependencies=[Depends(auth.require_admin)])
def delete_session(session_id: str):
    with db.connect() as conn:
        load_session(conn, session_id)
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return {"ok": True}


CSV_COLUMNS = [
    "session_id", "participant_id", "group_id", "task_seq", "task_id", "condition", "stage", "actor", "event_seq", "client_ts", "server_ts",
    "type", "edit_id", "edit_kind", "edit_original", "edit_revised", "explanation", "explanation_mode",
    "modality", "text", "error", "payload",
]


def export_data(session_id: str | None) -> list[dict]:
    with db.connect() as conn:
        if session_id:
            sessions = [load_session(conn, session_id)]
        else:
            sessions = [db.row_to_dict(r) for r in conn.execute("SELECT * FROM sessions ORDER BY created_at, group_id, seq, id")]
        out = []
        for s in sessions:
            decisions = [dict(r) for r in conn.execute("SELECT * FROM decisions WHERE session_id = ? ORDER BY ts", (s["id"],))]
            events = [db.row_to_dict(r) for r in conn.execute("SELECT * FROM events WHERE session_id = ? ORDER BY id", (s["id"],))]
            s = {k: v for k, v in s.items() if k != "participant_token"}
            out.append({**s, "task": TASKS.get(s["task_id"] or ""), "decisions": decisions, "events": events})
        return out


@app.get("/api/admin/export", dependencies=[Depends(auth.require_admin)])
def export(format: Literal["json", "csv"] = "json", sessionId: str | None = None):
    data = export_data(sessionId)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    name = f"cowrite-{sessionId or 'all'}-{stamp}"
    if format == "json":
        body = json.dumps({"exportedAt": now(), "sessions": data}, ensure_ascii=False, indent=2)
        return Response(body, media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{name}.json"'})

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
    w.writeheader()
    for s in data:
        for ev in s["events"]:
            edit = (s["edits"] or {}).get(ev["edit_id"] or "", {})
            explanation = edit.get("explanation") or {}
            payload = ev["payload"] or {}
            w.writerow({
                "session_id": s["id"], "participant_id": s["participant_id"], "group_id": s.get("group_id"),
                "task_seq": s.get("seq"), "task_id": s["task_id"], "condition": s.get("condition"),
                "stage": ev["stage"], "actor": ev["actor"], "event_seq": ev["id"], "client_ts": ev["client_ts"],
                "server_ts": ev["server_ts"], "type": ev["type"], "edit_id": ev["edit_id"], "edit_kind": edit.get("kind"),
                "edit_original": edit.get("original"), "edit_revised": edit.get("revised"),
                "explanation": explanation.get("text"), "explanation_mode": explanation.get("mode"),
                "modality": payload.get("modality"), "text": payload.get("text"), "error": payload.get("error"),
                "payload": json.dumps(payload, ensure_ascii=False) if payload else "",
            })
    return Response("﻿" + buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})


# ---------- Built frontend (production) ----------

DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        return FileResponse(DIST / "index.html")
