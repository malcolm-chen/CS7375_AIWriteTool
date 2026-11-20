"""Command-line helpers.

    python -m app.cli create P01 P02 P03 [--task energy_job_inquiry]
    python -m app.cli import ../sample_data/sample_revisions.json
"""
from __future__ import annotations

import argparse
import json
import sys

from .main import CreateBody, create_sessions, import_records


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m app.cli")
    p.add_argument("--base-url", default="http://localhost:5173", help="Used to print participant links")
    sub = p.add_subparsers(dest="cmd", required=True)
    create = sub.add_parser("create", help="Create writing-task sessions: every study task, in random order, per participant")
    create.add_argument("participants", nargs="+")
    create.add_argument("--task", default=None, help="Create only this task (for piloting) instead of the full sequence")
    imp = sub.add_parser("import", help="Create review sessions from pre-generated revisions (JSON)")
    imp.add_argument("file")
    args = p.parse_args()

    if args.cmd == "create":
        result = create_sessions(CreateBody(participantIds=args.participants, taskId=args.task))
    else:
        with open(args.file, encoding="utf-8") as f:
            result = import_records(json.load(f))
    for s in result["created"]:
        if s.get("seq", 1) not in (None, 1):
            continue  # participants start from task 1 and are linked onward from there
        print(f"{s['participantId']:<10} {s['stage']:<8} {args.base_url}/session/{s['id']}?t={s['token']}")
        for w in s["warnings"]:
            print(f"    warning: {w}")
    for f_ in result.get("failed", []):
        print(f"record {f_['index']} ({f_['sourceId']}): {f_['error']}", file=sys.stderr)


if __name__ == "__main__":
    main()
