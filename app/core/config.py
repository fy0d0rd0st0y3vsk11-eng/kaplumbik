
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(PROJECT_ROOT / ".env")


def _database_url():
    value = os.getenv("DATABASE_URL", "sqlite:///kaplumbik.db").strip()
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value[len("postgres://"):]
    if value.startswith("postgresql://"):
        return "postgresql+psycopg://" + value[len("postgresql://"):]
    return value


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    secret_key: str = os.getenv("SECRET_KEY", "")
    owner_discord_id: str = os.getenv("OWNER_DISCORD_ID", "")
    owner_totp_secret: str = os.getenv("OWNER_TOTP_SECRET", "").replace(" ", "").upper()

    discord_token: str = os.getenv("DISCORD_TOKEN", "")
    discord_client_id: str = os.getenv("DISCORD_CLIENT_ID", "")
    discord_client_secret: str = os.getenv(
        "DISCORD_CLIENT_SECRET", ""
    )
    discord_redirect_uri: str = os.getenv(
        "DISCORD_REDIRECT_URI",
        "http://127.0.0.1:5000/dashboard/callback",
    )

    database_url: str = _database_url()

    openrouter_api_key: str = os.getenv(
        "OPENROUTER_API_KEY", ""
    )
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "")

    log_level: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
