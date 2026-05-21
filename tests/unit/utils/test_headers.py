from src.utils.headers import get_fetch_headers


def test_fetch_headers_include_required_values():
    headers = get_fetch_headers()

    assert "Mozilla/5.0" in headers["User-Agent"]
    assert "text/html" in headers["Accept"]
    assert headers["Accept-Language"].startswith("zh-CN")
