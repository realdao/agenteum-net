from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorType(StrEnum):
    QUOTA_EXHAUSTED = "quota_exhausted"
    RATE_LIMITED = "rate_limited"
    AUTH_ERROR = "auth_error"
    CONFIG_ERROR = "config_error"
    INVALID_REQUEST = "invalid_request"
    INVALID_RESPONSE = "invalid_response"
    TIMEOUT = "timeout"
    NETWORK = "network"
    PROVIDER_5XX = "provider_5xx"
    BLOCKED = "blocked"
    EMPTY_CONTENT = "empty_content"
    UNSUPPORTED_CONTENT = "unsupported_content"
    PROVIDER_ERROR = "provider_error"


SECRET_KEYS = ("api_key", "authorization", "token", "secret", "password")
MAX_PAYLOAD_TEXT = 500


def _is_secret_key(key: str) -> bool:
    key_lower = key.lower()
    return any(secret in key_lower for secret in SECRET_KEYS)


def _truncate(value: str) -> str:
    if len(value) <= MAX_PAYLOAD_TEXT:
        return value
    return f"{value[:MAX_PAYLOAD_TEXT]}[TRUNCATED]"


def redact_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            key: "[REDACTED]" if _is_secret_key(str(key)) else redact_payload(value)
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [redact_payload(item) for item in payload]
    if isinstance(payload, tuple):
        return tuple(redact_payload(item) for item in payload)
    if isinstance(payload, str):
        return _truncate(payload)
    return payload


class ProviderError(Exception):
    def __init__(
        self,
        *,
        error_type: ErrorType,
        provider: str,
        message: str,
        http_status: int | None = None,
        request_id: str | None = None,
        payload: Any = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.provider = provider
        self.message = message
        self.http_status = http_status
        self.request_id = request_id
        self.payload = payload

    def safe_repr(self) -> dict[str, Any]:
        return {
            "error_type": self.error_type.value,
            "provider": self.provider,
            "message": self.message,
            "http_status": self.http_status,
            "request_id": self.request_id,
            "payload": redact_payload(self.payload),
        }
