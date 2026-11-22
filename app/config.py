from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: str = "gemini"
    llm_model: str = "gemini-3.5-flash-lite"
    fallback_provider: str = "gemini"
    fallback_model: str = "gemini-3.1-flash-lite"

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""

    llm_timeout_s: float = 60
    fetch_timeout_s: float = 10
    max_page_bytes: int = 2_000_000
    max_content_chars: int = 12_000  # ~3k tokens of cleaned text
    cache_ttl_s: int = 3600


@lru_cache
def get_settings() -> Settings:
    return Settings()
