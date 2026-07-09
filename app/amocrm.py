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
        """GET по относительному пути или абсолютному URL (для _links.next)."""
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        last_exc = None
        for attempt in range(4):
            try:
                resp = httpx.get(url, headers=self._headers, params=params,
                                 timeout=self._timeout)
            except httpx.HTTPError as exc:
                last_exc = exc
                continue  # сетевые сбои — повтор
            if resp.status_code == 401:
                raise AmoCRMError("amoCRM вернул 401 — недействительный токен")
            if resp.status_code == 204:
                return {}
            if resp.status_code == 429:
                continue  # лимит запросов — повтор
            if resp.status_code >= 400:
                raise AmoCRMError(f"amoCRM вернул {resp.status_code}: {resp.text[:300]}")
            try:
                return resp.json()
            except ValueError as exc:
                raise AmoCRMError(f"Не удалось разобрать JSON от amoCRM: {exc}") from exc
        raise AmoCRMError(f"Сетевая ошибка при обращении к amoCRM: {last_exc}")

    def _paginate(self, path: str, params: dict, embedded_key: str):
        """Генератор по страницам с обходом _links.next (ТЗ §6)."""
        page_params = dict(params or {})
        page_params.setdefault("limit", 250)
        next_url = None
        while True:
            data = self._get(next_url or path, None if next_url else page_params)
            if not data:  # 204 — данных больше нет
                break
            items = data.get("_embedded", {}).get(embedded_key, [])
            for item in items:
                yield item
            next_url = data.get("_links", {}).get("next", {}).get("href")
            if not next_url or not items:
                break

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


    # --- Данные для синхронизации Stage 2 ---

    def users(self) -> list[dict]:
        """GET /users — сопоставление responsible_user_id → имя менеджера."""
        return list(self._paginate("/users", {"limit": 250}, "users"))

    def custom_fields(self) -> list[dict]:
        """GET /leads/custom_fields — определение ID кастомных полей."""
        return list(self._paginate("/leads/custom_fields", {"limit": 250}, "custom_fields"))

    def iter_leads(self, pipeline_id: int | None = None):
        """GET /leads постранично. limit=250, обход по _links.next."""
        params = {"limit": 250, "with": "contacts"}
        if pipeline_id is not None:
            params["filter[pipeline_id]"] = pipeline_id
        yield from self._paginate("/leads", params, "leads")

    def iter_status_events(self, created_from: int | None = None,
                           created_to: int | None = None):
        """GET /events (lead_status_changed) постранично по диапазону дат."""
        params = {
            "filter[type]": "lead_status_changed",
            "filter[entity]": "lead",
            "order[created_at]": "asc",
            "limit": 100,
        }
        if created_from is not None:
            params["filter[created_at][from]"] = created_from
        if created_to is not None:
            params["filter[created_at][to]"] = created_to
        yield from self._paginate("/events", params, "events")


def client_from_config(config) -> AmoCRMClient:
    return AmoCRMClient(config.AMOCRM_SUBDOMAIN, config.AMOCRM_TOKEN)
