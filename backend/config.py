import os
import sys
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    secret_key: str = ""
    default_admin_password: str = "admin"
    db_path: str = "/data/lanlens.db"
    access_token_expire_minutes: int = 480  # 8 hours
    refresh_token_expire_days: int = 7
    algorithm: str = "HS256"
    tz: str = "UTC"

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
