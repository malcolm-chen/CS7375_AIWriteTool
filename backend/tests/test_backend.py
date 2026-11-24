import json
import os
import tempfile
from pathlib import Path

os.environ["COWRITE_DB"] = str(Path(tempfile.mkdtemp()) / "test.db")
os.environ["COWRITE_ADMIN_PASSWORD"] = "pw"
os.environ["COWRITE_ENV_FILE"] = os.devnull  # never load the real backend/.env in tests
os.environ["LLM_PROVIDERS"] = "kimi"
os.environ["KIMI_API_KEY"] = "test-key"

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import llm  # noqa: E402
from app.diffing import diff_spans, tokenize  # noqa: E402
from app.importer import build_content  # noqa: E402
from app.main import app  # noqa: E402
from app import db  # noqa: E402
from app.assignment import candidates  # noqa: E402
from app.tasks import STUDY_CONDITIONS, STUDY_TASKS, TASKS  # noqa: E402

SAMPLE = json.loads((Path(__file__).resolve().parents[2] / "sample_data" / "sample_revisions.json").read_text())

DRAFT = ("Dear Ms Reyes,\n\nI am writting to apply for the Junior Project Coordinator job. I think I might be a good fit "
         "because I helped organize events at my school club and I kept everyone updated. I have attached my resume. "
         "Can we meet sometime?\n\nBest,\nSam")
REVISED = ("Dear Ms. Reyes,\n\nI am writing to apply for the Junior Project Coordinator position. I am confident I would be "
           "a strong fit because I led event planning for my school club and kept a team of eight informed every week. "
           "I have attached my résumé. Could we schedule a brief interview at your convenience?\n\nBest,\nSam")
CHANGES = [
    {"original": "Ms", "revised": "Ms.", "type": "grammar", "explanation": "Added the period after the title."},
    {"original": "writting", "revised": "writing", "type": "grammar", "explanation": "Fixed spelling."},
    {"original": "job", "revised": "position", "type": "content", "explanation": "“Position” sounds more professional."},
    {"original": "I think I might be a good fit", "revised": "I am confident I would be a strong fit", "type": "content",
     "explanation": "You sound more confident this way."},
    {"original": "helped organize events at my school club and I kept everyone updated",
     "revised": "led event planning for my school club and kept a team of eight informed every week", "type": "content",
     "explanation": "Concrete details show your coordination skills."},
    # "resume" -> "résumé" deliberately not reported, to exercise the post-hoc explain call.
    {"original": "Can we meet sometime?", "revised": "Could we schedule a brief interview at your convenience?",
     "type": "content", "explanation": "A specific, polite request for an interview."},
]


class FakeKimi:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers=None, json=None, timeout=None):
        self.calls.append(json)
        body = self.responses.pop(0)
        content = body if isinstance(body, str) else __import__("json").dumps(body)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]},
                              request=httpx.Request("POST", url))


def fragments(original, revised):
    return [(original[s.o_start:s.o_end], revised[s.r_start:s.r_end]) for s in diff_spans(original, revised)]


def test_tokenize_mixed_language_roundtrip():
    text = "我们用GPT-4改写了it's draft，结果很好。"
    tokens = tokenize(text)
    assert "".join(tokens) == text
    assert "GPT-4" in tokens and "it's" in tokens and "我" in tokens and "，" in tokens


def test_diff_merges_across_one_word_but_not_punctuation():
    assert fragments("I might go to the park.", "I will attend the park.") == [("might go to", "will attend")]
    assert fragments("a big red dog", "a small red cat") == [("big red dog", "small red cat")]
    assert fragments("somewhat good, but bad", "good, and fine") == [("somewhat ", ""), ("but bad", "and fine")]


def test_import_aligns_given_edits():
    content, warnings = build_content(SAMPLE[0])
    assert warnings == []
    assert content["edits"]["e1"]["original"] == "might go to"
    assert content["edits"]["e1"]["kind"] == "content"


def test_enhance_maps_changes_and_explains_missing(monkeypatch):
    fake = FakeKimi([
        "```json\n" + json.dumps({"revised": REVISED, "changes": CHANGES}) + "\n```",
        {"changes": [{"id": "1", "type": "grammar", "explanation": "Added the accents used in “résumé”."}]},
    ])
    monkeypatch.setattr(llm.httpx, "post", fake)
    content = llm.enhance({"title": "t", "scenario": "s", "assignment": "a"}, DRAFT)
    edits = list(content["edits"].values())
    by_orig = {e["original"]: e for e in edits}
    assert by_orig[""]["kind"] == "grammar"  # "Ms" -> "Ms.": the diff sees only the inserted period
    assert by_orig["writting"]["kind"] == "grammar"
    assert by_orig["job"]["kind"] == "content"
    # Highlights stay at diff granularity; spans from one reported change share its explanation.
    assert "helped organize events at" in by_orig and "I kept everyone updated" in by_orig
    assert by_orig["helped organize events at"]["explanation"] == by_orig["I kept everyone updated"]["explanation"]
    assert by_orig["helped organize events at"]["changeIndex"] == by_orig["I kept everyone updated"]["changeIndex"]
    resume = next(e for e in edits if "resume" in e["original"])
    assert resume["explanation"]["mode"] == "post_hoc" and resume["kind"] == "grammar"
    assert len(fake.calls) == 2
    left = "".join(seg["text"] if seg["kind"] == "same" else content["edits"][seg["editId"]]["original"] for seg in content["segments"])
    right = "".join(seg["text"] if seg["kind"] == "same" else content["edits"][seg["editId"]]["revised"] for seg in content["segments"])
    assert left == DRAFT and right == REVISED


def test_enhance_retries_bad_json_then_fails(monkeypatch):
    monkeypatch.setattr(llm.httpx, "post", FakeKimi(["not json", "{\"nope\": 1}"]))
    with pytest.raises(llm.LLMError):
        llm.enhance({"title": "t", "scenario": "s", "assignment": "a"}, DRAFT)


def test_task_flow_and_permissions(monkeypatch):
    c = TestClient(app)
    assert c.get("/api/admin/sessions").status_code == 403
    assert c.post("/api/auth/login", json={"password": "pw"}).status_code == 200
    s = c.post("/api/admin/sessions", json={"participantIds": ["P01"]}).json()["created"][0]
    q = {"t": s["token"]}

    p = TestClient(app)
    assert p.get(f"/api/sessions/{s['id']}").status_code == 403
    view = p.get(f"/api/sessions/{s['id']}", params=q).json()
    assert view["stage"] == "writing" and view["task"]["id"] in TASKS and view["role"] == "participant"
    assert view["sequence"]["index"] == 1 and view["sequence"]["total"] == 2
    assert p.put(f"/api/sessions/{s['id']}/draft", params=q, json={"text": "Dear"}).status_code == 200
    assert p.post(f"/api/sessions/{s['id']}/enhance", params=q, json={"text": "too short"}).status_code == 400

    monkeypatch.setattr(llm.httpx, "post", FakeKimi(["garbage", "garbage"]))
    long_draft = DRAFT + " " + "More words here. " * 10
    assert p.post(f"/api/sessions/{s['id']}/enhance", params=q, json={"text": long_draft}).status_code == 502
    assert p.get(f"/api/sessions/{s['id']}", params=q).json()["stage"] == "writing"

    revised = REVISED + " " + "More words here. " * 10
    monkeypatch.setattr(llm.httpx, "post", FakeKimi([
        {"revised": revised.strip(), "changes": CHANGES},
        {"changes": [{"id": "1", "type": "content", "explanation": "x"}]},
    ]))
    view = p.post(f"/api/sessions/{s['id']}/enhance", params=q, json={"text": long_draft}).json()
    assert view["stage"] == "review" and "judge" not in json.dumps(view["edits"])
    grammar = next(e for e in view["edits"].values() if e["kind"] == "grammar")
    content = next(e for e in view["edits"].values() if e["kind"] == "content")
    assert p.post(f"/api/sessions/{s['id']}/decisions", params=q,
                  json={"editId": grammar["id"], "type": "confirmed", "ts": "x"}).status_code == 400
    assert p.post(f"/api/sessions/{s['id']}/decisions", params=q,
                  json={"editId": content["id"], "type": "confirmed", "ts": "x"}).status_code == 200
    assert p.put(f"/api/sessions/{s['id']}/draft", params=q, json={"text": "late"}).status_code == 409
    assert p.get("/api/admin/export", params=q).status_code == 403

    exported = c.get("/api/admin/export", params={"sessionId": s["id"]}).json()["sessions"][0]
    types = [e["type"] for e in exported["events"]]
    assert types == ["assigned", "draft_submit", "enhance_fail", "draft_submit", "enhance_done"]
    assert exported["meta"]["rawResponse"]
    assert "edit_kind" in c.get("/api/admin/export", params={"format": "csv"}).text.splitlines()[0]

    c.post(f"/api/admin/sessions/{s['id']}/reset")
    assert p.get(f"/api/sessions/{s['id']}", params=q).json() | {"draft": None} == p.get(
        f"/api/sessions/{s['id']}", params=q).json() | {"draft": None}
    assert p.get(f"/api/sessions/{s['id']}", params=q).json()["stage"] == "writing"


def test_import_creates_review_sessions():
    c = TestClient(app)
    c.post("/api/auth/login", json={"password": "pw"})
    created = c.post("/api/admin/import", json={"data": SAMPLE}).json()["created"]
    assert [x["stage"] for x in created] == ["review"] * 3


def test_falls_back_to_next_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDERS", "openai,kimi")
    monkeypatch.setenv("OPENAI_API_KEY", "o-key")
    calls = []

    def post(url, headers=None, json=None, timeout=None):
        calls.append(url)
        if "openai" in url:
            return httpx.Response(503, text="overloaded", request=httpx.Request("POST", url))
        content = __import__("json").dumps({"revised": REVISED, "changes": CHANGES[:5] + CHANGES[5:]})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]}, request=httpx.Request("POST", url))

    monkeypatch.setattr(llm.httpx, "post", post)
    content = llm.enhance({"title": "t", "scenario": "s", "assignment": "a"}, DRAFT)
    assert content["meta"]["rewriteModel"] == "kimi:kimi-k3"
    assert "HTTP 503" in content["meta"]["fallbackErrors"][0]
    assert sum("openai" in u for u in calls) == 2  # retried once before falling back


def test_demo_and_link_role(monkeypatch):
    c = TestClient(app)
    monkeypatch.delenv("COWRITE_DEMO", raising=False)
    assert c.post("/api/demo").status_code == 404
    monkeypatch.setenv("COWRITE_DEMO", "1")
    d = c.post("/api/demo").json()
    assert c.get(f"/api/sessions/{d['id']}", params={"t": d["token"]}).json()["stage"] == "writing"
    # A logged-in admin opening a participant link sees the participant view.
    c.post("/api/auth/login", json={"password": "pw"})
    assert c.get(f"/api/sessions/{d['id']}", params={"t": d["token"]}).json()["role"] == "participant"
    assert c.get(f"/api/sessions/{d['id']}").json()["role"] == "admin"


def fresh_db():
    with db.connect() as conn:
        conn.execute("DELETE FROM sessions")


def admin_client():
    c = TestClient(app)
    c.post("/api/auth/login", json={"password": "pw"})
    return c


def create_and_open(c, pids):
    """Creates participants and opens each one's task 1 link. Returns {participantId: [view of task 1, summary...]}."""
    created = c.post("/api/admin/sessions", json={"participantIds": pids}).json()["created"]
    for s in created:
        if s["seq"] == 1:
            TestClient(app).get(f"/api/sessions/{s['id']}", params={"t": s["token"]})
    return created


def assignments(c):
    """{groupId: ((taskId, condition), ...)} for assigned groups, from the admin listing."""
    groups = {}
    for s in c.get("/api/admin/sessions").json()["sessions"]:
        if s["groupId"] and s["taskId"]:
            groups.setdefault(s["groupId"], []).append((s["seq"], s["taskId"], s["condition"]))
    return {g: tuple((t, cond) for _, t, cond in sorted(rows)) for g, rows in groups.items()}


def test_sequence_is_assigned_on_first_open_and_linked(monkeypatch):
    fresh_db()
    c = admin_client()
    created = c.post("/api/admin/sessions", json={"participantIds": ["P01"]}).json()["created"]
    assert len(created) == 2 and all(s["taskId"] is None and s["condition"] is None for s in created)
    s1, s2 = sorted(created, key=lambda s: s["seq"])
    # The researcher opening the session doesn't assign it.
    assert c.get(f"/api/sessions/{s1['id']}").json()["task"] is None
    assert assignments(c) == {}

    p = TestClient(app)
    view = p.get(f"/api/sessions/{s1['id']}", params={"t": s1["token"]}).json()
    assert view["task"]["id"] in TASKS and view["sequence"] == {"index": 1, "total": 2, "next": None}
    (a,) = assignments(c).values()
    assert sorted(t for t, _ in a) == sorted(STUDY_TASKS) and sorted(cond for _, cond in a) == sorted(STUDY_CONDITIONS)
    # Opening again doesn't reassign.
    p.get(f"/api/sessions/{s1['id']}", params={"t": s1["token"]})
    assert list(assignments(c).values()) == [a]
    events = c.get("/api/admin/export", params={"sessionId": s1["id"]}).json()["sessions"][0]["events"]
    assert [e["type"] for e in events] == ["assigned"]
    assert events[0]["payload"] == {"tasks": [t for t, _ in a], "conditions": [cond for _, cond in a]}

    long_draft = DRAFT + " " + "More words here. " * 10
    revised = REVISED + " " + "More words here. " * 10
    monkeypatch.setattr(llm.httpx, "post", FakeKimi([
        {"revised": revised.strip(), "changes": CHANGES},
        {"changes": [{"id": "1", "type": "content", "explanation": "x"}]},
    ]))
    view = p.post(f"/api/sessions/{s1['id']}/enhance", params={"t": s1["token"]}, json={"text": long_draft}).json()
    assert view["sequence"]["next"] == {"id": s2["id"], "token": s2["token"]}
    last = p.get(f"/api/sessions/{s2['id']}", params={"t": s2["token"]}).json()
    assert last["task"]["id"] == a[1][0] and last["sequence"]["index"] == 2 and last["sequence"]["next"] is None

    assert p.post(f"/api/sessions/{s1['id']}/events", params={"t": s1["token"]},
                  json={"events": [{"ts": "x", "type": "paste", "payload": {"chars": 5}},
                                   {"ts": "x", "type": "next_task"}]}).json()["stored"] == 1  # paste is not stored
    header = c.get("/api/admin/export", params={"format": "csv"}).text.splitlines()[0]
    assert "group_id" in header and "task_seq" in header and "condition" in header


def test_assignments_are_balanced_and_unopened_links_take_no_slot():
    fresh_db()
    c = admin_client()
    c.post("/api/admin/sessions", json={"participantIds": ["U1", "U2", "U3"]})  # never opened
    create_and_open(c, [f"S{n}" for n in range(8)])
    got = list(assignments(c).values())
    assert len(got) == 8 and all(got.count(x) == 2 for x in candidates())  # every block of 4 covers all 4
    balance = c.get("/api/admin/sessions").json()["balance"]
    assert balance["unopened"] == 3
    assert [cell["in_progress"] for cell in balance["cells"]] == [2, 2, 2, 2]
    # Each scenario is written with and without explanations equally often.
    assert {(x["taskId"], x["condition"]): x["in_progress"] for x in balance["byTaskCondition"]} == {
        (t, cond): 4 for t in STUDY_TASKS for cond in STUDY_CONDITIONS}


def test_balance_ignores_abandoned_and_demo_participants(monkeypatch):
    fresh_db()
    c = admin_client()
    create_and_open(c, ["A", "B", "C", "D"])
    by_group = assignments(c)
    assert sorted(by_group.values()) == sorted(candidates())
    gx, gy = list(by_group)[:2]
    old = "2000-01-01T00:00:00.000+00:00"
    with db.connect() as conn:
        # X started long ago and never finished: abandoned, its slot opens up again.
        conn.execute("UPDATE sessions SET assigned_at = ? WHERE group_id = ?", (old, gx))
        # Y also started long ago but finished (every task in review, nothing left to decide): still counts.
        conn.execute("UPDATE sessions SET assigned_at = ?, stage = 'review', edits = '{}' WHERE group_id = ?", (old, gy))
    balance = c.get("/api/admin/sessions").json()["balance"]
    assert balance["groups"][gx] == "abandoned" and balance["groups"][gy] == "completed"

    monkeypatch.setenv("COWRITE_DEMO", "1")
    for _ in range(3):
        c.post("/api/demo")  # demos are assigned at once but never count
    assert c.get("/api/admin/sessions").json()["balance"]["cells"] == balance["cells"]

    create_and_open(c, ["E"])
    e_group = next(s["groupId"] for s in c.get("/api/admin/sessions").json()["sessions"] if s["participantId"] == "E")
    assert assignments(c)[e_group] == by_group[gx]  # the only least-used slot is the abandoned one


def test_concurrent_first_opens_stay_balanced():
    from concurrent.futures import ThreadPoolExecutor

    fresh_db()
    c = admin_client()
    created = [s for s in c.post("/api/admin/sessions", json={"participantIds": [f"T{n}" for n in range(8)]}).json()["created"]
               if s["seq"] == 1]
    with ThreadPoolExecutor(8) as pool:
        codes = list(pool.map(lambda s: TestClient(app).get(f"/api/sessions/{s['id']}", params={"t": s["token"]}).status_code, created))
    assert codes == [200] * 8
    got = list(assignments(c).values())
    assert all(got.count(x) == 2 for x in candidates())


def test_single_task_sessions_for_piloting():
    c = TestClient(app)
    c.post("/api/auth/login", json={"password": "pw"})
    created = c.post("/api/admin/sessions", json={"participantIds": ["pilot"], "taskId": "professor_apology"}).json()["created"]
    assert len(created) == 1 and created[0]["taskId"] == "professor_apology" and created[0]["groupId"] is None


def test_no_reasons_condition_withholds_explanations(monkeypatch):
    c = TestClient(app)
    c.post("/api/auth/login", json={"password": "pw"})
    long_draft = DRAFT + " " + "More words here. " * 10
    revised = (REVISED + " " + "More words here. " * 10).strip()
    views = {}
    for cond in ("reasons", "noReasons"):
        s = c.post("/api/admin/sessions", json={"participantIds": [f"pilot-{cond}"], "taskId": "professor_apology",
                                                "condition": cond}).json()["created"][0]
        assert s["condition"] == cond
        monkeypatch.setattr(llm.httpx, "post", FakeKimi([
            {"revised": revised, "changes": CHANGES},
            {"changes": [{"id": "1", "type": "content", "explanation": "x"}]},
        ]))
        p = TestClient(app)
        p.post(f"/api/sessions/{s['id']}/enhance", params={"t": s["token"]}, json={"text": long_draft})
        views[cond] = (s, p.get(f"/api/sessions/{s['id']}", params={"t": s["token"]}).json())
    assert all(e["explanation"] for e in views["reasons"][1]["edits"].values())
    hidden = views["noReasons"][1]
    assert all(e["explanation"] is None for e in hidden["edits"].values())
    assert "Position" not in json.dumps(hidden)  # no explanation text anywhere in the response
    # Explanations are still generated and exported for analysis.
    exported = c.get("/api/admin/export", params={"sessionId": views["noReasons"][0]["id"]}).json()["sessions"][0]
    assert exported["condition"] == "noReasons" and all(e["explanation"] for e in exported["edits"].values())
    assert c.post("/api/admin/sessions", json={"participantIds": ["x"], "taskId": "professor_apology",
                                               "condition": "bogus"}).status_code == 400


def test_review_fixes(monkeypatch):
    fresh_db()
    c = admin_client()
    # Full-sequence creation from the admin page sends no condition.
    created = c.post("/api/admin/sessions", json={"participantIds": ["R1", "R2"], "taskId": None}).json()["created"]
    r1 = sorted((s for s in created if s["participantId"] == "R1"), key=lambda s: s["seq"])
    r2 = sorted((s for s in created if s["participantId"] == "R2"), key=lambda s: s["seq"])

    # The next task's token goes to the participant only, never to an admin preview.
    p = TestClient(app)
    p.get(f"/api/sessions/{r1[0]['id']}", params={"t": r1[0]["token"]})
    with db.connect() as conn:
        conn.execute("UPDATE sessions SET stage = 'review', original = 'a', revised = 'a', segments = '[]', edits = '{}'"
                     " WHERE id = ?", (r1[0]["id"],))
    assert p.get(f"/api/sessions/{r1[0]['id']}", params={"t": r1[0]["token"]}).json()["sequence"]["next"]["id"] == r1[1]["id"]
    assert c.get(f"/api/sessions/{r1[0]['id']}").json()["sequence"]["next"] is None

    # Reset keeps the assignment record.
    c.post(f"/api/admin/sessions/{r1[0]['id']}/reset")
    events = c.get("/api/admin/export", params={"sessionId": r1[0]["id"]}).json()["sessions"][0]["events"]
    assert [e["type"] for e in events] == ["assigned"]

    # Deleting one task of a participant deletes all of their tasks.
    c.delete(f"/api/admin/sessions/{r2[1]['id']}")
    assert TestClient(app).get(f"/api/sessions/{r2[0]['id']}", params={"t": r2[0]["token"]}).status_code == 404

    # A group missing a task gets a clear error, not a crash, and isn't counted as an unopened link.
    created = c.post("/api/admin/sessions", json={"participantIds": ["R3"]}).json()["created"]
    with db.connect() as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (next(s["id"] for s in created if s["seq"] == 2),))
    s1 = next(s for s in created if s["seq"] == 1)
    assert TestClient(app).get(f"/api/sessions/{s1['id']}", params={"t": s1["token"]}).status_code == 409
    balance = c.get("/api/admin/sessions").json()["balance"]
    assert balance["groups"][s1["groupId"]] == "invalid" and balance["unopened"] == 0

    # Pilot sessions record their condition; a bad abandonment setting falls back to 24 h.
    pilot = c.post("/api/admin/sessions", json={"participantIds": ["X"], "taskId": "professor_apology"}).json()["created"][0]
    assert pilot["condition"] == "reasons"
    monkeypatch.setenv("COWRITE_ABANDON_HOURS", "abc")
    assert c.get("/api/admin/sessions").json()["balance"]["abandonHours"] == 24


def test_no_reasons_hides_change_index(monkeypatch):
    fresh_db()
    c = admin_client()
    s = c.post("/api/admin/sessions", json={"participantIds": ["N"], "taskId": "professor_apology",
                                            "condition": "noReasons"}).json()["created"][0]
    monkeypatch.setattr(llm.httpx, "post", FakeKimi([
        {"revised": (REVISED + " " + "More words here. " * 10).strip(), "changes": CHANGES},
        {"changes": [{"id": "1", "type": "content", "explanation": "x"}]},
    ]))
    view = TestClient(app).post(f"/api/sessions/{s['id']}/enhance", params={"t": s["token"]},
                                json={"text": DRAFT + " " + "More words here. " * 10}).json()
    assert all("changeIndex" not in e and e["explanation"] is None for e in view["edits"].values())


def test_production_mode_refuses_development_defaults():
    import subprocess
    import sys

    def start(**env):
        full = {**os.environ, "COWRITE_ENV_FILE": os.devnull, "COWRITE_PRODUCTION": "1", "COWRITE_DEMO": "0", **env}
        for k in ("COWRITE_SECRET", "COWRITE_ADMIN_PASSWORD"):
            if full.get(k) is None:
                full.pop(k, None)
        return subprocess.run([sys.executable, "-c", "import app.main"], env=full, capture_output=True, text=True,
                              cwd=Path(__file__).resolve().parents[1])

    bad = start(COWRITE_SECRET=None, COWRITE_ADMIN_PASSWORD=None)
    assert bad.returncode != 0 and "COWRITE_SECRET" in bad.stderr and "COWRITE_ADMIN_PASSWORD" in bad.stderr
    assert "COWRITE_DEMO=0" in start(COWRITE_SECRET="s" * 40, COWRITE_ADMIN_PASSWORD="p" * 12, COWRITE_DEMO="1").stderr
    assert start(COWRITE_SECRET="s" * 40, COWRITE_ADMIN_PASSWORD="p" * 12).returncode == 0
