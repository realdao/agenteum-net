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
SHORT_MARKDOWN_LENGTH = 500


def extract_title(html: str) -> str:
    match = TITLE_RE.search(html)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def looks_blocked(html: str, markdown: str | None = None) -> bool:
    markdown_text = markdown or ""
    title = extract_title(html).lower()
    short_markdown = (
        markdown_text.lower() if markdown and len(markdown_text) < SHORT_MARKDOWN_LENGTH else ""
    )
    if any(marker in title for marker in STRONG_BLOCKED_MARKERS):
        return True
    if short_markdown and any(marker in short_markdown for marker in STRONG_BLOCKED_MARKERS):
        return True
    return bool(short_markdown) and any(marker in title for marker in WEAK_BLOCKED_MARKERS)
