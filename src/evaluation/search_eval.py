from __future__ import annotations

import argparse
import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx

from src.config import Settings, get_settings
from src.errors import ProviderError
from src.providers.search.duckduckgo import DuckDuckGoSearchProvider
from src.providers.search.exa import ExaSearchProvider
from src.providers.search.tavily import TavilySearchProvider
from src.schemas import ParallelSearchResponse, SearchProviderError, SearchRequest
from src.services.search_service import SearchService

DEFAULT_QUERIES = [
    "Model Context Protocol server tutorial",
    "Python async httpx retry best practices",
    "OpenAI GPT-5 API release notes",
    "latest Tavily search API pricing",
    "Exa neural search examples",
    "DuckDuckGo search Python package ddgs",
    "FastAPI streamable HTTP MCP server",
    "Windows NSSM Python service install",
    "China AI regulation 2026 summary",
    "arXiv retrieval augmented generation evaluation",
    "GitHub Actions uv Python cache",
    "web search provider comparison Tavily Exa DuckDuckGo",
]

DEFAULT_PROVIDERS = ["tavily", "exa", "duckduckgo"]


@dataclass(frozen=True)
class ProviderRun:
    provider: str
    duration_ms: int
    urls: list[str]
    error: str | None


@dataclass(frozen=True)
class SearchEvaluation:
    query: str
    provider_runs: list[ProviderRun]
    parallel_duration_ms: int
    parallel_unique_urls: int
    parallel_sources: list[str]
    parallel_added_over_best_provider: int
    provider_unique_counts: dict[str, int]
    overlap_counts: dict[tuple[str, str], int]
    failed_providers: list[str]


def compare_provider_runs(
    *,
    query: str,
    provider_runs: list[ProviderRun],
    parallel_response: ParallelSearchResponse,
    parallel_duration_ms: int,
) -> SearchEvaluation:
    provider_url_sets = {
        run.provider: {_normalize_url(url) for url in run.urls}
        for run in provider_runs
    }
    provider_unique_counts = {
        provider: len(urls)
        for provider, urls in provider_url_sets.items()
    }
    overlap_counts: dict[tuple[str, str], int] = {}
    provider_names = sorted(provider_url_sets)
    for left_index, left_provider in enumerate(provider_names):
        for right_provider in provider_names[left_index + 1 :]:
            overlap_counts[(left_provider, right_provider)] = len(
                provider_url_sets[left_provider] & provider_url_sets[right_provider]
            )

    parallel_urls = {
        _normalize_url(result.url)
        for result in parallel_response.results
    }
    best_provider_count = max(provider_unique_counts.values(), default=0)

    return SearchEvaluation(
        query=query,
        provider_runs=provider_runs,
        parallel_duration_ms=parallel_duration_ms,
        parallel_unique_urls=len(parallel_urls),
        parallel_sources=list(parallel_response.sources),
        parallel_added_over_best_provider=max(0, len(parallel_urls) - best_provider_count),
        provider_unique_counts=provider_unique_counts,
        overlap_counts=overlap_counts,
        failed_providers=[run.provider for run in provider_runs if run.error],
    )


def empty_parallel_response_from_provider_runs(
    *,
    query: str,
    provider_runs: list[ProviderRun],
) -> ParallelSearchResponse:
    return ParallelSearchResponse(
        query=query,
        results=[],
        sources=[],
        errors=[
            SearchProviderError(
                provider=run.provider,
                type=run.error,
                message=f"{run.provider} failed with {run.error}.",
            )
            for run in provider_runs
            if run.error is not None
        ],
    )


def render_markdown_report(evaluations: list[SearchEvaluation]) -> str:
    lines = [
        "# Search Evaluation Report",
        "",
        f"Total queries: {len(evaluations)}",
        "",
        "| Query | Parallel URLs | Added vs Best Provider | Failed Providers |",
        "| --- | ---: | ---: | --- |",
    ]
    for evaluation in evaluations:
        failed = ", ".join(evaluation.failed_providers) or "-"
        lines.append(
            f"| {evaluation.query} | {evaluation.parallel_unique_urls} | "
            f"{evaluation.parallel_added_over_best_provider} | {failed} |"
        )

    for evaluation in evaluations:
        lines.extend(
            [
                "",
                f"## {evaluation.query}",
                "",
                "| Provider | URLs | Duration ms | Error |",
                "| --- | ---: | ---: | --- |",
            ]
        )
        for run in evaluation.provider_runs:
            lines.append(
                f"| {run.provider} | {len(run.urls)} | {run.duration_ms} | {run.error or '-'} |"
            )
        lines.extend(
            [
                "",
                f"Parallel duration ms: {evaluation.parallel_duration_ms}",
                f"Parallel sources: {', '.join(evaluation.parallel_sources) or '-'}",
                "",
                "| Provider Pair | URL Overlap |",
                "| --- | ---: |",
            ]
        )
        if evaluation.overlap_counts:
            for pair, count in sorted(evaluation.overlap_counts.items()):
                lines.append(f"| {' / '.join(pair)} | {count} |")
        else:
            lines.append("| - | 0 |")

    return "\n".join(lines) + "\n"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate search provider result differences.")
    parser.add_argument(
        "--providers",
        default=",".join(DEFAULT_PROVIDERS),
        help="Comma-separated provider names. Defaults to all search providers.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=len(DEFAULT_QUERIES),
        help="Number of built-in queries to run. Must be less than 50.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional Markdown report output path. Prints to stdout when omitted.",
    )
    return parser


async def evaluate_search(
    *,
    queries: Sequence[str],
    providers: list[str],
    settings: Settings,
) -> list[SearchEvaluation]:
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        service = SearchService(
            [
                TavilySearchProvider(api_key=settings.tavily_api_key, client=client),
                ExaSearchProvider(api_key=settings.exa_api_key, client=client),
                DuckDuckGoSearchProvider(),
            ]
        )
        evaluations: list[SearchEvaluation] = []
        for query in queries:
            request = SearchRequest(query=query)
            provider_runs = await asyncio.gather(
                *(_run_single_provider(service, request, provider) for provider in providers)
            )
            start = time.perf_counter()
            try:
                parallel_response = await service.parallel_search(request, provider_names=providers)
            except ProviderError:
                parallel_response = empty_parallel_response_from_provider_runs(
                    query=query,
                    provider_runs=list(provider_runs),
                )
            parallel_duration_ms = _elapsed_ms(start)
            evaluations.append(
                compare_provider_runs(
                    query=query,
                    provider_runs=list(provider_runs),
                    parallel_response=parallel_response,
                    parallel_duration_ms=parallel_duration_ms,
                )
            )
    return evaluations


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    providers = _parse_providers(args.providers)
    queries = _limited_queries(args.limit)
    report = render_markdown_report(
        asyncio.run(evaluate_search(queries=queries, providers=providers, settings=get_settings()))
    )
    if args.output is None:
        print(report)
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"Wrote search evaluation report to {args.output}")


async def _run_single_provider(
    service: SearchService,
    request: SearchRequest,
    provider_name: str,
) -> ProviderRun:
    start = time.perf_counter()
    try:
        response = await service.parallel_search(request, provider_names=[provider_name])
    except ProviderError as exc:
        return ProviderRun(
            provider=provider_name,
            duration_ms=_elapsed_ms(start),
            urls=[],
            error=exc.error_type.value,
        )
    return ProviderRun(
        provider=provider_name,
        duration_ms=_elapsed_ms(start),
        urls=[result.url for result in response.results],
        error=None,
    )


def _parse_providers(value: str) -> list[str]:
    providers = [provider.strip() for provider in value.split(",") if provider.strip()]
    return providers or DEFAULT_PROVIDERS


def _limited_queries(limit: int) -> list[str]:
    if limit < 1 or limit >= 50:
        raise ValueError("--limit must be between 1 and 49")
    return DEFAULT_QUERIES[:limit]


def _elapsed_ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


def _normalize_url(url: str) -> str:
    return url.rstrip("/")


if __name__ == "__main__":
    main()
