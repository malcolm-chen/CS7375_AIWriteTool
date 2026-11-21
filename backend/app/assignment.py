"""Counterbalanced assignment of task order x explanation condition.

Every participant writes every task in STUDY_TASKS, one under each condition in STUDY_CONDITIONS.
The candidate assignments are every task order crossed with every condition order (2 x 2 = 4 for two
tasks), and each participant gets a random choice among the candidates used least so far.

Assignment happens when the participant first opens their link, not when the link is created, so
links that are never opened take no slot. Only participants still in the study count toward balance:
those who finished, and those who started less than COWRITE_ABANDON_HOURS (default 24) ago. Demo
sessions never count.
"""
from __future__ import annotations

import itertools
import json
import os
import secrets
from datetime import datetime, timedelta, timezone

from .tasks import STUDY_CONDITIONS, STUDY_TASKS

Assignment = tuple[tuple[str, str], ...]  # ((task_id, condition), ...) in the order they are written

COUNTED = ("completed", "in_progress")


def abandon_hours() -> float:
    return float(os.environ.get("COWRITE_ABANDON_HOURS") or 24)


def candidates() -> list[Assignment]:
    return [tuple(zip(tasks, conds)) for tasks in itertools.permutations(STUDY_TASKS)
            for conds in itertools.permutations(STUDY_CONDITIONS)]


def _content_edits(edits_json: str | None) -> int:
    edits = json.loads(edits_json) if edits_json else {}
    return sum(1 for e in edits.values() if e.get("kind") != "grammar")


def group_statuses(conn) -> dict[str, dict]:
    """Per participant group: status ('unassigned' | 'in_progress' | 'completed' | 'abandoned'),
    assignment, and whether it is a demo.

    Completed means every task reached review and every highlighted edit has a decision.
    """
    decided = {r["session_id"]: r["n"] for r in
               conn.execute("SELECT session_id, COUNT(*) AS n FROM decisions GROUP BY session_id")}
    groups: dict[str, list] = {}
    for r in conn.execute("SELECT id, group_id, participant_id, task_id, condition, stage, edits, assigned_at,"
                          " created_at, demo FROM sessions WHERE group_id IS NOT NULL ORDER BY group_id, seq"):
        groups.setdefault(r["group_id"], []).append(r)

    cutoff = datetime.now(timezone.utc) - timedelta(hours=abandon_hours())
    out = {}
    for gid, rows in groups.items():
        info = {"participantId": rows[0]["participant_id"], "demo": bool(rows[0]["demo"]), "assignment": None}
        if not all(r["task_id"] for r in rows):
            info["status"] = "unassigned"
        else:
            info["assignment"] = tuple((r["task_id"], r["condition"]) for r in rows)
            # Groups assigned before assigned_at existed fall back to their creation time.
            started = datetime.fromisoformat(rows[0]["assigned_at"] or rows[0]["created_at"])
            if all(r["stage"] == "review" and decided.get(r["id"], 0) >= _content_edits(r["edits"]) for r in rows):
                info["status"] = "completed"
            elif started < cutoff:
                info["status"] = "abandoned"
            else:
                info["status"] = "in_progress"
        out[gid] = info
    return out


def pick(conn) -> Assignment:
    """A random choice among the candidates with the fewest participants still in the study."""
    options = candidates()
    used = {c: 0 for c in options}
    for g in group_statuses(conn).values():
        if not g["demo"] and g["status"] in COUNTED and g["assignment"] in used:
            used[g["assignment"]] += 1
    fewest = min(used.values())
    return secrets.choice([c for c in options if used[c] == fewest])


def assign_group(conn, group_id: str, *, demo: bool = False) -> Assignment | None:
    """Assigns tasks and conditions to an unassigned group. Returns the assignment, or None when the
    group was already assigned. Demo groups get a uniformly random assignment."""
    if not conn.in_transaction:
        # Take the write lock before counting, so two participants opening their links at the same
        # moment can't both be given the same least-used slot.
        conn.execute("BEGIN IMMEDIATE")
    rows = conn.execute("SELECT id, task_id FROM sessions WHERE group_id = ? ORDER BY seq", (group_id,)).fetchall()
    if not rows or all(r["task_id"] for r in rows):
        return None
    assignment = secrets.choice(candidates()) if demo else pick(conn)
    if len(rows) != len(assignment):
        raise RuntimeError(f"group {group_id} has {len(rows)} sessions but the study has {len(assignment)} tasks")
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    for r, (task_id, condition) in zip(rows, assignment):
        conn.execute("UPDATE sessions SET task_id = ?, condition = ?, assigned_at = ? WHERE id = ?",
                     (task_id, condition, ts, r["id"]))
    return assignment


def balance_report(conn) -> dict:
    """Counts for the admin page (demo sessions left out)."""
    every = group_statuses(conn)
    statuses = {gid: g for gid, g in every.items() if not g["demo"]}
    cells = []
    for c in candidates():
        counts = {s: 0 for s in ("completed", "in_progress", "abandoned")}
        for g in statuses.values():
            if g["assignment"] == c:
                counts[g["status"]] += 1
        cells.append({"assignment": [{"taskId": t, "condition": cond} for t, cond in c], **counts})
    by_task = []
    for t in STUDY_TASKS:
        for cond in STUDY_CONDITIONS:
            n = {s: 0 for s in COUNTED}
            for g in statuses.values():
                if g["status"] in COUNTED and (t, cond) in g["assignment"]:
                    n[g["status"]] += 1
            by_task.append({"taskId": t, "condition": cond, **n})
    return {
        "cells": cells,
        "byTaskCondition": by_task,
        "unopened": sum(1 for g in statuses.values() if g["status"] == "unassigned"),
        "abandonHours": abandon_hours(),
        "groups": {gid: g["status"] for gid, g in every.items()},
    }
