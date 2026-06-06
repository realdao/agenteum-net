import logging

from src.app import configure_logging
from src.config import Settings


def test_configure_logging_uses_settings_log_level(monkeypatch):
    captured = {}

    def fake_basic_config(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(logging, "basicConfig", fake_basic_config)

    configure_logging(Settings(AGENTEUM_LOG_LEVEL="debug"))

    assert captured["level"] == logging.DEBUG
