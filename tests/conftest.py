from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from brief.config import Config, FilterConfig, PublishConfig, SourceConfig

FIXTURES = Path(__file__).parent / "fixtures"
# 2026-10-02 06:30 Asia/Seoul
NOW = datetime(2026, 10, 1, 21, 30, tzinfo=UTC)


def make_config(tmp_path: Path, *, sources=None, **publish) -> Config:
    sources = sources or (
        SourceConfig(
            id="news", name="뉴스", connector="fake", url="https://news.example.kr/rss", language="ko"
        ),
        SourceConfig(
            id="blog", name="Blog", connector="fake", url="https://blog.example.com/feed", weight=0.5
        ),
    )
    return Config(
        data_dir=tmp_path / "data",
        publish=PublishConfig(**publish),
        filter=FilterConfig(),
        sources=tuple(sources),
    )


@pytest.fixture
def fixture_bytes():
    return lambda name: (FIXTURES / name).read_bytes()
