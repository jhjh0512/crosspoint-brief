"""Minimal static server for development and device tests. Production uses nginx (deploy/)."""

from __future__ import annotations

import logging
import socket
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

log = logging.getLogger(__name__)


class _Handler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".epub": "application/epub+zip",
        ".xml": "application/atom+xml;profile=opds-catalog;charset=utf-8",
    }

    def end_headers(self):
        if self.path.split("?", 1)[0].endswith(".xml"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def list_directory(self, path):
        self.send_error(404)
        return None

    def log_message(self, format, *args):
        log.info("%s %s", self.address_string(), format % args)


def lan_address() -> str:
    """Best-effort LAN IP for the hint shown at startup (no packet is sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(("10.255.255.255", 1))
            return sock.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def make_server(www_dir: Path, host: str, port: int) -> ThreadingHTTPServer:
    www_dir.mkdir(parents=True, exist_ok=True)
    handler = partial(_Handler, directory=str(www_dir))
    return ThreadingHTTPServer((host, port), handler)


def serve(www_dir: Path, host: str = "0.0.0.0", port: int = 8080) -> None:
    server = make_server(www_dir, host, port)
    shown = lan_address() if host in ("0.0.0.0", "") else host
    log.info(
        "serving %s on http://%s:%d — OPDS catalog: http://%s:%d/opds.xml", www_dir, shown, port, shown, port
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
