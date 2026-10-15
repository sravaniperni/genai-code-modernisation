"""Runtime configuration.

Every setting is read from environment variables carrying the ``MODERNISATION_`` prefix. The prefix is
deliberate: the platform must never pick up ambient credentials such as a CI runner's ``GITHUB_TOKEN``
or an unrelated ``OPENAI_API_KEY`` by accident.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MODERNISATION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- persistence -------------------------------------------------------------------------------
    database_url: str = "postgresql+psycopg://modernisation:modernisation-dev@127.0.0.1:5432/modernisation"
    data_dir: Path = Path(".data")

    # --- API -----------------------------------------------------------------------------------------
    api_cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    api_token: SecretStr | None = None  # when set, mutating endpoints require "Authorization: Bearer <token>"

    # --- repositories ------------------------------------------------------------------------------
    # Local filesystem roots that may be registered as repositories. Anything else is refused.
    allowed_local_roots: list[Path] = Field(default_factory=list)
    # GitHub owners whose repositories may be registered ("owner" or "owner/repo").
    allowed_github_repositories: list[str] = Field(default_factory=list)

    # --- model inference ---------------------------------------------------------------------------
    model_provider: Literal["openai_compatible", "anthropic", "none"] = "none"
    model_base_url: str | None = None
    model_name: str | None = None
    model_api_key: SecretStr | None = None
    model_timeout_s: float = 600.0
    model_max_retries: int = 2
    model_max_output_tokens: int = 2048
    model_temperature: float = 0.0
    model_context_tokens: int = 16384
    # How structured (JSON) output is requested from an OpenAI-compatible server:
    #   json_schema        OpenAI-style {"type": "json_schema", "json_schema": {...}}
    #   json_object_schema llama.cpp-style {"type": "json_object", "schema": {...}} (grammar constrained)
    #   prompt_only        schema in the prompt only; output validated and repaired client-side
    model_structured_output: Literal["json_schema", "json_object_schema", "prompt_only"] = "json_schema"
    # USD per million tokens; when unset, cost is recorded as unknown rather than zero.
    model_price_input_per_mtok: float | None = None
    model_price_output_per_mtok: float | None = None

    # --- GitHub ------------------------------------------------------------------------------------
    github_api_url: str = "https://api.github.com"
    github_token: SecretStr | None = None
    github_webhook_secret: SecretStr | None = None
    github_timeout_s: float = 30.0
    # Identity recorded on commits the platform creates for publication. Set these to an identity you are
    # authorised to use; the defaults clearly mark commits as platform-generated.
    git_author_name: str = "Modernisation Platform"
    git_author_email: str = "modernisation-platform@users.noreply.localhost"

    # --- execution sandbox -------------------------------------------------------------------------
    sandbox_backend: Literal["bubblewrap", "unsandboxed"] = "bubblewrap"
    # Host uid/gid the sandboxed processes run as. Must not be root.
    sandbox_uid: int = 9100
    sandbox_gid: int = 9100
    sandbox_python: str = "/usr/bin/python3.12"
    sandbox_command_timeout_s: float = 300.0
    sandbox_memory_mb: int = 2048
    sandbox_max_processes: int = 256
    sandbox_max_file_mb: int = 256
    sandbox_output_limit_kb: int = 256
    wheelhouse_dir: Path | None = None  # offline package mirror mounted read-only into the sandbox

    # --- workflow ----------------------------------------------------------------------------------
    worker_lease_s: float = 120.0
    worker_heartbeat_s: float = 15.0
    worker_poll_s: float = 1.0
    default_max_attempts: int = 3
    require_plan_approval: bool = False
    workspace_retention: Literal["keep", "delete"] = "delete"

    # --- observability -----------------------------------------------------------------------------
    log_level: str = "INFO"
    otel_exporter: Literal["none", "console", "jsonl"] = "none"

    @property
    def repos_dir(self) -> Path:
        return self.data_dir / "repos"

    @property
    def workspaces_dir(self) -> Path:
        return self.data_dir / "workspaces"

    @property
    def envs_dir(self) -> Path:
        return self.data_dir / "envs"

    def secret_values(self) -> list[str]:
        """Return configured secret values so the log redactor can mask them verbatim."""
        out: list[str] = []
        for secret in (self.model_api_key, self.github_token, self.github_webhook_secret, self.api_token):
            if secret is not None and secret.get_secret_value():
                out.append(secret.get_secret_value())
        return out


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
