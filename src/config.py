from __future__ import annotations

import logging
from functools import lru_cache
from ipaddress import ip_address

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    host: str = Field(default="127.0.0.1", alias="AGENTEUM_HOST")
    port: int = Field(default=8765, alias="AGENTEUM_PORT")
    allow_remote: bool = Field(default=False, alias="AGENTEUM_ALLOW_REMOTE")
    request_timeout: float = Field(default=15.0, alias="AGENTEUM_REQUEST_TIMEOUT")
    fetch_timeout: float = Field(default=20.0, alias="AGENTEUM_FETCH_TIMEOUT")
    jina_timeout: float = Field(default=30.0, alias="AGENTEUM_JINA_TIMEOUT")
    tavily_api_key: str | None = Field(default=None, alias="TAVILY_API_KEY")
    exa_api_key: str | None = Field(default=None, alias="EXA_API_KEY")
    jina_api_key: str | None = Field(default=None, alias="JINA_API_KEY")

    def validate_network_binding(self, logger: logging.Logger) -> None:
        if not is_remote_bind_host(self.host):
            return
        if not self.allow_remote:
            raise ValueError(
                "Remote bind hosts require AGENTEUM_ALLOW_REMOTE=true "
                "because v1.0 has no authentication."
            )
        logger.warning(
            "Agenteum Net is listening on a remote bind host with no authentication.",
            extra={"host": self.host, "port": self.port, "security": "no_authentication"},
        )


def is_remote_bind_host(host: str) -> bool:
    normalized = host.strip().lower()
    if normalized in {"localhost", "127.0.0.1", "::1"}:
        return False
    if normalized in {"0.0.0.0", "::", ""}:
        return True
    try:
        return not ip_address(normalized).is_loopback
    except ValueError:
        return True


@lru_cache
def get_settings() -> Settings:
    return Settings()
