from __future__ import annotations

from io import BytesIO
from typing import Any

from markitdown import MarkItDown


class MarkdownConverter:
    def __init__(self, markitdown: Any | None = None) -> None:
        self._markitdown = markitdown or MarkItDown()

    def html_to_markdown(self, html: str, url: str | None = None) -> str:
        stream = BytesIO(html.encode("utf-8"))
        result = self._markitdown.convert_stream(stream, file_extension=".html", url=url)
        return str(result.text_content).strip()
