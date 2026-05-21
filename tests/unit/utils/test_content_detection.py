from src.utils.content_detection import extract_title, looks_blocked


def test_extract_title_reads_html_title():
    title = extract_title("<html><head><title>Access Denied</title></head></html>")

    assert title == "Access Denied"


def test_blocked_detector_flags_captcha_page():
    assert looks_blocked("<title>Captcha</title>", "Verify you are human")


def test_blocked_detector_avoids_ordinary_cloudflare_article():
    html = "<title>Cloudflare architecture notes</title>"
    markdown = "# Cloudflare architecture notes\n\nA long ordinary article body. " * 80

    assert not looks_blocked(html, markdown)
