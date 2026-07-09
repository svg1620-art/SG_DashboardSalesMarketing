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


# Общие агрегаты воронки (без разреза) — переиспользуются источниками и месяцами
_COUNTS = """
    count(*) FILTER (WHERE d.reached_mql)                       AS mql,
    count(*) FILTER (WHERE d.reached_sql)                       AS sql,
    count(*) FILTER (WHERE d.meeting_scheduled)                 AS meeting_scheduled,
    count(*) FILTER (WHERE d.meeting_held)                      AS meeting_held,
    count(*) FILTER (WHERE d.invoiced)                          AS invoiced,
    count(*) FILTER (WHERE d.sold)                              AS sold,
    count(*) FILTER (WHERE d.is_lost AND NOT d.meeting_scheduled) AS unqualified,
    COALESCE(sum(d.price) FILTER (WHERE d.sold), 0)            AS revenue
"""

# Агрегаты воронки по источнику
_FUNNEL_SELECT = (
    "COALESCE(NULLIF(d.source, ''), '(без источника)') AS source, " + _COUNTS
)


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


def by_month(f: dict, config) -> dict:
    """Помесячная когортная воронка + юнит-экономика (ТЗ §3).

    Атрибуция по месяцу СОЗДАНИЯ лида: продажи/выручка догоняются по мере
    закрытия сделок в строку месяца, когда лид создан (не когда закрылся).
    """
    where, params = _deal_where(f)
    rows = db.query(
        f"""SELECT to_char(date_trunc('month', d.created_at), 'YYYY-MM') AS month,
                {_COUNTS},
                COALESCE(sum(d.sum_platform) FILTER (WHERE d.sold), 0) AS platform_revenue,
                COALESCE(avg(d.monthly_payment) FILTER (WHERE d.sold
                    AND d.monthly_payment IS NOT NULL), 0) AS arppu,
                COALESCE(avg(d.license_months) FILTER (WHERE d.sold), 0) AS lic_months
             FROM deals d
             WHERE {where} AND d.created_at IS NOT NULL
             GROUP BY 1 ORDER BY 1""",
        params,
    )
    ad = _ad_by_month(f)
    op = _opcosts_by_month()

    out = []
    for r in rows:
        r = dict(r)
        _coerce_month(r)
        _add_unit_economics(r, ad.get(r["month"], 0.0),
                            op.get(r["month"]), config)
        out.append(r)

    total = _month_totals(out, ad, op, config)
    return {"rows": out, "total": total}


def _coerce_month(r: dict) -> None:
    r["revenue"] = float(r["revenue"] or 0)
    r["platform_revenue"] = float(r["platform_revenue"] or 0)
    r["arppu"] = float(r["arppu"] or 0)
    r["lic_months"] = float(r["lic_months"] or 0)


def _add_unit_economics(r: dict, ad_spend: float, oc, config) -> None:
    """CAC / средний чек / LTV / LTV:CAC / ROAS для месяца (уточнения заказчика)."""
    won = r["sold"]
    salary_sales = float(oc["salary_sales"]) if oc else 0.0
    salary_marketing = float(oc["salary_marketing"]) if oc else 0.0
    payroll_tax_pct = float(oc["payroll_tax_pct"]) if oc else 0.0

    salaries = salary_sales + salary_marketing
    payroll_tax = salaries * payroll_tax_pct / 100.0
    turnover_tax = r["revenue"] * config.TURNOVER_TAX_PCT / 100.0
    total_cost = salaries + payroll_tax + ad_spend + turnover_tax

    r["ad_spend"] = ad_spend
    r["salary_sales"] = salary_sales
    r["salary_marketing"] = salary_marketing
    r["payroll_tax"] = payroll_tax
    r["turnover_tax"] = turnover_tax
    r["total_cost"] = total_cost

    r["cac"] = _div(total_cost, won)
    # средний чек = выручка по платформе (разовая) / клиенты; LTV = × срок жизни
    r["avg_check"] = _div(r["platform_revenue"], won)
    r["ltv"] = r["avg_check"] * config.LTV_MONTHS if r["avg_check"] is not None else None
    r["ltv_cac"] = _div(r["ltv"], r["cac"]) if r["cac"] else None
    r["roas"] = _div(r["revenue"], ad_spend)
    r["cr_mql_sale"] = _div(won, r["mql"])
    r["reachability"] = _div(r["meeting_held"], r["meeting_scheduled"])


def _month_totals(rows: list, ad: dict, op: dict, config) -> dict:
    keys = ["mql", "sql", "meeting_scheduled", "meeting_held", "invoiced",
            "sold", "unqualified", "revenue", "platform_revenue"]
    t = {k: 0 for k in keys}
    for r in rows:
        for k in keys:
            t[k] += r[k] or 0
    t["month"] = "Итого"
    t["arppu"] = _div(sum(r["arppu"] * r["sold"] for r in rows), t["sold"]) or 0
    t["lic_months"] = _div(sum(r["lic_months"] * r["sold"] for r in rows), t["sold"]) or 0
    ad_total = sum(ad.values())
    # суммарные операционные затраты по всем месяцам
    salaries = sum(float(v["salary_sales"]) + float(v["salary_marketing"]) for v in op.values())
    payroll = sum((float(v["salary_sales"]) + float(v["salary_marketing"]))
                  * float(v["payroll_tax_pct"]) / 100.0 for v in op.values())
    turnover = t["revenue"] * config.TURNOVER_TAX_PCT / 100.0
    total_cost = salaries + payroll + ad_total + turnover
    t["ad_spend"] = ad_total
    t["total_cost"] = total_cost
    t["cac"] = _div(total_cost, t["sold"])
    t["avg_check"] = _div(t["platform_revenue"], t["sold"])
    t["ltv"] = t["avg_check"] * config.LTV_MONTHS if t["avg_check"] is not None else None
    t["ltv_cac"] = _div(t["ltv"], t["cac"]) if t["cac"] else None
    t["roas"] = _div(t["revenue"], ad_total)
    t["cr_mql_sale"] = _div(t["sold"], t["mql"])
    t["reachability"] = _div(t["meeting_held"], t["meeting_scheduled"])
    return t


def _ad_by_month(f: dict) -> dict:
    """Рекламные затраты по месяцам из costs_touches (для CAC и ROAS)."""
    clauses, params = [], []
    if f.get("source"):
        clauses.append("source = %s")
        params.append(f["source"])
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = db.query(
        f"SELECT to_char(period_month, 'YYYY-MM') AS month, sum(amount) AS amount "
        f"FROM costs_touches{where} GROUP BY 1",
        params,
    )
    return {r["month"]: float(r["amount"] or 0) for r in rows}


def _opcosts_by_month() -> dict:
    rows = db.query(
        "SELECT to_char(period_month, 'YYYY-MM') AS month, salary_sales, "
        "salary_marketing, payroll_tax_pct FROM monthly_costs"
    )
    return {r["month"]: r for r in rows}


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
