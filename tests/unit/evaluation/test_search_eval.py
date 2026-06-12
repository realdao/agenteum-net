import sys
from pathlib import Path

import pytest

import src.evaluation.search_eval as search_eval
from src.evaluation.search_eval import (
    DEFAULT_QUERIES,
    ProviderRun,
    SearchEvaluation,
    _parse_providers,
    build_arg_parser,
    compare_provider_runs,
    empty_parallel_response_from_provider_runs,
    render_markdown_report,
)
from src.schemas import ParallelSearchResponse, SearchResult


def make_result(url: str, source: str = "tavily") -> SearchResult:
    return SearchResult(
        title=url,
        url=url,
        snippet=None,
        published_at=None,
        source=source,
        score=None,
    )


def test_default_queries_stay_under_fifty():
    assert 5 <= len(DEFAULT_QUERIES) < 50


def test_compare_provider_runs_reports_overlap_and_parallel_gain():
    runs = [
        ProviderRun(
            provider="tavily",
            duration_ms=120,
            urls=["https://example.com/a", "https://example.com/shared"],
            error=None,
        ),
        ProviderRun(
            provider="exa",
            duration_ms=80,
            urls=["https://example.com/shared", "https://example.com/b"],
            error=None,
        ),
        ProviderRun(
            provider="duckduckgo",
            duration_ms=70,
            urls=[],
            error="rate_limited",
        ),
    ]
    parallel = ParallelSearchResponse(
        query="mcp",
        results=[
            make_result("https://example.com/a"),
            make_result("https://example.com/shared"),
            make_result("https://example.com/b", source="exa"),
        ],
        sources=["tavily", "exa"],
        errors=[],
    )

    evaluation = compare_provider_runs(
        query="mcp",
        provider_runs=runs,
        parallel_response=parallel,
        parallel_duration_ms=150,
    )

    assert evaluation.query == "mcp"
    assert evaluation.parallel_unique_urls == 3
    assert evaluation.parallel_added_over_best_provider == 1
    assert evaluation.provider_unique_counts == {"tavily": 2, "exa": 2, "duckduckgo": 0}
    assert evaluation.overlap_counts[("exa", "tavily")] == 1
    assert evaluation.failed_providers == ["duckduckgo"]


def test_render_markdown_report_includes_summary_table_and_queries():
    evaluation = SearchEvaluation(
        query="mcp",
        provider_runs=[
            ProviderRun(
                provider="tavily",
                duration_ms=120,
                urls=["https://example.com"],
                error=None,
            )
        ],
        parallel_duration_ms=150,
        parallel_unique_urls=1,
        parallel_sources=["tavily"],
        parallel_added_over_best_provider=0,
        provider_unique_counts={"tavily": 1},
        overlap_counts={},
        failed_providers=[],
    )

    report = render_markdown_report([evaluation])

    assert "# Search Evaluation Report" in report
    assert "| Query | Parallel URLs | Added vs Best Provider | Failed Providers |" in report
    assert "| mcp | 1 | 0 | - |" in report
    assert "## mcp" in report
    assert "tavily" in report


def test_arg_parser_accepts_provider_list_limit_and_output():
    parser = build_arg_parser()

    args = parser.parse_args(
        [
            "--providers",
            "tavily,exa",
            "--limit",
            "8",
            "--output",
            "reports/search-eval.md",
        ]
    )

    assert args.providers == "tavily,exa"
    assert args.limit == 8
    assert args.output == Path("reports/search-eval.md")


def test_parse_providers_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unknown provider"):
        _parse_providers("tavily,unknown")


def test_main_reports_unknown_provider_as_argparse_error(monkeypatch, capsys):
    async def fail_evaluate_search(**kwargs):
        pytest.fail("evaluate_search should not run with invalid providers")

    monkeypatch.setattr(sys, "argv", ["search-eval", "--providers", "unknown", "--limit", "1"])
    monkeypatch.setattr(search_eval, "evaluate_search", fail_evaluate_search)

    with pytest.raises(SystemExit) as exc_info:
        search_eval.main()

    assert exc_info.value.code == 2
    assert "Unknown provider" in capsys.readouterr().err


def test_empty_parallel_response_from_provider_runs_preserves_errors():
    response = empty_parallel_response_from_provider_runs(
        query="mcp",
        provider_runs=[
            ProviderRun(provider="tavily", duration_ms=10, urls=[], error="config_error"),
            ProviderRun(provider="exa", duration_ms=12, urls=[], error="auth_error"),
        ],
    )

    assert response.query == "mcp"
    assert response.results == []
    assert response.sources == []
    assert [error.provider for error in response.errors] == ["tavily", "exa"]
