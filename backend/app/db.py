from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.environ.get("COWRITE_DB", Path(__file__).resolve().parent.parent / "data" / "cowrite.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  participant_id TEXT NOT NULL,
  task_id TEXT,
  source TEXT NOT NULL,           -- 'task' (participant writes, AI revises) or 'import'
  stage TEXT NOT NULL,            -- 'writing' | 'enhancing' | 'review'
  draft TEXT NOT NULL DEFAULT '',
  original TEXT,
  revised TEXT,
  segments TEXT,
  edits TEXT,
  meta TEXT NOT NULL DEFAULT '{}',
  source_id TEXT,
  participant_token TEXT NOT NULL,
  warnings TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  enhanced_at TEXT,
  group_id TEXT,                  -- links one participant's task sessions
  seq INTEGER,                    -- 1-based position in that participant's task order
  condition TEXT,                 -- 'reasons' | 'noReasons'; NULL shows explanations
  assigned_at TEXT,               -- when the group got its task order and conditions (first opened)
  demo INTEGER NOT NULL DEFAULT 0 -- demo sessions don't count toward balance
);
CREATE TABLE IF NOT EXISTS decisions (
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  edit_id TEXT NOT NULL,
  type TEXT NOT NULL,
  modality TEXT,
  text TEXT,
  audio_ref TEXT,
  ts TEXT NOT NULL,
  PRIMARY KEY (session_id, edit_id)
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  client_ts TEXT,
  server_ts TEXT NOT NULL,
  type TEXT NOT NULL,
  edit_id TEXT,
  payload TEXT,
  stage TEXT NOT NULL,
  actor TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_session ON events(session_id, id);
"""

JSON_COLUMNS = {"segments", "edits", "meta", "warnings", "payload"}


def init() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
        # Databases created before multi-task sessions lack these columns.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(sessions)")}
        for col, typ in (("group_id", "TEXT"), ("seq", "INTEGER"), ("condition", "TEXT"), ("assigned_at", "TEXT"),
                         ("demo", "INTEGER NOT NULL DEFAULT 0")):
            if col not in cols:
                conn.execute(f"ALTER TABLE sessions ADD COLUMN {col} {typ}")


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    out = dict(row)
    for k in JSON_COLUMNS & out.keys():
        if out[k] is not None:
            out[k] = json.loads(out[k])
    return out


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)
