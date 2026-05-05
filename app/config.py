from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["local", "dev", "prod"] = "local"
    app_port: int = 8000
    log_level: str = "INFO"

    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "soma"
    mysql_password: str = ""
    mysql_database: str = "soma_agent"

    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "soma_chunks"

    solar_api_key: str = ""
    solar_llm_model: str = "solar-pro"
    # Upstage embedding은 passage(저장용)와 query(검색용)가 분리됨. 둘 다 4096차원.
    solar_embedding_passage_model: str = "embedding-passage"
    solar_embedding_query_model: str = "embedding-query"

    opensoma_sidecar_url: str = "http://opensoma-sidecar:3000"

    operator_webex_token: str = ""
    webex_sender_salt: str = ""

    sync_notices_cron: str = "*/30 * * * *"
    sync_mentorings_cron: str = "*/30 * * * *"
    sync_webex_cron: str = "0 * * * *"

    calendar_mock_fail_rate: float = 0.0

    @property
    def mysql_url(self) -> str:
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
