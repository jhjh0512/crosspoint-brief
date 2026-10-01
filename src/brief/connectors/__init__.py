"""Connector registry. Adding a connector type = one class + one line here."""

from __future__ import annotations

from brief.connectors.base import Connector, ConnectorError, FetchResult
from brief.connectors.rss import RssConnector

_REGISTRY: dict[str, Connector] = {
    RssConnector.type_name: RssConnector(),
}


def get_connector(type_name: str) -> Connector:
    try:
        return _REGISTRY[type_name]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY))
        raise ConnectorError(f"unknown connector type {type_name!r} (known: {known})") from None


def register(connector: Connector) -> None:
    _REGISTRY[connector.type_name] = connector


__all__ = ["Connector", "ConnectorError", "FetchResult", "get_connector", "register"]
