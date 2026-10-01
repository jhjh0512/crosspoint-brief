"""URL normalization used to spot the same article coming from several sources."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PREFIXES = ("utm_", "mc_")
_TRACKING_KEYS = {"fbclid", "gclid", "igshid", "ref", "ref_src", "source", "spm"}
_DEFAULT_PORTS = {"http": 80, "https": 443}


def canonical_url(url: str | None) -> str | None:
    """Return a comparison key for a URL, or None if it is not http(s).

    Lowercases scheme/host, drops "www.", default ports, fragments, tracking parameters
    and a trailing slash, and sorts the remaining query parameters.
    """
    if not url:
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS or not parts.hostname:
        return None

    host = parts.hostname.lower()
    if host.startswith("www."):
        host = host[4:]
    try:
        port = parts.port
    except ValueError:
        return None
    netloc = host if port in (None, _DEFAULT_PORTS[scheme]) else f"{host}:{port}"

    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(_TRACKING_PREFIXES) and k.lower() not in _TRACKING_KEYS
    ]
    query.sort()

    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    # http and https point at the same article for comparison purposes.
    return urlunsplit(("https", netloc, path, urlencode(query), ""))
