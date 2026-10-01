"""Common data shapes shared by connectors, the pipeline and the renderers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ContentItem:
    """One normalized piece of content. Every connector emits these; the pipeline only reads these."""

    source_id: str
    guid: str
    title: str
    kind: str = "article"  # article, event, alert, ...
    url: str | None = None
    canonical_url: str | None = None
    summary_html: str = ""  # summary the source already provides
    body_html: str = ""  # full or partial body, when the source provides it
    published_at: datetime | None = None  # UTC
    first_seen_at: datetime | None = None  # UTC, set on first store
    language: str | None = None
    author: str | None = None
    signals: dict[str, float] = field(default_factory=dict)  # points, comments, ...
    tags: list[str] = field(default_factory=list)
    ai_allowed: bool = True

    @property
    def id(self) -> str:
        return item_id(self.source_id, self.guid)

    @property
    def content_hash(self) -> str:
        blob = "\x1f".join([self.title, self.summary_html, self.body_html]).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    @property
    def sort_time(self) -> datetime | None:
        return self.published_at or self.first_seen_at


def item_id(source_id: str, guid: str) -> str:
    return hashlib.sha1(f"{source_id}\x1f{guid}".encode()).hexdigest()[:16]


@dataclass
class Article:
    """A chosen item as it appears in a publication."""

    item: ContentItem
    source_name: str
    summary_html: str  # sanitized XHTML fragment
    summary_kind: str  # "feed", "excerpt", "none"


@dataclass
class Section:
    title: str
    articles: list[Article]


@dataclass
class SourceStatus:
    source_id: str
    name: str
    ok: bool
    new_items: int = 0
    detail: str = ""


@dataclass
class Publication:
    id: str
    title: str
    author: str
    created_at: datetime  # UTC
    local_date: str  # YYYY-MM-DD in the publish timezone
    sections: list[Section]
    skim: list[Article]
    sources: list[SourceStatus]
    notes: list[str]  # stages that ran as rule-based fallbacks, warnings, ...
    config_hash: str
    timezone: str = "Asia/Seoul"  # zone used for every time shown in the book
    language: str = "ko"

    @property
    def articles(self) -> list[Article]:
        return [a for s in self.sections for a in s.articles]
