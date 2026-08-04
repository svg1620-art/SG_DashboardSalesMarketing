"""Движок синхронизации amoCRM → PostgreSQL (ТЗ §6).

Тянет справочники (статусы/менеджеры/поля), сделки и историю событий,
вычисляет этапы воронки и делает идемпотентный upsert. Запускается в фоновом
потоке с прогрессом (кнопка «Обновить») и по расписанию (APScheduler).
"""
import threading
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

from .amocrm import AmoCRMClient, AmoCRMError
from .stages import compute_stages, LOST_STATUS_ID

# Сопоставление кастомных полей amoCRM по вхождению в имя (регистр не важен).
# Список редактируется здесь; сущностные для воронки — source и client_type.
# Ключ advisory-lock: не даёт двум процессам (воркерам/шедулеру) синкать разом
SYNC_LOCK_KEY = 815162342

CF_PATTERNS = {
    "source": ["источник"],
    "client_type": ["тип клиента"],
    "monthly_payment": ["ежемесяч"],
    "sum_platform": ["платформ"],
    "sum_implementation": ["внедрен"],
    "sum_courses": ["курс"],
    "license_months": ["срок лицензии", "лиценз"],
}


# --- Прогресс фоновой синхронизации (in-memory, потокобезопасно) ---

class SyncProgress:
    def __init__(self):
        self._lock = threading.Lock()
        self.running = False
        self.phase = "idle"
        self.deals_done = 0
        self.deals_total = 0
        self.events_done = 0
        self.message = ""
        self.error = None
        self.finished_at = None

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "running": self.running, "phase": self.phase,
                "deals_done": self.deals_done, "deals_total": self.deals_total,
                "events_done": self.events_done, "message": self.message,
                "error": self.error, "finished_at": self.finished_at,
            }

    def update(self, **kw):
        with self._lock:
            for k, v in kw.items():
                setattr(self, k, v)


PROGRESS = SyncProgress()


# --- Вспомогательные функции ---

def resolve_custom_fields(fields: list[dict]) -> dict:
    """Строит {target: field_id} по именам полей amoCRM."""
    resolved = {}
    for f in fields:
        name = (f.get("name") or "").lower()
        for target, needles in CF_PATTERNS.items():
            if target in resolved:
                continue
            if any(n in name for n in needles):
                resolved[target] = f.get("id")
    return resolved


def _cf_value(lead: dict, field_id):
    """Достаёт первое значение кастомного поля сделки по field_id."""
    if field_id is None:
        return None
    for cf in lead.get("custom_fields_values") or []:
        if cf.get("field_id") == field_id:
            values = cf.get("values") or []
            if values:
                return values[0].get("value")
    return None


def _num(value):
    try:
        if value in (None, ""):
            return None
        return float(str(value).replace(" ", "").replace(",", "."))
    except (ValueError, TypeError):
        return None


def _ts_to_dt(ts):
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc)


def _status_from_event(event: dict):
    """status_id, в который перешла сделка (value_after) + метка времени."""
    after = event.get("value_after") or []
    status_id = None
    if after:
        status_id = (after[0].get("lead_status") or {}).get("id")
    return event.get("entity_id"), status_id, event.get("created_at")


# --- Основной прогон ---

def run_sync(config, full: bool = False) -> None:
    """Полный проход синхронизации. Пишет в sync_log и обновляет PROGRESS."""
    PROGRESS.update(running=True, phase="init", deals_done=0, deals_total=0,
                    events_done=0, error=None, message="Запуск синхронизации",
                    finished_at=None)
    conn = psycopg2.connect(config.DATABASE_URL)
    conn.autocommit = False
    log_id = None

    # Не запускаем параллельно с другим процессом (lock снимается при close)
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (SYNC_LOCK_KEY,))
        if not cur.fetchone()[0]:
            conn.close()
            PROGRESS.update(running=False, phase="idle",
                            message="Синхронизация уже идёт в другом процессе")
            return

    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sync_log (status, message) VALUES ('running', %s) RETURNING id",
                (f"{'backfill' if full else 'incremental'} старт",),
            )
            log_id = cur.fetchone()[0]
        conn.commit()

        client = AmoCRMClient(config.AMOCRM_SUBDOMAIN, config.AMOCRM_TOKEN)

        # 1. Справочники
        PROGRESS.update(phase="reference", message="Справочники")
        _sync_managers(conn, client)
        _sync_statuses(conn, client, config.AMOCRM_PIPELINE_ID)
        cf_map = resolve_custom_fields(client.custom_fields())

        # 2. События (история смены статусов)
        PROGRESS.update(phase="events", message="История событий")
        created_from = _events_from_ts(conn, config, full)
        events_synced = _sync_events(conn, client, created_from)

        # 3. Сделки + вычисление этапов
        PROGRESS.update(phase="deals", message="Сделки")
        status_map = _load_status_map(conn)
        history = _load_history(conn)
        deals_synced, seen = _sync_deals(conn, client, config, cf_map, status_map, history)

        # 3b. Сверка: удаляем сделки, исчезнувшие из воронки amoCRM
        PROGRESS.update(phase="reconcile", message="Сверка удалённых/перенесённых")
        removed = _reconcile_deals(conn, seen)

        # 4. Обновление справочника источников
        _sync_sources(conn)

        removed_note = (f", удалено (нет в amo) {removed}" if removed > 0 else
                        f", сверка пропущена ({-removed} под удаление)" if removed < 0 else "")
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE sync_log SET finished_at = now(), status = 'ok',
                       deals_synced = %s, events_synced = %s,
                       message = %s WHERE id = %s""",
                (deals_synced, events_synced,
                 f"OK: сделок {deals_synced}, событий {events_synced}{removed_note}, "
                 f"поля {sorted(cf_map)}", log_id),
            )
        conn.commit()
        PROGRESS.update(running=False, phase="done", deals_done=deals_synced,
                        events_done=events_synced,
                        message=f"Готово: сделок {deals_synced}, событий {events_synced}",
                        finished_at=datetime.now(timezone.utc).isoformat())
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        msg = str(exc)
        if log_id is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE sync_log SET finished_at = now(), status = 'error', "
                        "message = %s WHERE id = %s", (msg[:1000], log_id),
                    )
                conn.commit()
            except Exception:  # noqa: BLE001
                conn.rollback()
        PROGRESS.update(running=False, phase="error", error=msg,
                        message=f"Ошибка: {msg}",
                        finished_at=datetime.now(timezone.utc).isoformat())
    finally:
        conn.close()


def run_sync_background(config, full: bool = False) -> bool:
    """Стартует run_sync в отдельном потоке. False, если уже идёт."""
    if PROGRESS.snapshot()["running"]:
        return False
    t = threading.Thread(target=run_sync, args=(config,), kwargs={"full": full},
                         daemon=True)
    t.start()
    return True


# --- Шаги ---

def _sync_managers(conn, client: AmoCRMClient) -> None:
    rows = []
    for u in client.users():
        rows.append((u.get("id"), u.get("name") or "", True))
    if not rows:
        return
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO managers (amo_user_id, name, is_active) VALUES %s
               ON CONFLICT (amo_user_id) DO UPDATE
                   SET name = EXCLUDED.name, is_active = EXCLUDED.is_active""",
            rows,
        )
    conn.commit()


def _sync_statuses(conn, client: AmoCRMClient, pipeline_id: int) -> None:
    """Upsert статусов целевой воронки. mapped_stage/is_excluded НЕ трогаем
    (правки admin и посев миграции сохраняются)."""
    rows = []
    for p in client.pipelines():
        if p.get("id") != pipeline_id:
            continue
        for s in p.get("_embedded", {}).get("statuses", []):
            rows.append((s.get("id"), p.get("id"), s.get("name") or "",
                         s.get("sort") or 0))
    if not rows:
        return
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO pipeline_statuses (status_id, pipeline_id, name, sort_order)
               VALUES %s
               ON CONFLICT (status_id) DO UPDATE
                   SET pipeline_id = EXCLUDED.pipeline_id,
                       name = EXCLUDED.name,
                       sort_order = EXCLUDED.sort_order""",
            rows,
        )
    conn.commit()


def _events_from_ts(conn, config, full: bool) -> int:
    """С какой метки времени тянуть события."""
    year_start = int(datetime(config.BACKFILL_SINCE_YEAR, 1, 1,
                              tzinfo=timezone.utc).timestamp())
    if full:
        return year_start
    with conn.cursor() as cur:
        cur.execute("SELECT max(finished_at) FROM sync_log WHERE status = 'ok'")
        last = cur.fetchone()[0]
    if last is None:
        return year_start
    # запас в сутки на случай пропусков
    return int(last.timestamp()) - 86400


def _sync_events(conn, client: AmoCRMClient, created_from: int) -> int:
    count = 0
    batch = []
    for ev in client.iter_status_events(created_from=created_from):
        lead_id, status_id, created_at = _status_from_event(ev)
        if not lead_id or not status_id:
            continue
        batch.append((lead_id, status_id, _ts_to_dt(created_at)))
        if len(batch) >= 500:
            count += _flush_events(conn, batch)
            batch = []
            PROGRESS.update(events_done=count)
    if batch:
        count += _flush_events(conn, batch)
        PROGRESS.update(events_done=count)
    return count


def _flush_events(conn, batch) -> int:
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO deal_stage_history (amo_lead_id, status_id, changed_at)
               VALUES %s ON CONFLICT (amo_lead_id, status_id, changed_at) DO NOTHING""",
            batch,
        )
    conn.commit()
    return len(batch)


def _load_status_map(conn) -> dict:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT status_id, mapped_stage, is_excluded FROM pipeline_statuses")
        return {r["status_id"]: {"mapped_stage": r["mapped_stage"],
                                 "is_excluded": r["is_excluded"]}
                for r in cur.fetchall()}


def _load_history(conn) -> dict:
    """{amo_lead_id: set(status_id)} по всей накопленной истории."""
    hist: dict = {}
    with conn.cursor() as cur:
        cur.execute("SELECT amo_lead_id, status_id FROM deal_stage_history")
        for lead_id, status_id in cur.fetchall():
            hist.setdefault(lead_id, set()).add(status_id)
    return hist


def _sync_deals(conn, client, config, cf_map, status_map, history):
    """Возвращает (кол-во, множество актуальных amo_lead_id из amoCRM)."""
    count = 0
    seen = set()
    batch = []
    for lead in client.iter_leads(pipeline_id=config.AMOCRM_PIPELINE_ID):
        lead_id = lead.get("id")
        if lead_id is not None:
            seen.add(lead_id)
        row = _build_deal_row(lead, cf_map, status_map, history)
        batch.append(row)
        count += 1
        if len(batch) >= 500:
            _flush_deals(conn, batch)
            batch = []
            PROGRESS.update(deals_done=count)
    if batch:
        _flush_deals(conn, batch)
    PROGRESS.update(deals_done=count, deals_total=count)
    return count, seen


def _reconcile_deals(conn, seen: set) -> int:
    """Удаляет сделки, которых больше нет в воронке amoCRM (удалены/перенесены).

    iter_leads отдаёт ВСЕ текущие сделки воронки (включая закрытые — они остаются
    в воронке), поэтому отсутствие в `seen` = сделки в amoCRM больше нет.
    Защита: не удаляем при пустой/подозрительно малой выгрузке.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT amo_lead_id FROM deals")
        existing = {r[0] for r in cur.fetchall()}
    stale = existing - seen
    if not stale:
        return 0

    # Страховка от массового удаления из-за сбойной/частичной выгрузки:
    # пустой seen или удаление >20% базы (и >100 сделок) — не трогаем, только лог.
    if not seen or (len(stale) > 100 and len(stale) > 0.2 * max(1, len(existing))):
        PROGRESS.update(message=f"Сверка пропущена: под удаление попало "
                        f"{len(stale)} сделок — похоже на неполную выгрузку")
        return -len(stale)  # отрицательное = пропущено (для лога)

    ids = list(stale)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM deal_stage_history WHERE amo_lead_id = ANY(%s)", (ids,))
        cur.execute("DELETE FROM deals WHERE amo_lead_id = ANY(%s)", (ids,))
    conn.commit()
    return len(stale)


def _build_deal_row(lead, cf_map, status_map, history):
    lead_id = lead.get("id")
    current_status_id = lead.get("status_id")
    client_type = _cf_value(lead, cf_map.get("client_type"))
    passed = history.get(lead_id, set())
    st = compute_stages(current_status_id, passed, client_type, status_map)
    stage_source = "events" if passed else "fallback"

    return (
        lead_id,
        lead.get("pipeline_id"),
        current_status_id,
        lead.get("responsible_user_id"),
        _cf_value(lead, cf_map.get("source")),
        _num(lead.get("price")),
        _ts_to_dt(lead.get("created_at")),
        _ts_to_dt(lead.get("closed_at")),
        st["is_won"], st["is_lost"], client_type,
        _num(_cf_value(lead, cf_map.get("monthly_payment"))),
        _num(_cf_value(lead, cf_map.get("sum_platform"))),
        _num(_cf_value(lead, cf_map.get("sum_implementation"))),
        _num(_cf_value(lead, cf_map.get("sum_manager"))),
        _num(_cf_value(lead, cf_map.get("sum_courses"))),
        _int(_cf_value(lead, cf_map.get("license_months"))),
        st["max_stage_reached"],
        st["reached_mql"], st["reached_sql"], st["meeting_scheduled"],
        st["meeting_held"], st["invoiced"], st["sold"],
        stage_source,
        psycopg2.extras.Json(lead),
    )


def _int(value):
    n = _num(value)
    return int(n) if n is not None else None


DEAL_COLUMNS = (
    "amo_lead_id, pipeline_id, current_status_id, responsible_user_id, source, "
    "price, created_at, closed_at, is_won, is_lost, client_type, monthly_payment, "
    "sum_platform, sum_implementation, sum_manager, sum_courses, license_months, "
    "max_stage_reached, reached_mql, reached_sql, meeting_scheduled, meeting_held, "
    "invoiced, sold, stage_source, raw"
)


def _flush_deals(conn, batch) -> None:
    update_cols = [c.strip() for c in DEAL_COLUMNS.split(",") if c.strip() != "amo_lead_id"]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            f"""INSERT INTO deals ({DEAL_COLUMNS}, synced_at) VALUES %s
                ON CONFLICT (amo_lead_id) DO UPDATE
                    SET {set_clause}, synced_at = now()""",
            batch,
            template="(" + ", ".join(["%s"] * 26) + ", now())",
        )
    conn.commit()


def _sync_sources(conn) -> None:
    """Объединение источников из сделок и ручных затрат (ТЗ §8)."""
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO sources (name)
               SELECT DISTINCT source FROM deals
                   WHERE source IS NOT NULL AND source <> ''
               ON CONFLICT (name) DO NOTHING"""
        )
    conn.commit()
