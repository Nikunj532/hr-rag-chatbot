from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings

# backend/core/config.py → parent = backend/ → parent = project root
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE  = ROOT_DIR / ".env"


class Settings(BaseSettings):
    # Groq
    groq_api_key: str

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5435
    postgres_db: str = "hr_chatbot"
    postgres_user: str = "postgres"
    postgres_password: str

    # ChromaDB
    chroma_persist_dir: str = "./chroma_store"

    # Gmail SMTP
    gmail_sender: str
    gmail_app_password: str
    gmail_notify_recipient: str

    # App
    backend_url: str = "http://localhost:8000"
    conversation_summary_threshold: int = 200

    @property
    def postgres_dsn(self) -> str:
        user = quote_plus(self.postgres_user)
        password = quote_plus(self.postgres_password)
        return (
            f"postgresql://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def postgres_async_dsn(self) -> str:
        user = quote_plus(self.postgres_user)
        password = quote_plus(self.postgres_password)
        return (
            f"postgresql+asyncpg://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    model_config = {
        "env_file": str(ENV_FILE),
        "env_file_encoding": "utf-8",
        "extra": "ignore",           # ← ignore any extra keys in .env
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()