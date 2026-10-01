"""SQLite storage for items, source fetch state, publications and runs."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from brief.models import ContentItem

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_state (
    source_id TEXT PRIMARY KEY,
    etag TEXT,
    last_modified TEXT,
    last_fetched_at TEXT,
    last_ok_at TEXT,
    last_error TEXT
);
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    guid TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    canonical_url TEXT,
    summary_html TEXT NOT NULL DEFAULT '',
    body_html TEXT NOT NULL DEFAULT '',
    published_at TEXT,
    first_seen_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    language TEXT,
    author TEXT,
    signals TEXT NOT NULL DEFAULT '{}',
    tags TEXT NOT NULL DEFAULT '[]',
    ai_allowed INTEGER NOT NULL DEFAULT 1,
    content_hash TEXT NOT NULL,
    UNIQUE (source_id, guid)
);
CREATE INDEX IF NOT EXISTS items_first_seen ON items (first_seen_at);
CREATE INDEX IF NOT EXISTS items_canonical ON items (canonical_url);
CREATE TABLE IF NOT EXISTS publications (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    author TEXT NOT NULL,
    created_at TEXT NOT NULL,
    local_date TEXT NOT NULL,
    filename TEXT NOT NULL,
    size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    pruned INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS publication_items (
    publication_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (publication_id, item_id)
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
"""


def utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


@dataclass
class SourceState:
    source_id: str
    etag: str | None = None
    last_modified: str | None = None
    last_fetched_at: datetime | None = None
    last_ok_at: datetime | None = None
    last_error: str | None = None


@dataclass
class PublicationRecord:
    id: str
    kind: str
    title: str
    author: str
    created_at: datetime
    local_date: str
    filename: str
    size: int
    sha256: str
    config_hash: str
    summary: str
    pruned: bool


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(_SCHEMA)
        self.conn.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),)
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.conn
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    # --- source state -------------------------------------------------------------------------

    def get_source_state(self, source_id: str) -> SourceState:
        row = self.conn.execute("SELECT * FROM source_state WHERE source_id = ?", (source_id,)).fetchone()
        if row is None:
            return SourceState(source_id=source_id)
        return SourceState(
            source_id=source_id,
            etag=row["etag"],
            last_modified=row["last_modified"],
            last_fetched_at=parse_utc(row["last_fetched_at"]),
            last_ok_at=parse_utc(row["last_ok_at"]),
            last_error=row["last_error"],
        )

    def save_source_state(self, state: SourceState) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO source_state (source_id, etag, last_modified, last_fetched_at, last_ok_at, last_error)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (source_id) DO UPDATE SET
                    etag = excluded.etag,
                    last_modified = excluded.last_modified,
                    last_fetched_at = excluded.last_fetched_at,
                    last_ok_at = excluded.last_ok_at,
                    last_error = excluded.last_error
                """,
                (
                    state.source_id,
                    state.etag,
                    state.last_modified,
                    utc_iso(state.last_fetched_at),
                    utc_iso(state.last_ok_at),
                    state.last_error,
                ),
            )

    # --- items --------------------------------------------------------------------------------

    def upsert_items(self, items: Iterable[ContentItem], now: datetime) -> int:
        """Store items; returns how many were new. Changed items keep their first_seen_at."""
        now_iso = utc_iso(now)
        new = 0
        with self.transaction() as conn:
            for item in items:
                row = conn.execute("SELECT content_hash FROM items WHERE id = ?", (item.id,)).fetchone()
                values = (
                    item.kind,
                    item.title,
                    item.url,
                    item.canonical_url,
                    item.summary_html,
                    item.body_html,
                    utc_iso(item.published_at),
                    item.language,
                    item.author,
                    json.dumps(item.signals, sort_keys=True),
                    json.dumps(item.tags, ensure_ascii=False),
                    int(item.ai_allowed),
                    item.content_hash,
                )
                if row is None:
                    conn.execute(
                        """
                        INSERT INTO items (kind, title, url, canonical_url, summary_html, body_html,
                            published_at, language, author, signals, tags, ai_allowed, content_hash,
                            id, source_id, guid, first_seen_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (*values, item.id, item.source_id, item.guid, now_iso, now_iso),
                    )
                    new += 1
                elif row["content_hash"] != item.content_hash:
                    conn.execute(
                        """
                        UPDATE items SET kind = ?, title = ?, url = ?, canonical_url = ?, summary_html = ?,
                            body_html = ?, published_at = ?, language = ?, author = ?, signals = ?, tags = ?,
                            ai_allowed = ?, content_hash = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (*values, now_iso, item.id),
                    )
        return new

    def items_since(self, since: datetime) -> list[ContentItem]:
        """Items first seen or published at/after `since`."""
        since_iso = utc_iso(since)
        rows = self.conn.execute(
            """
            SELECT * FROM items
            WHERE first_seen_at >= ? OR (published_at IS NOT NULL AND published_at >= ?)
            """,
            (since_iso, since_iso),
        ).fetchall()
        return [_row_to_item(r) for r in rows]

    def published_item_ids(self, exclude_publication: str | None = None) -> set[str]:
        """Items already used in a publication (optionally ignoring one, when rebuilding it)."""
        rows = self.conn.execute(
            "SELECT item_id FROM publication_items WHERE publication_id IS NOT ?", (exclude_publication,)
        )
        return {r["item_id"] for r in rows}

    # --- publications -------------------------------------------------------------------------

    def get_publication(self, publication_id: str) -> PublicationRecord | None:
        row = self.conn.execute("SELECT * FROM publications WHERE id = ?", (publication_id,)).fetchone()
        return _row_to_publication(row) if row else None

    def add_publication(self, record: PublicationRecord, item_ids: list[str]) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM publication_items WHERE publication_id = ?", (record.id,))
            conn.execute(
                """
                INSERT OR REPLACE INTO publications (id, kind, title, author, created_at, local_date, filename,
                    size, sha256, config_hash, summary, pruned)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    record.id,
                    record.kind,
                    record.title,
                    record.author,
                    utc_iso(record.created_at),
                    record.local_date,
                    record.filename,
                    record.size,
                    record.sha256,
                    record.config_hash,
                    record.summary,
                ),
            )
            conn.executemany(
                "INSERT INTO publication_items (publication_id, item_id, position) VALUES (?, ?, ?)",
                [(record.id, item_id, pos) for pos, item_id in enumerate(item_ids)],
            )

    def live_publications(self) -> list[PublicationRecord]:
        rows = self.conn.execute(
            "SELECT * FROM publications WHERE pruned = 0 ORDER BY created_at DESC, id DESC"
        ).fetchall()
        return [_row_to_publication(r) for r in rows]

    def mark_pruned(self, publication_id: str) -> None:
        with self.transaction() as conn:
            conn.execute("UPDATE publications SET pruned = 1 WHERE id = ?", (publication_id,))

    # --- runs ---------------------------------------------------------------------------------

    def start_run(self, kind: str, now: datetime) -> int:
        with self.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO runs (kind, started_at, status) VALUES (?, ?, 'running')", (kind, utc_iso(now))
            )
            return int(cur.lastrowid)

    def finish_run(self, run_id: int, now: datetime, status: str, detail: str = "") -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE runs SET finished_at = ?, status = ?, detail = ? WHERE id = ?",
                (utc_iso(now), status, detail, run_id),
            )

    def last_run(self, kind: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM runs WHERE kind = ? ORDER BY id DESC LIMIT 1", (kind,)
        ).fetchone()


def _row_to_item(row: sqlite3.Row) -> ContentItem:
    return ContentItem(
        source_id=row["source_id"],
        guid=row["guid"],
        title=row["title"],
        kind=row["kind"],
        url=row["url"],
        canonical_url=row["canonical_url"],
        summary_html=row["summary_html"],
        body_html=row["body_html"],
        published_at=parse_utc(row["published_at"]),
        first_seen_at=parse_utc(row["first_seen_at"]),
        language=row["language"],
        author=row["author"],
        signals=json.loads(row["signals"]),
        tags=json.loads(row["tags"]),
        ai_allowed=bool(row["ai_allowed"]),
    )


def _row_to_publication(row: sqlite3.Row) -> PublicationRecord:
    return PublicationRecord(
        id=row["id"],
        kind=row["kind"],
        title=row["title"],
        author=row["author"],
        created_at=parse_utc(row["created_at"]),
        local_date=row["local_date"],
        filename=row["filename"],
        size=row["size"],
        sha256=row["sha256"],
        config_hash=row["config_hash"],
        summary=row["summary"],
        pruned=bool(row["pruned"]),
    )
