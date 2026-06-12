from __future__ import annotations

from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator

ProviderName = Literal["tavily", "exa", "duckduckgo", "http", "jina"]
SearchProviderName = Literal["tavily", "exa", "duckduckgo"]
FetchProviderName = Literal["http", "jina"]
FetchStatus = Literal["ok", "error"]
TimeRange = Literal["day", "week", "month", "year", "d", "w", "m", "y"]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    max_result: int = Field(default=10, ge=1, le=20)
    time_range: TimeRange | None = None
    topic: str | None = None

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("query must not be blank")
        return stripped


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str | None = None
    published_at: str | None = None
    source: SearchProviderName
    score: float | None = None


class FallbackRecord(BaseModel):
    from_provider: SearchProviderName = Field(alias="from")
    to_provider: SearchProviderName = Field(alias="to")
    reason: str

    model_config = ConfigDict(populate_by_name=True)


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    source: SearchProviderName
    fallbacks: list[FallbackRecord] = Field(default_factory=list)


class SearchProviderError(BaseModel):
    provider: SearchProviderName
    type: str
    message: str
    http_status: int | None = None
    request_id: str | None = None


class ParallelSearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    sources: list[SearchProviderName]
    errors: list[SearchProviderError] = Field(default_factory=list)


class FetchError(BaseModel):
    type: str
    message: str
    provider: FetchProviderName
    http_status: int | None = None


class FetchResult(BaseModel):
    url: str
    final_url: str | None = None
    content: str | None = None
    source: FetchProviderName
    status: FetchStatus
    error: FetchError | None = None


class FetchRequest(BaseModel):
    urls: list[AnyHttpUrl] = Field(min_length=1, max_length=10)

    def normalized_urls(self) -> list[str]:
        return [str(url) for url in self.urls]


class FetchResponse(BaseModel):
    results: list[FetchResult]
