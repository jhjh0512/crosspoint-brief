"""Run every enabled source's connector and store the results."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx

from brief.config import Config
from brief.connectors import ConnectorError, get_connector
from brief.db import Database
from brief.models import SourceStatus

log = logging.getLogger(__name__)


def make_client(config: Config) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": config.collect.user_agent},
        timeout=config.collect.timeout_seconds,
        follow_redirects=True,
    )


def collect(config: Config, db: Database, client: httpx.Client | None = None) -> list[SourceStatus]:
    own_client = client is None
    client = client or make_client(config)
    statuses: list[SourceStatus] = []
    try:
        for source in config.sources:
            if not source.enabled:
                continue
            statuses.append(_collect_one(source, db, client))
    finally:
        if own_client:
            client.close()
    return statuses


def _collect_one(source, db: Database, client: httpx.Client) -> SourceStatus:
    state = db.get_source_state(source.id)
    now = datetime.now(UTC)
    state.last_fetched_at = now
    try:
        result = get_connector(source.connector).fetch(source, state, client)
    except ConnectorError as exc:
        state.last_error = str(exc)
        db.save_source_state(state)
        log.warning("source %s failed: %s", source.id, exc)
        return SourceStatus(source.id, source.name, ok=False, detail=str(exc))

    state.etag = result.etag
    state.last_modified = result.last_modified
    state.last_ok_at = now
    state.last_error = None
    new = 0 if result.not_modified else db.upsert_items(result.items, now)
    db.save_source_state(state)
    detail = "변경 없음 (304)" if result.not_modified else f"항목 {len(result.items)}개 중 새 항목 {new}개"
    log.info("source %s: %s", source.id, detail)
    return SourceStatus(source.id, source.name, ok=True, new_items=new, detail=detail)
