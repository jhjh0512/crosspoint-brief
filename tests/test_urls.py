import pytest

from brief.urls import canonical_url


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("https://www.Example.com/post/", "http://example.com/post"),
        ("https://example.com/p?utm_source=x&id=3&fbclid=y", "https://example.com/p?id=3"),
        ("https://example.com:443/p#section", "https://example.com/p"),
        ("https://example.com/p?b=2&a=1", "https://example.com/p?a=1&b=2"),
    ],
)
def test_equivalent_urls_share_a_key(a, b):
    assert canonical_url(a) == canonical_url(b)


def test_different_paths_differ():
    assert canonical_url("https://example.com/a") != canonical_url("https://example.com/b")


@pytest.mark.parametrize("url", [None, "", "mailto:x@example.com", "javascript:alert(1)", "not a url"])
def test_non_http_urls_have_no_key(url):
    assert canonical_url(url) is None


def test_non_default_port_is_kept():
    assert canonical_url("http://nas.local:8080/x") == "https://nas.local:8080/x"
