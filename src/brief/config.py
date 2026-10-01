"""Settings loaded from a TOML file (P0-1). P0-3 moves them into the web admin page."""

from __future__ import annotations

import hashlib
import json
import os
import tomllib
from dataclasses import asdict, dataclass, field
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class SourceConfig:
    id: str
    name: str
    connector: str
    url: str
    weight: float = 1.0
    max_per_day: int = 20
    language: str | None = None
    ai_allowed: bool = True
    enabled: bool = True


@dataclass(frozen=True)
class PublishConfig:
    time: str = "06:30"
    retry_time: str = "07:00"
    timezone: str = "Asia/Seoul"
    slug: str = "am"
    title: str = "아침 브리핑"
    author: str = "CrossPoint Brief"
    article_count: int = 12
    skim_count: int = 30
    window_hours: int = 24
    summary_max_chars: int = 600
    keep_publications: int = 14

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def publish_time(self) -> time:
        return _parse_hhmm(self.time, "publish.time")

    @property
    def retry_at(self) -> time:
        return _parse_hhmm(self.retry_time, "publish.retry_time")


@dataclass(frozen=True)
class CollectConfig:
    interval_minutes: int = 60
    timeout_seconds: float = 20.0
    user_agent: str = "crosspoint-brief/0.1"


@dataclass(frozen=True)
class FilterConfig:
    exclude_keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class Config:
    data_dir: Path
    publish: PublishConfig = field(default_factory=PublishConfig)
    collect: CollectConfig = field(default_factory=CollectConfig)
    filter: FilterConfig = field(default_factory=FilterConfig)
    sources: tuple[SourceConfig, ...] = ()

    @property
    def db_path(self) -> Path:
        return self.data_dir / "brief.db"

    @property
    def www_dir(self) -> Path:
        """Web root served to the reader: opds.xml + publications/."""
        return self.data_dir / "www"

    @property
    def publications_dir(self) -> Path:
        return self.www_dir / "publications"

    def source(self, source_id: str) -> SourceConfig | None:
        return next((s for s in self.sources if s.id == source_id), None)

    def fingerprint(self) -> str:
        """Short hash recorded with each publication, so a brief can be traced to its settings."""
        payload = {
            "publish": asdict(self.publish),
            "filter": asdict(self.filter),
            "sources": [asdict(s) for s in self.sources],
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()[:12]


def _parse_hhmm(value: str, key: str) -> time:
    try:
        hour, minute = value.split(":")
        return time(int(hour), int(minute))
    except ValueError as exc:
        raise ConfigError(f"{key} must be HH:MM, got {value!r}") from exc


def _section(raw: dict, name: str, cls):
    data = raw.get(name, {})
    if not isinstance(data, dict):
        raise ConfigError(f"[{name}] must be a table")
    known = set(cls.__dataclass_fields__)
    unknown = set(data) - known
    if unknown:
        raise ConfigError(f"[{name}] has unknown keys: {', '.join(sorted(unknown))}")
    return cls(**data)


def load_config(path: str | os.PathLike) -> Config:
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    with path.open("rb") as fh:
        raw = tomllib.load(fh)

    data_dir_env = os.environ.get("BRIEF_DATA_DIR")
    data_dir = Path(data_dir_env) if data_dir_env else Path(raw.get("paths", {}).get("data_dir", "data"))
    if not data_dir.is_absolute():
        data_dir = (path.parent / data_dir).resolve()

    publish = _section(raw, "publish", PublishConfig)
    try:
        ZoneInfo(publish.timezone)
    except Exception as exc:  # ZoneInfoNotFoundError or a malformed key
        raise ConfigError(f"unknown publish.timezone {publish.timezone!r}") from exc
    _parse_hhmm(publish.time, "publish.time")
    _parse_hhmm(publish.retry_time, "publish.retry_time")

    collect = _section(raw, "collect", CollectConfig)
    filter_raw = raw.get("filter", {})
    filt = FilterConfig(exclude_keywords=tuple(k for k in filter_raw.get("exclude_keywords", []) if k))

    sources = []
    seen = set()
    for entry in raw.get("sources", []):
        try:
            source = SourceConfig(**entry)
        except TypeError as exc:
            raise ConfigError(f"invalid [[sources]] entry {entry.get('id')!r}: {exc}") from exc
        if source.id in seen:
            raise ConfigError(f"duplicate source id {source.id!r}")
        seen.add(source.id)
        sources.append(source)

    return Config(data_dir=data_dir, publish=publish, collect=collect, filter=filt, sources=tuple(sources))
