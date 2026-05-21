from __future__ import annotations

from importlib.resources import files

RESOURCE_URIS = {
    "agenteum://tools/search-guide": "search-guide.md",
    "agenteum://tools/fetch-guide": "fetch-guide.md",
    "agenteum://providers/capabilities": "providers-capabilities.md",
}


def load_resource_text(filename: str) -> str:
    return files("src.resources").joinpath(filename).read_text(encoding="utf-8")


def resource_text_by_uri(uri: str) -> str:
    return load_resource_text(RESOURCE_URIS[uri])
