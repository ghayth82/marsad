"""إعدادات الخادم. كل قيمة تأتي من متغيرات البيئة (أو .env)، ولا سر مكتوب في الكود."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MARSAD_", env_file=".env", extra="ignore")

    # فارغ = قاعدة SQLite داخل مجلد البيانات (للتطوير والاختبار فقط).
    # المُثبِّت يمرّر عنوان PostgreSQL المضمَّن، والخادم يمرّر عنوان الحاوية.
    database_url: str = ""
    secret_key: str = ""

    # desktop | portable | server
    mode: str = "desktop"
    session_hours: int = 12
    cookie_secure: bool = False  # True خلف HTTPS على الخادم

    max_failed_logins: int = 5
    lockout_minutes: int = 15


@lru_cache
def get_settings() -> Settings:
    return Settings()
