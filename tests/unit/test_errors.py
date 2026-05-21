from src.errors import ErrorType, ProviderError, redact_payload


def test_provider_error_safe_repr_redacts_secrets_and_truncates_payload():
    error = ProviderError(
        error_type=ErrorType.AUTH_ERROR,
        provider="tavily",
        message="bad key",
        http_status=401,
        payload={
            "api_key": "secret-key",
            "nested": {"authorization": "Bearer secret-token"},
            "body": "x" * 600,
        },
    )

    safe = error.safe_repr()

    assert safe["error_type"] == "auth_error"
    assert safe["provider"] == "tavily"
    assert safe["payload"]["api_key"] == "[REDACTED]"
    assert safe["payload"]["nested"]["authorization"] == "[REDACTED]"
    assert safe["payload"]["body"].endswith("[TRUNCATED]")
    assert len(safe["payload"]["body"]) < 530


def test_redact_payload_handles_lists():
    payload = [{"token": "secret"}, {"value": "visible"}]

    assert redact_payload(payload)[0]["token"] == "[REDACTED]"
    assert redact_payload(payload)[1]["value"] == "visible"
