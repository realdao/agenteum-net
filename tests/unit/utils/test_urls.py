from src.utils.urls import is_jina_first_url


def test_jina_first_domains():
    assert is_jina_first_url("https://x.com/openai/status/1")
    assert is_jina_first_url("https://twitter.com/openai/status/1")
    assert not is_jina_first_url("https://example.com")
