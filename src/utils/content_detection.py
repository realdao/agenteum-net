from __future__ import annotations

import re

STRONG_BLOCKED_MARKERS = (
    "access denied",
    "captcha",
    "checking your browser",
    "enable javascript",
    "verify you are human",
    "unusual traffic",
    "bot detection",
    "temporarily blocked",
)

WEAK_BLOCKED_MARKERS = ("cloudflare", "forbidden")

TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def extract_title(html: str) -> str:
    match = TITLE_RE.search(html)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def looks_blocked(html: str, markdown: str | None = None) -> bool:
    markdown_text = markdown or ""
    title = extract_title(html).lower()
    combined = f"{title}\n{html}\n{markdown_text}".lower()
    if any(marker in combined for marker in STRONG_BLOCKED_MARKERS):
        return True
    if any(marker in title for marker in WEAK_BLOCKED_MARKERS) and len(markdown_text) < 500:
        return True
    return False
