from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    registry_mode: str = "mock"
    registry_api_base_url: str = "https://crm-med-mock.dbi-testing.ru/api/v1"
    registry_api_token: str = "test-token"
    app_db_path: str = "data/app.sqlite3"
    schedule_path: str = "docs_tz/raspisanie_vrachey.xlsx"
    regulation_path: str = "docs_tz/registrature_reglament.docx"
    team_id: str = "local-team"
    llm_mode: str = "fallback"
    llm_base_url: str = "http://127.0.0.1:8080/v1"
    llm_model: str = "alissa-ai-f-q3_k_m"
    llm_timeout_seconds: float = 8.0
    asr_mode: str = "stub"
    tts_mode: str = "stub"
    voice_language: str = "ru"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
