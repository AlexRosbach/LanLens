import os
import sys
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    secret_key: str = ""
    default_admin_password: str = "admin"
    db_path: str = "/data/lanlens.db"
    access_token_expire_minutes: int = 480  # 8 hours
    refresh_token_expire_days: int = 7
    algorithm: str = "HS256"
    tz: str = "UTC"
    api_token: str = Field(
        default="",
        validation_alias=AliasChoices("LANLENS_API_TOKEN", "API_TOKEN"),
    )
    api_token_read_only: bool = Field(
        default=True,
        validation_alias=AliasChoices("LANLENS_API_TOKEN_READ_ONLY", "API_TOKEN_READ_ONLY"),
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

_PLACEHOLDER_KEYS = {"", "change-this", "CHANGE_THIS_TO_A_LONG_RANDOM_STRING"}

if settings.secret_key in _PLACEHOLDER_KEYS or len(settings.secret_key) < 32:
    print(
        "ERROR: SECRET_KEY is not set, too short, or still uses a placeholder value.\n"
        "Please set a SECRET_KEY of at least 32 characters before starting LanLens.\n"
        "Generate one with:\n"
        "  python3 -c \"import secrets; print(secrets.token_hex(32))\"",
        file=sys.stderr,
    )
    sys.exit(1)

if settings.api_token and len(settings.api_token) < 32:
    print(
        "ERROR: LANLENS_API_TOKEN must be at least 32 characters when configured.\n"
        "Generate one with:\n"
        "  python3 -c \"import secrets; print(secrets.token_urlsafe(32))\"",
        file=sys.stderr,
    )
    sys.exit(1)
