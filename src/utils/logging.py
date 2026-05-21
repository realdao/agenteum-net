from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

from src.errors import ProviderError


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


@contextmanager
def provider_latency_log(
    logger: logging.Logger,
    *,
    provider: str,
    operation: str,
) -> Iterator[None]:
    started = time.perf_counter()
    try:
        yield
    except ProviderError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "provider call failed",
            extra={
                "provider": provider,
                "operation": operation,
                "latency_ms": latency_ms,
                "status": "error",
                "error_type": exc.error_type.value,
                "http_status": exc.http_status,
                "provider_error": exc.safe_repr(),
            },
        )
        raise
    else:
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "provider call succeeded",
            extra={
                "provider": provider,
                "operation": operation,
                "latency_ms": latency_ms,
                "status": "ok",
            },
        )
