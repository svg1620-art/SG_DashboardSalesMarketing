"""Чистая логика вычисления этапов воронки (ТЗ §3, §6).

Вынесена отдельно от синхронизации, чтобы покрывать юнит-тестами без API/БД.
"""

# Порядковые номера этапов воронки (§3)
STAGE_ORDER = {
    "mql": 1,
    "sql": 2,
    "meeting_scheduled": 3,
    "meeting_held": 4,
    "invoiced": 5,
    "won": 6,
}

MILESTONES = ("meeting_scheduled", "meeting_held", "invoiced", "won")

# Глобальные встроенные статусы amoCRM (одинаковы во всех воронках)
WON_STATUS_ID = 142
LOST_STATUS_ID = 143


def compute_stages(current_status_id, passed_status_ids, client_type, status_map):
    """Возвращает флаги этапов и max_stage_reached для одной сделки.

    - current_status_id: текущий status_id сделки
    - passed_status_ids: множество/список status_id, пройденных по истории событий
    - client_type: значение поля «Тип клиента в сделке» (для SQL)
    - status_map: {status_id: {"mapped_stage": str, "is_excluded": bool}}
    """
    cur = status_map.get(current_status_id, {})

    # Дубли и прочие исключённые статусы полностью вне воронки (решение по MQL)
    if cur.get("is_excluded"):
        return {
            "reached_mql": False, "reached_sql": False,
            "meeting_scheduled": False, "meeting_held": False,
            "invoiced": False, "sold": False,
            "is_won": False, "is_lost": current_status_id == LOST_STATUS_ID,
            "max_stage_reached": 0,
        }

    all_ids = set(passed_status_ids or ())
    if current_status_id is not None:
        all_ids.add(current_status_id)

    hit = set()
    for sid in all_ids:
        ms = status_map.get(sid, {}).get("mapped_stage", "none")
        if ms in MILESTONES:
            hit.add(ms)

    meeting_scheduled = "meeting_scheduled" in hit
    meeting_held = "meeting_held" in hit
    invoiced = "invoiced" in hit
    won = "won" in hit or current_status_id == WON_STATUS_ID

    # Линейная порядковая воронка: достижение этапа N ⇒ пройдены предыдущие (§3)
    if won:
        invoiced = meeting_held = meeting_scheduled = True
    if invoiced:
        meeting_held = meeting_scheduled = True
    if meeting_held:
        meeting_scheduled = True

    reached_mql = True  # существует в воронке и не исключён
    reached_sql = bool(client_type and str(client_type).strip())

    max_stage = 1  # mql
    if reached_sql:
        max_stage = 2
    if meeting_scheduled:
        max_stage = max(max_stage, 3)
    if meeting_held:
        max_stage = max(max_stage, 4)
    if invoiced:
        max_stage = max(max_stage, 5)
    if won:
        max_stage = 6

    return {
        "reached_mql": reached_mql, "reached_sql": reached_sql,
        "meeting_scheduled": meeting_scheduled, "meeting_held": meeting_held,
        "invoiced": invoiced, "sold": won,
        "is_won": current_status_id == WON_STATUS_ID,
        "is_lost": current_status_id == LOST_STATUS_ID,
        "max_stage_reached": max_stage,
    }
