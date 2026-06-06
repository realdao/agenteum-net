import logging

import pytest

from src.config import Settings


def test_default_settings_bind_to_loopback():
    settings = Settings()

    assert settings.host == "127.0.0.1"
    assert settings.port == 8765
    assert settings.allow_remote is False
    assert settings.log_level == "INFO"


def test_log_level_can_be_configured():
    settings = Settings(AGENTEUM_LOG_LEVEL="debug")

    assert settings.log_level == "DEBUG"


def test_remote_binding_requires_explicit_flag():
    settings = Settings(AGENTEUM_HOST="0.0.0.0", AGENTEUM_ALLOW_REMOTE=False)

    with pytest.raises(ValueError, match="AGENTEUM_ALLOW_REMOTE=true"):
        settings.validate_network_binding(logging.getLogger("test"))


def test_remote_binding_logs_warning_when_allowed(caplog):
    settings = Settings(AGENTEUM_HOST="0.0.0.0", AGENTEUM_ALLOW_REMOTE=True)

    with caplog.at_level(logging.WARNING):
        settings.validate_network_binding(logging.getLogger("test"))

    assert "no authentication" in caplog.text
