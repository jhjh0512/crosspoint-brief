"""Command line: brief collect | publish | run | serve | status."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from datetime import UTC, datetime

from brief import __version__
from brief.config import ConfigError, load_config
from brief.db import Database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="brief", description="CrossPoint morning brief publisher")
    parser.add_argument("--config", default=os.environ.get("BRIEF_CONFIG", "config.toml"))
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--version", action="version", version=f"crosspoint-brief {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("collect", help="fetch every enabled source once")
    p_publish = sub.add_parser("publish", help="build today's brief now")
    p_publish.add_argument("--force", action="store_true", help="rebuild even if today's brief exists")
    p_publish.add_argument("--no-collect", action="store_true", help="use stored items only")
    p_run = sub.add_parser("run", help="scheduler: collect periodically, publish daily")
    p_run.add_argument("--serve", type=int, metavar="PORT", help="also serve the web root (development)")
    p_serve = sub.add_parser("serve", help="serve opds.xml and EPUBs (development)")
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=8080)
    sub.add_parser("status", help="show sources, runs and publications")

    args = parser.parse_args(argv)
    # Windows consoles and pipes default to a legacy code page (cp949) that cannot print every
    # character in titles; always emit UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    if args.command == "serve":
        from brief.serve import serve

        serve(config.www_dir, args.host, args.port)
        return 0

    if args.command == "run":
        from brief import scheduler

        if args.serve:
            from brief.serve import serve

            threading.Thread(target=serve, args=(config.www_dir, "0.0.0.0", args.serve), daemon=True).start()
        scheduler.run(config)
        return 0

    db = Database(config.db_path)
    try:
        if args.command == "collect":
            from brief.pipeline.collect import collect

            statuses = collect(config, db)
            for s in statuses:
                print(f"{s.source_id}: {'ok' if s.ok else 'FAILED'} — {s.detail}")
            return 0 if all(s.ok for s in statuses) else 1

        if args.command == "publish":
            from brief.pipeline.publish import publish

            run_id = db.start_run("publish", datetime.now(UTC))
            try:
                outcome = publish(config, db, force=args.force, collect_first=not args.no_collect)
            except Exception as exc:
                db.finish_run(run_id, datetime.now(UTC), "failed", f"{exc.__class__.__name__}: {exc}")
                raise
            record = outcome.record
            db.finish_run(run_id, datetime.now(UTC), "ok", f"{record.id} skipped={outcome.skipped}")
            state = "already exists (use --force)" if outcome.skipped else "built"
            print(f"{record.id}: {state} — {record.summary}")
            print(f"  file: {config.publications_dir / record.filename} ({record.size} bytes)")
            return 0

        if args.command == "status":
            _print_status(config, db)
            return 0
    finally:
        db.close()
    return 1


def _print_status(config, db: Database) -> None:
    print(f"data: {config.data_dir}")
    print("sources:")
    for source in config.sources:
        state = db.get_source_state(source.id)
        flag = "on " if source.enabled else "off"
        last = state.last_ok_at.isoformat() if state.last_ok_at else "never"
        err = f"  last error: {state.last_error}" if state.last_error else ""
        print(f"  [{flag}] {source.id} ({source.connector}) last ok {last}{err}")
    print("last runs:")
    for kind in ("collect", "publish"):
        row = db.last_run(kind)
        if row:
            print(f"  {kind}: {row['status']} at {row['started_at']} {row['detail']}")
    print("publications:")
    for record in db.live_publications():
        print(f"  {record.id}  {record.size:>8} bytes  {record.summary}")
