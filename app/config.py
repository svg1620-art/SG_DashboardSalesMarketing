"""Конфигурация DashboardSales&Marketing из переменных окружения."""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # dotenv не обязателен в проде (Railway передаёт переменные напрямую)
    pass


def _normalize_db_url(url: str | None) -> str | None:
    """Railway/Heroku иногда отдают postgres:// — psycopg2 ждёт postgresql://."""
    if url and url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-key-change-me")
    DATABASE_URL = _normalize_db_url(os.environ.get("DATABASE_URL"))

    AMOCRM_SUBDOMAIN = os.environ.get("AMOCRM_SUBDOMAIN", "")
    AMOCRM_TOKEN = os.environ.get("AMOCRM_TOKEN", "")
    # Целевая воронка (по умолчанию «Воронка1»); переопределяется переменной
    AMOCRM_PIPELINE_ID = int(os.environ.get("AMOCRM_PIPELINE_ID", "3807"))
    # Год, с которого тянем историю при первичном бэкофилле (ТЗ §6)
    BACKFILL_SINCE_YEAR = int(os.environ.get("BACKFILL_SINCE_YEAR", "2023"))
    # Ежедневный автосинк (APScheduler); час по UTC
    SYNC_HOUR_UTC = int(os.environ.get("SYNC_HOUR_UTC", "2"))
    ENABLE_SCHEDULER = os.environ.get("ENABLE_SCHEDULER", "1") == "1"

    BOOTSTRAP_ADMIN_EMAIL = os.environ.get("BOOTSTRAP_ADMIN_EMAIL")
    BOOTSTRAP_ADMIN_PASSWORD = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD")

    # Сессии
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("FLASK_ENV", "production") == "production"

    APP_NAME = "DashboardSales&Marketing"

    @property
    def amocrm_base_url(self) -> str:
        return f"https://{self.AMOCRM_SUBDOMAIN}.amocrm.ru/api/v4"
