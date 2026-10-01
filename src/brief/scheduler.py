"""In-app scheduler: collect every N minutes, publish once a day at publish.time (one retry).

It lives inside the app (not DSM Task Scheduler) so the publish time can later be changed from the
web admin page.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial

from brief.config import Config
from brief.db import Database
from brief.pipeline.collect import collect
from brief.pipeline.compose import publication_id
from brief.pipeline.publish import publish

log = logging.getLogger(__name__)

# A server that was down at 06:30 still builds the brief if it comes back within this window.
CATCH_UP_HOURS = 6
MAX_SLEEP_SECONDS = 60


@dataclass
class DayState:
    local_date: str = ""
    attempts: int = 0


def publish_due(config: Config, db: Database, now: datetime, state: DayState) -> bool:
    tz = config.publish.tz
    local = now.astimezone(tz)
    today = local.date()
    if state.local_date != today.isoformat():
        state.local_date = today.isoformat()
        state.attempts = 0

    pub_id, _ = publication_id(config, now)
    existing = db.get_publication(pub_id)
    if existing and not existing.pruned:
        return False

    first = datetime.combine(today, config.publish.publish_time, tz)
    retry = datetime.combine(today, config.publish.retry_at, tz)
    if local < first or local > first + timedelta(hours=CATCH_UP_HOURS):
        return False
    if state.attempts == 0:
        return True
    return state.attempts == 1 and local >= retry


def run(config: Config, stop: threading.Event | None = None) -> None:
    stop = stop or threading.Event()
    db = Database(config.db_path)
    state = DayState()
    interval = timedelta(minutes=config.collect.interval_minutes)
    next_collect = datetime.now(UTC)
    log.info(
        "scheduler started: collect every %d min, publish at %s %s",
        config.collect.interval_minutes,
        config.publish.time,
        config.publish.timezone,
    )
    try:
        while not stop.is_set():
            now = datetime.now(UTC)
            if publish_due(config, db, now, state):
                state.attempts += 1
                _run_logged(db, "publish", partial(publish, config, db, now=now))
                next_collect = now + interval  # publish just collected
            elif now >= next_collect:
                _run_logged(db, "collect", partial(collect, config, db))
                next_collect = now + interval
            wait = (next_collect - datetime.now(UTC)).total_seconds()
            stop.wait(min(MAX_SLEEP_SECONDS, max(1.0, wait)))
    finally:
        db.close()


def _run_logged(db: Database, kind: str, job) -> None:
    run_id = db.start_run(kind, datetime.now(UTC))
    try:
        result = job()
    except Exception as exc:  # keep the scheduler alive; the failure is recorded
        log.exception("%s failed", kind)
        db.finish_run(run_id, datetime.now(UTC), "failed", f"{exc.__class__.__name__}: {exc}")
        return
    db.finish_run(run_id, datetime.now(UTC), "ok", _describe(result))


def _describe(result) -> str:
    if isinstance(result, list):  # collect -> list[SourceStatus]
        return "; ".join(f"{s.source_id}: {'ok' if s.ok else 'failed'} {s.detail}" for s in result)
    record = getattr(result, "record", None)
    if record is not None:
        return f"{record.id} skipped" if result.skipped else f"{record.id} {record.size} bytes"
    return ""
