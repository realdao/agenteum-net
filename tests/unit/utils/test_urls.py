from src.utils.urls import is_http_url, is_jina_first_url


def test_http_url_validation():
    assert is_http_url("https://example.com")
    assert not is_http_url("file:///tmp/a.html")


def test_jina_first_domains():
    assert is_jina_first_url("https://x.com/openai/status/1")
    assert is_jina_first_url("https://twitter.com/openai/status/1")
    assert not is_jina_first_url("https://example.com")
