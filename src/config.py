from functools import lru_cache

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

USER_AGENT = "Mozilla/5.0 B2BEmailResearchBot/1.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    openai_model_fast: str = "gpt-5.4-mini"
    openai_model_strong: str = "gpt-5.4"
    openai_search_model: str = "gpt-4o-mini"
    brave_api_key: str = ""
    brave_country: str = "ES"
    request_timeout: int = 15
    max_pages_per_domain: int = 14
    max_concurrent_requests: int = 5

    @property
    def openai_enabled(self) -> bool:
        return bool(self.openai_api_key.strip())

    @property
    def brave_enabled(self) -> bool:
        return bool(self.brave_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
