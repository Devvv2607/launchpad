"""Application settings. Everything configurable comes from the environment.

Model names deliberately have NO defaults: a missing/retired model must fail loudly
at the call site with a clear message, never silently fall back to something else.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

LLMProvider = Literal["groq", "gemini", "openai", "anthropic"]
EmbeddingProvider = Literal["gemini", "openai"]
ImageProvider = Literal["gemini", "openai", "replicate"]
StorageBackend = Literal["s3", "local"]
AuthProvider = Literal["local", "supabase"]


class Settings(BaseSettings):
    # Repo-root .env (docker-compose/Makefile) and api/.env both work; the latter wins.
    # Empty values (e.g. `LLM_PROVIDER=` straight from .env.example) mean "unset", not "".
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    # --- App ---
    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    log_json: bool = False
    api_public_url: str = "http://localhost:8000"
    web_public_url: str = "http://localhost:3000"
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    max_request_bytes: int = 10 * 1024 * 1024

    # --- Database / queue ---
    database_url: str = "postgresql+asyncpg://launchpad:launchpad@localhost:5432/launchpad"
    redis_url: str = "redis://localhost:6379/0"

    # --- Auth ---
    auth_provider: AuthProvider = "local"
    jwt_secret: SecretStr = SecretStr("")
    jwt_ttl_minutes: int = 60 * 24 * 7
    supabase_url: str | None = None
    supabase_jwt_audience: str = "authenticated"

    # --- Encryption of third-party tokens at rest (comma-separated Fernet keys; first encrypts) ---
    token_encryption_keys: SecretStr = SecretStr("")

    # --- LLM ---
    # Defaults for every purpose; workspaces may override per purpose in Settings → AI.
    llm_provider: LLMProvider | None = None
    llm_model: str | None = None  # writing + planning
    llm_fast_model: str | None = None  # critique, hashtags, extraction (falls back to llm_model)
    llm_temperature: float = 0.7
    groq_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    llm_max_retries: int = 3
    log_llm_payloads: bool = False  # store prompts/outputs on llm_calls (off by default)
    daily_spend_cap_usd: float = 2.00  # per workspace; overridable in workspace settings
    agent_run_token_budget: int = 200_000
    agent_run_cost_budget_usd: float = 1.00

    # --- Embeddings (RAG) ---
    embedding_provider: EmbeddingProvider | None = None
    embedding_model: str | None = None
    # Must match the pgvector column (migration); changing it requires a migration + re-index.
    embedding_dim: int = 768

    # --- Images ---
    image_provider: ImageProvider | None = None
    image_model: str | None = None
    replicate_api_token: SecretStr | None = None

    # --- Research ---
    tavily_api_key: SecretStr | None = None

    # --- Storage ---
    storage_backend: StorageBackend = "local"
    storage_local_dir: str = ".storage"
    s3_endpoint_url: str | None = None
    s3_public_base_url: str | None = None
    s3_bucket: str = "launchpad"
    s3_region: str = "auto"
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None

    # --- Email ---
    resend_api_key: SecretStr | None = None
    email_from: str | None = None

    # --- Social OAuth ---
    meta_app_id: str | None = None
    meta_app_secret: SecretStr | None = None
    linkedin_client_id: str | None = None
    linkedin_client_secret: SecretStr | None = None

    # --- Observability ---
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str) and not v.startswith("["):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    def require_jwt_secret(self) -> str:
        secret = self.jwt_secret.get_secret_value()
        if len(secret) < 32:
            raise RuntimeError("JWT_SECRET must be set to at least 32 characters.")
        return secret


@lru_cache
def get_settings() -> Settings:
    return Settings()
