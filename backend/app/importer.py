"""Turn pre-generated revision records into session content.

Accepted top-level shapes (see sample_data/sample_revisions.json):
  * a list of records
  * {"items": [records...]}
  * {"<sourceId>": record, ...}

A record needs `original` and `revised`. `edits` is optional; when given, each
edit carries its own fragments plus an optional explanation and judge result.
When `edits` is missing (or cannot be aligned with the texts) the edits are
computed with a word-level diff.
"""
from __future__ import annotations

from typing import Any

from .diffing import Span, align_spans, build_segments, diff_spans

CATEGORIES = {"semantic", "wording"}
DIMENSIONS = {
    "certainty_up", "certainty_down", "hedge_removed", "hedge_added", "meaning_reversed",
    "scope_changed", "stance_changed", "info_added", "info_removed", "phrasing",
}
_ORIGINAL_KEYS = ("original", "original_text", "source")
_REVISED_KEYS = ("revised", "revised_text", "rewrite", "ai_text")
_EXPLANATION_KEYS = ("explanation", "reason")
_KIND_KEYS = ("kind", "type")


class RecordError(ValueError):
    pass


def _pick(d: dict, keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in d:
            return d[k]
    return None


def iter_records(data: Any) -> list[tuple[str | None, dict]]:
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        data = data["items"]
    if isinstance(data, list):
        return [(r.get("id") if isinstance(r, dict) else None, r) for r in data]
    if isinstance(data, dict):
        if any(k in data for k in _ORIGINAL_KEYS):
            return [(data.get("id"), data)]
        return [(k, v) for k, v in data.items()]
    raise RecordError("Expected a list of records, {\"items\": [...]}, or an object keyed by id.")


def _explanation(raw: Any, record: dict) -> dict | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = {"text": raw}
    if not isinstance(raw, dict) or not str(raw.get("text", "")).strip():
        return None
    return {
        "text": str(raw["text"]).strip(),
        "model": raw.get("model") or record.get("explanationModel"),
        "promptVersion": raw.get("promptVersion") or record.get("explanationPromptVersion"),
    }


def validate_judge(raw: Any, record: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    category, dimension = raw.get("category"), raw.get("dimension")
    if category not in CATEGORIES or dimension not in DIMENSIONS:
        return None
    confidence = raw.get("confidence")
    if confidence is not None:
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            return None
        confidence = float(confidence)
    return {
        "category": category,
        "dimension": dimension,
        "confidence": confidence,
        "rationale": raw.get("rationale"),
        "model": raw.get("model") or record.get("judgeModel"),
        "promptVersion": raw.get("promptVersion") or record.get("judgePromptVersion"),
    }


def make_edit(eid: str, original: str, revised: str, s: Span, explanation: dict | None, kind: str, judge: dict | None = None) -> dict:
    """kind 'grammar' edits are applied but not highlighted for review."""
    return {
        "id": eid,
        "original": original[s.o_start:s.o_end],
        "revised": revised[s.r_start:s.r_end],
        "originalRange": [s.o_start, s.o_end],
        "revisedRange": [s.r_start, s.r_end],
        "kind": kind,
        "explanation": explanation,
        "judge": judge,
    }


def build_content(record: Any) -> tuple[dict, list[str]]:
    """Returns ({original, revised, segments, edits, meta}, warnings)."""
    if not isinstance(record, dict):
        raise RecordError("Record must be an object.")
    original, revised = _pick(record, _ORIGINAL_KEYS), _pick(record, _REVISED_KEYS)
    if not isinstance(original, str) or not isinstance(revised, str):
        raise RecordError("Record needs string fields `original` and `revised`.")

    warnings: list[str] = []
    given = record.get("edits")
    given = given if isinstance(given, list) else None
    annotations: list[dict | None] = []
    spans: list[Span] | None = None

    if given:
        pairs = [(str(e.get("original") or ""), str(e.get("revised") or "")) for e in given if isinstance(e, dict)]
        spans = align_spans(original, revised, pairs)
        if spans is None:
            warnings.append("Provided edits do not line up with the texts; edits were recomputed by diff and annotations matched by text.")
        else:
            annotations = [e for e in given if isinstance(e, dict)]

    if spans is None:
        spans = diff_spans(original, revised)
        unused = [e for e in (given or []) if isinstance(e, dict)]
        for s in spans:
            o, r = original[s.o_start:s.o_end].strip(), revised[s.r_start:s.r_end].strip()
            match = next((e for e in unused if str(e.get("original") or "").strip() == o and str(e.get("revised") or "").strip() == r), None)
            if match is not None:
                unused.remove(match)
            annotations.append(match)
        if given and unused:
            warnings.append(f"{len(unused)} provided edit annotation(s) could not be matched and were dropped.")

    edits: dict[str, dict] = {}
    for n, (s, ann) in enumerate(zip(spans, annotations), start=1):
        eid = f"e{n}"
        ann = ann or {}
        judge = None
        if "judge" in ann and ann["judge"] is not None:
            judge = validate_judge(ann["judge"], record)
            if judge is None:
                warnings.append(f"{eid}: invalid judge result, stored as null.")
        kind = "grammar" if str(_pick(ann, _KIND_KEYS) or "").lower() == "grammar" else "content"
        edits[eid] = make_edit(eid, original, revised, s, _explanation(_pick(ann, _EXPLANATION_KEYS), record), kind, judge)

    meta = {k: record.get(k) for k in (
        "rewriteModel", "explanationMode", "explanationModel", "explanationPromptVersion",
        "judgeModel", "judgePromptVersion", "notes",
    ) if record.get(k) is not None}
    return {
        "original": original,
        "revised": revised,
        "segments": build_segments(original, spans),
        "edits": edits,
        "meta": meta,
    }, warnings
