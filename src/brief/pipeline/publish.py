"""collect -> select -> compose -> render -> store -> prune -> OPDS."""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from brief.config import Config
from brief.db import Database, PublicationRecord
from brief.pipeline.collect import collect
from brief.pipeline.compose import compose, publication_id
from brief.pipeline.select import select
from brief.render.epub import build_epub
from brief.render.opds import build_opds

log = logging.getLogger(__name__)


@dataclass
class PublishOutcome:
    record: PublicationRecord
    skipped: bool  # today's publication already existed


def publish(
    config: Config,
    db: Database,
    *,
    force: bool = False,
    collect_first: bool = True,
    now: datetime | None = None,
    client=None,
) -> PublishOutcome:
    now = now or datetime.now(UTC)
    pub_id, local_date = publication_id(config, now)

    existing = db.get_publication(pub_id)
    if existing and not existing.pruned and not force:
        log.info("publication %s already exists; use --force to rebuild", pub_id)
        return PublishOutcome(existing, skipped=True)

    statuses = collect(config, db, client=client) if collect_first else []
    items = db.items_since(now - timedelta(hours=config.publish.window_hours))
    selection = select(config, items, db.published_item_ids(exclude_publication=pub_id), now)
    publication = compose(config, selection, statuses, now)
    data = build_epub(publication)

    filename = f"{pub_id}.epub"
    _write_atomic(config.publications_dir / filename, data)

    article_count = len(publication.articles)
    source_names = ", ".join(s.title for s in publication.sections) or "새 기사 없음"
    record = PublicationRecord(
        id=pub_id,
        kind="morning-brief",
        title=publication.title,
        author=publication.author,
        created_at=now,
        local_date=local_date,
        filename=filename,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        config_hash=publication.config_hash,
        summary=f"기사 {article_count}개 · {source_names}",
        pruned=False,
    )
    db.add_publication(record, [a.item.id for a in publication.articles])
    prune(config, db)
    write_catalog(config, db, now)
    log.info("published %s (%d articles, %d bytes)", pub_id, article_count, len(data))
    return PublishOutcome(record, skipped=False)


def prune(config: Config, db: Database) -> None:
    for record in db.live_publications()[config.publish.keep_publications :]:
        path = config.publications_dir / record.filename
        if path.exists():
            path.unlink()
        db.mark_pruned(record.id)
        log.info("pruned %s", record.id)


def write_catalog(config: Config, db: Database, now: datetime) -> None:
    feed = build_opds(db.live_publications(), now, config.publish.author, config.publish.author)
    _write_atomic(config.www_dir / "opds.xml", feed)


def _write_atomic(path: Path, data: bytes) -> None:
    """Write next to the target then rename, so a reader never downloads a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
