"""AI revision through Kimi (Moonshot, OpenAI-compatible chat completions).

Pipeline for one draft:
  1. Revise: the model returns the full revised text plus a list of changes
     (fragment, type grammar/content, one-sentence explanation).
  2. Diff: edits are computed from the two texts ourselves, because model-reported
     fragments are not reliably exact. Each diff span is matched to a reported
     change by position; spans covered by the same change are merged.
  3. Explain: diff spans no reported change covers get a second call that
     classifies and explains them (marked as post-hoc explanations).
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Callable

import httpx

from .diffing import Span, build_segments, diff_spans
from .importer import make_edit
from .tasks import task_brief

ENHANCE_PROMPT_VERSION = "enhance-v3"
EXPLAIN_PROMPT_VERSION = "explain-v1"

ENHANCE_SYSTEM = """You are helping someone revise a message they are about to send in a high-stakes situation, such as resigning, asking a boss for something, apologizing, applying for a job, or asking someone on a date. The writer will read your revision next to your explanations and decide what to keep, so each change has to make sense on its own.

Revise the message so it is more likely to get the writer what they want from this reader, while keeping it recognizably theirs:
 - Keep the writer's intent, the facts they state, and their voice. Don't invent details such as names, dates, accomplishments, or promises. If something important is missing, add a short bracketed placeholder like [start date] and explain why it belongs there.
 - Change only what improves the message. Leave parts that already work alone; a strong message may need only a few changes.
 - Match the register the situation calls for. A text to a crush shouldn't read like a cover letter, and an apology to a client shouldn't read like a press release.

Output format:
- "revised": the whole revised message, not only the changed parts, in the same language as the draft.
- "changes": every place where your revision differs from the draft, in reading order:
  - "original": the exact text from the draft that you replaced, copied character for character ("" if you only inserted text).
  - "revised": the exact text that replaces it in your revision, copied character for character ("" if you only deleted text).
  - "type": "grammar" if the change only fixes spelling, punctuation, capitalization, or grammar without changing word choice, tone, or meaning; otherwise "content".
  - "explanation": one sentence addressed to the writer ("you") explaining why you made the change.
- Edit at the word and short-phrase level. Keep the writer's sentences and change only the specific words that weaken them: swap a word, cut a hedge, add a missing word or detail. Don't replace or restructure a whole sentence, even when you would phrase it differently yourself. Each entry in "changes" should be a single word or short phrase (usually one to five words) with its own explanation; replacing more than about eight words at once should be rare.

Respond with one JSON object and nothing else:
{"revised": "<full revised message>", "changes": [{"original": "...", "revised": "...", "type": "grammar", "explanation": "..."}]}"""

EXPLAIN_SYSTEM = """You are a writing assistant. You revised a person's draft to help them accomplish a task. Below are the task, the draft, your revision, and a numbered list of changes between them. For each change, say whether it only fixes spelling, punctuation, capitalization, or grammar ("grammar") or changes anything else such as word choice, tone, content, or meaning ("content"), and explain in one sentence addressed to the writer ("you") why the change was made.

Respond with one JSON object and nothing else:
{"changes": [{"id": "1", "type": "content", "explanation": "..."}]}"""


class LLMError(RuntimeError):
    pass


PROVIDER_DEFAULTS = {
    "openai": {"base": "https://api.openai.com/v1", "model": "gpt-6-sol"},
    "kimi": {"base": "https://api.moonshot.ai/v1", "model": "kimi-k3"},
}


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def provider_names() -> list[str]:
    """Providers in fallback order, from LLM_PROVIDERS (e.g. "openai,kimi")."""
    raw = _env("LLM_PROVIDERS") or _env("LLM_PROVIDER") or "openai,kimi"
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def provider_config(name: str) -> dict | None:
    """Settings from <NAME>_API_KEY / _BASE_URL / _MODEL / _REASONING_EFFORT / _TEMPERATURE / _TIMEOUT."""
    prefix = name.upper()
    key = _env(f"{prefix}_API_KEY")
    if not key:
        return None
    defaults = PROVIDER_DEFAULTS.get(name, {})
    return {
        "name": name,
        "key": key,
        "base": (_env(f"{prefix}_BASE_URL") or defaults.get("base", "")).rstrip("/"),
        "model": _env(f"{prefix}_MODEL") or defaults.get("model", ""),
        "reasoning_effort": _env(f"{prefix}_REASONING_EFFORT") or None,
        "temperature": _env(f"{prefix}_TEMPERATURE") or None,
        "timeout": float(_env(f"{prefix}_TIMEOUT") or "180"),
    }


def configured_providers() -> list[dict]:
    return [c for c in map(provider_config, provider_names()) if c and c["base"] and c["model"]]


def model_name() -> str:
    """Primary model, for display."""
    providers = configured_providers()
    return f"{providers[0]['name']}:{providers[0]['model']}" if providers else ""


def _parse_json(text: str) -> Any:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ValueError("no JSON object in response")
    return json.loads(text[start:end + 1])


def _call_provider(p: dict, system: str, user: str, validate: Callable[[Any], bool]) -> tuple[Any, str]:
    """One provider in JSON mode; retries once on a bad response."""
    body: dict[str, Any] = {
        "model": p["model"],
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_object"},
    }
    if p["reasoning_effort"]:
        body["reasoning_effort"] = p["reasoning_effort"]
    if p["temperature"]:
        body["temperature"] = float(p["temperature"])
    last_error = "unknown error"
    for _ in range(2):
        try:
            r = httpx.post(f"{p['base']}/chat/completions", headers={"Authorization": f"Bearer {p['key']}"},
                           json=body, timeout=p["timeout"])
            r.raise_for_status()
            raw = r.json()["choices"][0]["message"]["content"]
            obj = _parse_json(raw)
            if validate(obj):
                return obj, raw
            last_error = "response did not match the expected JSON shape"
        except httpx.HTTPStatusError as e:
            last_error = f"HTTP {e.response.status_code}: {e.response.text[:300]}"
            if e.response.status_code in (400, 401, 403, 404):
                break
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as e:
            last_error = str(e) or type(e).__name__
    raise LLMError(f"{p['name']}:{p['model']} failed: {last_error}")


def chat_json(system: str, user: str, validate: Callable[[Any], bool], prefer: str | None = None) -> tuple[Any, str, dict]:
    """Tries each configured provider in order (`prefer` first). Returns (obj, raw, provider info)."""
    providers = configured_providers()
    if not providers:
        raise LLMError("AI revision is not configured (no API key for any provider in LLM_PROVIDERS).")
    if prefer:
        providers.sort(key=lambda p: p["name"] != prefer)
    errors = []
    for p in providers:
        try:
            obj, raw = _call_provider(p, system, user, validate)
            return obj, raw, {"provider": p["name"], "model": p["model"], "fallbackErrors": errors}
        except LLMError as e:
            errors.append(str(e))
    raise LLMError("AI revision failed. " + " | ".join(errors))


def _valid_revision(obj: Any) -> bool:
    return (
        isinstance(obj, dict)
        and isinstance(obj.get("revised"), str)
        and obj["revised"].strip() != ""
        and isinstance(obj.get("changes", []), list)
    )


def _valid_explain(obj: Any) -> bool:
    return isinstance(obj, dict) and isinstance(obj.get("changes"), list)


def normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _locate(haystack: str, needle: str, cursor: int) -> tuple[int, int] | None:
    if not needle:
        return None
    i = haystack.find(needle, cursor)
    if i == -1:
        i = haystack.find(needle)
    return None if i == -1 else (i, i + len(needle))


def _overlaps(span: tuple[int, int], rng: tuple[int, int] | None) -> bool:
    if rng is None:
        return False
    a, b = span
    x, y = rng
    return (a < y and x < b) if a < b else x <= a <= y


def match_changes(draft: str, revised: str, changes: list[dict], spans: list[Span]) -> list[tuple[Span, int | None]]:
    """Assign each diff span the reported change that covers it (by position).

    Highlights stay at diff granularity: a sentence-level change reported by the
    model that touches three words yields three edits sharing one explanation.
    """
    located = []
    co = cr = 0
    for c in changes:
        o = _locate(draft, str(c.get("original") or ""), co)
        r = _locate(revised, str(c.get("revised") or ""), cr)
        if o:
            co = o[1]
        if r:
            cr = r[1]
        located.append((o, r))
    return [
        (s, next((i for i, (o, r) in enumerate(located)
                  if _overlaps((s.r_start, s.r_end), r) or _overlaps((s.o_start, s.o_end), o)), None))
        for s in spans
    ]


def _kind(value: Any) -> str:
    return "grammar" if str(value).lower() == "grammar" else "content"


def _explain_missing(brief: str, draft: str, revised: str, missing: list[tuple[str, str]], prefer: str) -> tuple[dict[str, dict], dict]:
    listing = "\n".join(f'{n}. "{o}" → "{r}"' for n, (o, r) in enumerate(missing, start=1))
    user = f"Task:\n{brief}\n\nDraft:\n<<<\n{draft}\n>>>\n\nRevision:\n<<<\n{revised}\n>>>\n\nChanges:\n{listing}"
    obj, _, used = chat_json(EXPLAIN_SYSTEM, user, _valid_explain, prefer=prefer)
    return {str(c.get("id")): c for c in obj["changes"] if isinstance(c, dict)}, used


def enhance(task: dict, draft: str) -> dict:
    """Returns session content: {original, revised, segments, edits, meta}."""
    draft = normalize(draft)
    brief = task_brief(task)
    started = time.time()
    obj, raw, used = chat_json(ENHANCE_SYSTEM, f"The writer's situation:\n{brief}\n\nTheir draft:\n<<<\n{draft}\n>>>", _valid_revision)
    revised = normalize(obj["revised"])
    changes = [c for c in obj.get("changes", []) if isinstance(c, dict)]
    matched = match_changes(draft, revised, changes, diff_spans(draft, revised))
    pairs = [(s, None if i is None else changes[i]) for s, i in matched]

    model = f"{used['provider']}:{used['model']}"
    explain_model = model
    explain_error = None
    missing = [(n, s) for n, (s, c) in enumerate(pairs) if c is None or not str(c.get("explanation") or "").strip()]
    post_hoc: dict[str, dict] = {}
    if missing:
        try:
            post_hoc, explain_used = _explain_missing(
                brief, draft, revised, [(draft[s.o_start:s.o_end], revised[s.r_start:s.r_end]) for _, s in missing],
                prefer=used["provider"])
            explain_model = f"{explain_used['provider']}:{explain_used['model']}"
        except LLMError as e:
            explain_error = str(e)
    post_hoc_by_index = {n: post_hoc.get(str(k)) for k, (n, _) in enumerate(missing, start=1)}

    edits = {}
    for n, (s, c) in enumerate(pairs):
        eid = f"e{n + 1}"
        extra = post_hoc_by_index.get(n)
        if c is not None and str(c.get("explanation") or "").strip():
            explanation = {"text": str(c["explanation"]).strip(), "model": model,
                           "promptVersion": ENHANCE_PROMPT_VERSION, "mode": "self"}
            kind = _kind(c.get("type"))
        elif extra and str(extra.get("explanation") or "").strip():
            explanation = {"text": str(extra["explanation"]).strip(), "model": explain_model,
                           "promptVersion": EXPLAIN_PROMPT_VERSION, "mode": "post_hoc"}
            kind = _kind(extra.get("type"))
        else:
            explanation, kind = None, _kind(c.get("type")) if c else "content"
        edits[eid] = make_edit(eid, draft, revised, s, explanation, kind)
        edits[eid]["changeIndex"] = matched[n][1]  # which reported change it came from (shared explanations)

    return {
        "original": draft,
        "revised": revised,
        "segments": build_segments(draft, [s for s, _ in pairs]),
        "edits": edits,
        "meta": {
            "rewriteModel": model,
            "fallbackErrors": used["fallbackErrors"],
            "enhancePromptVersion": ENHANCE_PROMPT_VERSION,
            "explanationMode": "self",
            "postHocExplained": len(missing),
            "explainError": explain_error,
            "latencySeconds": round(time.time() - started, 2),
            "rawResponse": raw,
        },
    }
