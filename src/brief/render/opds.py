"""OPDS 1.2 acquisition feed that CrossPoint's OPDS browser can read.

CrossPoint (OpdsParser.cpp) treats an entry as a book only for an acquisition link whose type is
exactly "application/epub+zip", and joins a relative href onto the feed URL with a plain "/"
(UrlUtils::buildUrl), so "opds.xml" + "a.epub" would become "opds.xml/a.epub". Every href here is
therefore an absolute path starting with "/".
"""

from __future__ import annotations

import uuid
from datetime import datetime

from brief.db import PublicationRecord, utc_iso
from brief.render.epub import book_uuid
from brief.render.sanitize import xml_attr, xml_text

FEED_PATH = "/opds.xml"
PUBLICATIONS_PATH = "/publications"
_FEED_TYPE = "application/atom+xml;profile=opds-catalog;kind=acquisition"


def build_opds(records: list[PublicationRecord], updated: datetime, catalog_title: str, author: str) -> bytes:
    feed_id = uuid.uuid5(uuid.NAMESPACE_URL, "crosspoint-brief:catalog")
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:dc="http://purl.org/dc/terms/" '
        'xmlns:opds="http://opds-spec.org/2010/catalog">',
        f"<id>urn:uuid:{feed_id}</id>",
        f"<title>{xml_text(catalog_title)}</title>",
        f"<updated>{utc_iso(updated)}</updated>",
        f"<author><name>{xml_text(author)}</name></author>",
        f'<link rel="self" href="{FEED_PATH}" type="{_FEED_TYPE}"/>',
        f'<link rel="start" href="{FEED_PATH}" type="{_FEED_TYPE}"/>',
    ]
    for record in records:
        href = f"{PUBLICATIONS_PATH}/{record.filename}"
        lines += [
            "<entry>",
            f"<title>{xml_text(record.title)}</title>",
            f"<id>urn:uuid:{book_uuid(record.id)}</id>",
            f"<updated>{utc_iso(record.created_at)}</updated>",
            f"<author><name>{xml_text(record.author)}</name></author>",
            "<dc:language>ko</dc:language>",
            f'<summary type="text">{xml_text(record.summary)}</summary>',
            f'<link rel="http://opds-spec.org/acquisition" href={xml_attr(href)} '
            f'type="application/epub+zip" length="{record.size}"/>',
            "</entry>",
        ]
    lines.append("</feed>")
    return ("\n".join(lines) + "\n").encode("utf-8")
