from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # GitHub
    github_token: str = ""
    github_graphql_url: str = "https://api.github.com/graphql"
    github_rest_url: str = "https://api.github.com"

    # Anthropic / LLM
    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-4-6"
    llm_max_tokens: int = 8000
    llm_enable_thinking: bool = True

    # Database
    database_url: str = "sqlite+aiosqlite:///./insights.db"

    # API
    cors_origins: list[str] = ["http://localhost:8000", "http://localhost:3000"]
    rate_limit_per_minute: int = 10

    # Logging
    log_level: str = "INFO"
    log_json: bool = False

    # App
    app_version: str = "0.1.0"
    debug: bool = False

    @field_validator("github_token", "anthropic_api_key", mode="before")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v


@lru_cache
def get_settings() -> Settings:
    return Settings()
