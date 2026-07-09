"""Расчёт метрик воронки из БД (ТЗ §3). Агрегация на лету по deals + costs.

Метрики считаются по когорте сделок, СОЗДАННЫХ в периоде (MQL по дате создания,
§3). Затраты берутся из costs_touches по месяцам, попадающим в период.
"""
from datetime import date, datetime

from . import db


def parse_filters(args) -> dict:
    """Разбирает GET-параметры фильтра в нормализованный словарь."""
    def _d(key):
        raw = (args.get(key) or "").strip()
        if not raw:
            return None
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            return None

    def _i(key):
        raw = (args.get(key) or "").strip()
        return int(raw) if raw.isdigit() else None

    return {
        "date_from": _d("date_from"),
        "date_to": _d("date_to"),
        "manager_id": _i("manager_id"),
        "source": (args.get("source") or "").strip() or None,
    }


def _deal_where(f: dict):
    """WHERE и параметры для выборки сделок по фильтру. База = MQL (не исключённые)."""
    clauses = ["d.reached_mql"]
    params = []
    if f.get("date_from"):
        clauses.append("d.created_at >= %s")
        params.append(f["date_from"])
    if f.get("date_to"):
        clauses.append("d.created_at < %s")
        params.append(_next_day(f["date_to"]))
    if f.get("manager_id"):
        clauses.append("d.responsible_user_id = %s")
        params.append(f["manager_id"])
    if f.get("source"):
        clauses.append("d.source = %s")
        params.append(f["source"])
    return " AND ".join(clauses), params


def _next_day(d: date) -> date:
    from datetime import timedelta
    return d + timedelta(days=1)


# Агрегаты воронки по источнику
_FUNNEL_SELECT = """
    COALESCE(NULLIF(d.source, ''), '(без источника)') AS source,
    count(*) FILTER (WHERE d.reached_mql)                       AS mql,
    count(*) FILTER (WHERE d.reached_sql)                       AS sql,
    count(*) FILTER (WHERE d.meeting_scheduled)                 AS meeting_scheduled,
    count(*) FILTER (WHERE d.meeting_held)                      AS meeting_held,
    count(*) FILTER (WHERE d.invoiced)                          AS invoiced,
    count(*) FILTER (WHERE d.sold)                              AS sold,
    count(*) FILTER (WHERE d.is_lost AND NOT d.meeting_scheduled) AS unqualified,
    COALESCE(sum(d.price) FILTER (WHERE d.sold), 0)            AS revenue
"""


def by_source(f: dict) -> dict:
    """Метрики по каждому источнику + строка «Все источники» + данные воронки."""
    where, params = _deal_where(f)
    rows = db.query(
        f"SELECT {_FUNNEL_SELECT} FROM deals d WHERE {where} "
        f"GROUP BY 1 ORDER BY mql DESC",
        params,
    )
    costs = _costs_by_source(f)

    result_rows = []
    for r in rows:
        r = dict(r)
        r["revenue"] = float(r["revenue"] or 0)
        c = costs.get(r["source"], {"amount": 0, "touches": 0})
        r["amount"] = float(c["amount"] or 0)
        r["touches"] = int(c["touches"] or 0)
        _add_derived(r)
        result_rows.append(r)

    total = _totals(result_rows, f)
    funnel = {
        "labels": ["Лиды (MQL)", "Возможности (SQL)", "Назначено встреч",
                   "Проведено встреч", "Выставлено счетов", "Продажи"],
        "values": [total["mql"], total["sql"], total["meeting_scheduled"],
                   total["meeting_held"], total["invoiced"], total["sold"]],
    }
    return {"rows": result_rows, "total": total, "funnel": funnel}


def _costs_by_source(f: dict) -> dict:
    clauses = []
    params = []
    if f.get("date_from"):
        clauses.append("period_month >= date_trunc('month', %s::date)")
        params.append(f["date_from"])
    if f.get("date_to"):
        clauses.append("period_month <= %s")
        params.append(f["date_to"])
    if f.get("source"):
        clauses.append("source = %s")
        params.append(f["source"])
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = db.query(
        f"SELECT source, sum(amount) AS amount, sum(touches) AS touches "
        f"FROM costs_touches{where} GROUP BY source",
        params,
    )
    return {r["source"]: {"amount": r["amount"], "touches": r["touches"]} for r in rows}


def _div(a, b):
    return (a / b) if b else None


def _add_derived(r: dict) -> None:
    """Производные метрики (§3) для одной строки."""
    mql = r["mql"]
    r["cr_mql_sql"] = _div(r["sql"], mql)
    r["cr_sql_meeting"] = _div(r["meeting_scheduled"], r["sql"])
    r["reachability"] = _div(r["meeting_held"], r["meeting_scheduled"])  # доходимость
    r["cr_meeting_sale"] = _div(r["sold"], r["meeting_held"])
    r["unqual_pct"] = _div(r["unqualified"], mql)
    r["cr_mql_sale"] = _div(r["sold"], mql)
    # cost-метрики (нужны затраты)
    amount = r["amount"]
    r["cpl"] = _div(amount, mql)
    r["price_meeting"] = _div(amount, r["meeting_scheduled"])
    r["price_reached"] = _div(amount, r["meeting_held"])
    r["price_sale"] = _div(amount, r["sold"])
    r["roas"] = _div(r["revenue"], amount)
    r["avg_check"] = _div(r["revenue"], r["sold"])


def _totals(rows: list, f: dict) -> dict:
    keys = ["mql", "sql", "meeting_scheduled", "meeting_held", "invoiced",
            "sold", "unqualified", "revenue", "amount", "touches"]
    total = {k: 0 for k in keys}
    for r in rows:
        for k in keys:
            total[k] += r[k] or 0
    total["source"] = "Все источники"
    _add_derived(total)
    return total


def filter_options() -> dict:
    """Списки для выпадающих фильтров + границы дат."""
    managers = db.query(
        "SELECT amo_user_id, name FROM managers WHERE is_active ORDER BY name"
    )
    sources = db.query(
        "SELECT name FROM sources WHERE is_active ORDER BY name"
    )
    bounds = db.query(
        "SELECT min(created_at)::date AS min_d, max(created_at)::date AS max_d FROM deals",
        fetchone=True,
    )
    return {"managers": managers, "sources": sources,
            "min_date": bounds["min_d"] if bounds else None,
            "max_date": bounds["max_d"] if bounds else None}
