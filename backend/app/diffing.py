"""Word-level diff between the original and revised text.

Tokens: each CJK character is one token, runs of letters/digits (with inner
apostrophes or hyphens) are one token, whitespace runs are one token, and any
other character (punctuation) is its own token. Adjacent changes separated by
at most one unchanged word (and no punctuation) are merged into one edit.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

_CJK = "぀-ヿ㐀-䶿一-鿿豈-﫿가-힯"
_WORD_CHAR = rf"(?:(?![{_CJK}])[^\W_])"
TOKEN_RE = re.compile(
    rf"[{_CJK}]"
    rf"|{_WORD_CHAR}+(?:['’\-]{_WORD_CHAR}+)*"
    r"|\s+"
    r"|\S"
)
_WORD_RE = re.compile(rf"[{_CJK}]|{_WORD_CHAR}")


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text)


def _kind(token: str) -> str:
    if token.isspace():
        return "space"
    if _WORD_RE.match(token):
        return "word"
    return "punct"


@dataclass
class Span:
    o_start: int
    o_end: int
    r_start: int
    r_end: int


def _offsets(tokens: list[str]) -> list[int]:
    out = [0]
    for t in tokens:
        out.append(out[-1] + len(t))
    return out


def _mergeable(gap: list[str], max_gap_words: int) -> bool:
    kinds = [_kind(t) for t in gap]
    return "punct" not in kinds and kinds.count("word") <= max_gap_words


def diff_spans(original: str, revised: str, max_gap_words: int = 1) -> list[Span]:
    a, b = tokenize(original), tokenize(revised)
    ao, bo = _offsets(a), _offsets(b)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)

    groups: list[list[int]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if groups and _mergeable(a[groups[-1][1]:i1], max_gap_words):
            groups[-1][1], groups[-1][3] = i2, j2
        else:
            groups.append([i1, i2, j1, j2])

    spans = []
    for i1, i2, j1, j2 in groups:
        s = Span(ao[i1], ao[i2], bo[j1], bo[j2])
        # Trim whitespace that both sides share at the edges.
        while s.o_start < s.o_end and s.r_start < s.r_end and original[s.o_start].isspace() and revised[s.r_start].isspace():
            s.o_start += 1
            s.r_start += 1
        while s.o_start < s.o_end and s.r_start < s.r_end and original[s.o_end - 1].isspace() and revised[s.r_end - 1].isspace():
            s.o_end -= 1
            s.r_end -= 1
        spans.append(s)
    return spans


def _find_all(haystack: str, needle: str, start: int):
    i = haystack.find(needle, start)
    while i != -1:
        yield i
        i = haystack.find(needle, i + 1)


def align_spans(original: str, revised: str, pairs: list[tuple[str, str]]) -> list[Span] | None:
    """Locate pre-segmented edits (original fragment, revised fragment) in order.

    Text between consecutive edits must be identical on both sides. Returns
    None when the given edits do not fully explain the difference.
    """
    co = cr = 0
    out: list[Span] = []
    for po, pr in pairs:
        if not po and not pr:
            return None
        found = None
        if pr:
            for rs in _find_all(revised, pr, cr):
                between = revised[cr:rs]
                os_ = co + len(between)
                if original[co:os_] == between and original.startswith(po, os_):
                    found = Span(os_, os_ + len(po), rs, rs + len(pr))
                    break
        else:
            for os_ in _find_all(original, po, co):
                between = original[co:os_]
                rs = cr + len(between)
                if revised[cr:rs] == between:
                    found = Span(os_, os_ + len(po), rs, rs)
                    break
        if found is None:
            return None
        out.append(found)
        co, cr = found.o_end, found.r_end
    if original[co:] != revised[cr:]:
        return None
    return out


def build_segments(original: str, spans: list[Span]) -> list[dict]:
    """Shared segment sequence; edit ids are e1..en in reading order."""
    segments: list[dict] = []
    cursor = 0
    for n, s in enumerate(spans, start=1):
        if s.o_start > cursor:
            segments.append({"kind": "same", "text": original[cursor:s.o_start]})
        segments.append({"kind": "edit", "editId": f"e{n}"})
        cursor = s.o_end
    if cursor < len(original):
        segments.append({"kind": "same", "text": original[cursor:]})
    return segments
