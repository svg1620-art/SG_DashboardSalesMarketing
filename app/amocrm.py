"""Клиент amoCRM API v4.

На Stage 1 используется для проверки токена/доступности и реальной глубины
истории событий (events), от которой зависит объём фолбэка (ТЗ §6, §11).
"""
import re

import httpx


class AmoCRMError(Exception):
    pass


def normalize_subdomain(raw: str) -> str:
    """Оставляет только сам субдомен из любого разумного ввода.

    Терпит `https://`, хвост `.amocrm.ru`/`.amocrm.com`, слэши и пробелы —
    чтобы неверный формат переменной не приводил к DNS-ошибке.
    """
    s = (raw or "").strip()
    s = re.sub(r"^https?://", "", s, flags=re.IGNORECASE)  # убрать схему
    s = s.split("/")[0]                                     # убрать путь
    s = re.sub(r"\.amocrm\.(ru|com)$", "", s, flags=re.IGNORECASE)  # убрать домен
    return s.strip().strip(".")


class AmoCRMClient:
    def __init__(self, subdomain: str, token: str, timeout: float = 30.0):
        subdomain = normalize_subdomain(subdomain)
        if not subdomain or not token:
            raise AmoCRMError("Не заданы AMOCRM_SUBDOMAIN / AMOCRM_TOKEN")
        self.subdomain = subdomain
        self.base_url = f"https://{subdomain}.amocrm.ru/api/v4"
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self._timeout = timeout

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        try:
            resp = httpx.get(url, headers=self._headers, params=params, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise AmoCRMError(f"Сетевая ошибка при обращении к amoCRM: {exc}") from exc
        if resp.status_code == 401:
            raise AmoCRMError("amoCRM вернул 401 — недействительный токен")
        if resp.status_code == 204:
            return {}
        if resp.status_code >= 400:
            raise AmoCRMError(f"amoCRM вернул {resp.status_code}: {resp.text[:300]}")
        try:
            return resp.json()
        except ValueError as exc:
            raise AmoCRMError(f"Не удалось разобрать JSON от amoCRM: {exc}") from exc

    # --- Проверочные вызовы Stage 1 ---

    def account(self) -> dict:
        """GET /account — проверка токена и доступности субдомена."""
        return self._get("/account")

    def pipelines(self) -> list[dict]:
        """GET /leads/pipelines — воронки и их статусы."""
        data = self._get("/leads/pipelines")
        return data.get("_embedded", {}).get("pipelines", [])

    def probe_events_depth(self) -> dict:
        """Оценка реальной глубины истории смены статусов.

        Возвращает самую раннюю доступную дату события lead_status_changed,
        чтобы зафиксировать, с какого момента история пригодна (ТЗ §6, риск).
        """
        data = self._get(
            "/events",
            params={
                "filter[type]": "lead_status_changed",
                "filter[entity]": "lead",
                "order[created_at]": "asc",
                "limit": 1,
            },
        )
        events = data.get("_embedded", {}).get("events", [])
        if not events:
            return {"available": False, "earliest_created_at": None}
        return {
            "available": True,
            "earliest_created_at": events[0].get("created_at"),
        }


def client_from_config(config) -> AmoCRMClient:
    return AmoCRMClient(config.AMOCRM_SUBDOMAIN, config.AMOCRM_TOKEN)
