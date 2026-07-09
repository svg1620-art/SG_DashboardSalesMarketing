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
