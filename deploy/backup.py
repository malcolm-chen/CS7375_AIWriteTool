"""Consistent copy of the SQLite database, safe while the server is running.

    backend/.venv/bin/python deploy/backup.py [--keep 30]

Writes backend/data/backups/cowrite-YYYYmmdd-HHMMSS.db and deletes all but the newest --keep
copies. Copying the .db file with cp while the server writes can produce a corrupt copy; this uses
SQLite's online backup API instead. Run daily by cowrite-backup.timer (see deploy/README.md).
Copy the backups off this machine too.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "backend" / "data"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=os.environ.get("COWRITE_DB") or str(DATA / "cowrite.db"))
    p.add_argument("--out", default=str(DATA / "backups"))
    p.add_argument("--keep", type=int, default=30)
    args = p.parse_args()

    src_path = Path(args.db)
    if not src_path.is_file():
        raise SystemExit(f"no database at {src_path}")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    dest_path = out / f"cowrite-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"

    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    dest = sqlite3.connect(dest_path)
    try:
        src.backup(dest)
        ok = dest.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        src.close()
        dest.close()
    if ok != "ok":
        dest_path.unlink(missing_ok=True)
        raise SystemExit(f"backup failed the integrity check: {ok}")

    backups = sorted(out.glob("cowrite-*.db"))
    for old in backups[:-args.keep] if args.keep > 0 else []:
        old.unlink()
    print(f"backed up to {dest_path} ({len(backups[-args.keep:])} kept)")


if __name__ == "__main__":
    main()
