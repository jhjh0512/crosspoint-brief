"""Connector contract. A connector type knows HOW to fetch; a SourceConfig says WHAT to fetch."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import httpx

from brief.config import SourceConfig
from brief.db import SourceState
from brief.models import ContentItem


@dataclass
class FetchResult:
    items: list[ContentItem] = field(default_factory=list)
    not_modified: bool = False
    etag: str | None = None
    last_modified: str | None = None


class ConnectorError(RuntimeError):
    """A fetch failed in a way worth reporting on the brief's "발행 정보" page."""


class Connector(Protocol):
    type_name: str

    def fetch(self, source: SourceConfig, state: SourceState, client: httpx.Client) -> FetchResult:
        """Return the source's current items. Raise ConnectorError on failure.

        Implementations should honour state.etag / state.last_modified for conditional GETs
        and must not raise for an empty but valid source.
        """
        ...
