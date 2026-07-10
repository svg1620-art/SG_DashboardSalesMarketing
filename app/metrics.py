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

    # Явно выбранные месяцы для сравнения (multiselect) — 'YYYY-MM'
    if hasattr(args, "getlist"):
        months = [m.strip() for m in args.getlist("months") if m.strip()]
    else:
        months = [m for m in (args.get("months") or "").split(",") if m.strip()]
    moy_raw = (args.get("month_of_year") or "").strip()
    month_of_year = int(moy_raw) if moy_raw.isdigit() and 1 <= int(moy_raw) <= 12 else None

    return {
        "date_from": _d("date_from"),
        "date_to": _d("date_to"),
        "manager_id": _i("manager_id"),
        "source": (args.get("source") or "").strip() or None,
        "client_type": (args.get("client_type") or "").strip() or None,
        "months": months,
        "month_of_year": month_of_year,
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
    if f.get("client_type"):
        clauses.append("d.client_type = %s")
        params.append(f["client_type"])
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

    # Итого — по всем источникам (до скрытия пустых), чтобы KPI были полными
    total = _totals(result_rows, f)

    # Скрываем «мёртвые» источники: ни одного результата дальше лида и без выручки
    result_rows = [r for r in result_rows if _source_has_activity(r)]

    values = [total["mql"], total["sql"], total["meeting_scheduled"],
              total["meeting_held"], total["invoiced"], total["sold"]]
    funnel = {
        "labels": ["Лиды (MQL)", "Возможности (SQL)", "Назначено встреч",
                   "Проведено встреч", "Выставлено счетов", "Продажи"],
        "values": values,
        # поэтапная конверсия каждого этапа к предыдущему (для подписей на диаграмме)
        "conv": [None] + [_div(values[i], values[i - 1]) for i in range(1, len(values))],
    }
    funnel_ct = _funnel_by_client_type(where, params)
    return {"rows": result_rows, "total": total, "funnel": funnel,
            "funnel_ct": funnel_ct}


def _funnel_by_client_type(where: str, params: list) -> dict:
    """Разбивка воронки с этапа SQL по типу клиента (для стека и процентов)."""
    rows = db.query(
        f"""SELECT COALESCE(NULLIF(d.client_type, ''), '(без типа)') AS ct,
                   count(*) FILTER (WHERE d.reached_sql)        AS sql,
                   count(*) FILTER (WHERE d.meeting_scheduled)  AS meeting_scheduled,
                   count(*) FILTER (WHERE d.meeting_held)       AS meeting_held,
                   count(*) FILTER (WHERE d.invoiced)           AS invoiced,
                   count(*) FILTER (WHERE d.sold)               AS sold
              FROM deals d WHERE {where}
             GROUP BY 1""",
        params,
    )
    stages = ["sql", "meeting_scheduled", "meeting_held", "invoiced", "sold"]
    stage_labels = ["Возможности (SQL)", "Назначено встреч", "Проведено встреч",
                    "Выставлено счетов", "Продажи"]
    # только типы, у которых есть хоть один SQL+
    types = [dict(r) for r in rows if any(r[s] for s in stages)]
    types.sort(key=lambda r: r["sql"], reverse=True)
    stage_totals = [sum(t[s] for t in types) for s in stages]

    series = []
    for i, t in enumerate(types):
        series.append({
            "name": short_client_type(t["ct"]),
            "color": client_type_color(t["ct"], i),
            "counts": [t[s] for s in stages],
        })
    return {"stage_labels": stage_labels, "series": series, "stage_totals": stage_totals}


def _source_has_activity(r: dict) -> bool:
    """Есть ли у источника хоть один результат дальше лида или выручка."""
    return bool(r["sql"] or r["meeting_scheduled"] or r["meeting_held"]
                or r["invoiced"] or r["sold"] or r["revenue"])


def by_manager(f: dict) -> dict:
    """Метрики по менеджерам (ТЗ §4, вкладка 3).

    Только количественные метрики и конверсии — cost-метрики (CPL, цена
    встречи/продажи, ROAS) в разрезе менеджеров не считаются: затраты
    привязаны к источнику, а не к менеджеру (ограничение методики §4).
    """
    where, params = _deal_where(f)
    rows = db.query(
        f"""SELECT COALESCE(m.name,
                   CASE WHEN d.responsible_user_id IS NULL THEN '(не назначен)'
                        ELSE 'ID ' || d.responsible_user_id::text END) AS manager,
                {_COUNTS}
             FROM deals d
             LEFT JOIN managers m ON m.amo_user_id = d.responsible_user_id
             WHERE {where} GROUP BY 1 ORDER BY mql DESC""",
        params,
    )
    result_rows = []
    for r in rows:
        r = dict(r)
        r["revenue"] = float(r["revenue"] or 0)
        r["amount"] = 0.0
        r["touches"] = 0
        _add_derived(r)
        result_rows.append(r)

    total = _totals(result_rows, f)
    total["manager"] = "Все менеджеры"
    return {"rows": result_rows, "total": total}


def manager_cards(f: dict) -> dict:
    """Карточки менеджеров: по каждому типу клиента — конверсия MQL→успех и
    средняя длина сделки. Позволяет увидеть, кто с каким типом клиента лучше
    справляется (ТЗ §4, уточнение заказчика). Только менеджеры с активностью
    в выбранном периоде."""
    where, params = _deal_where(f)
    rows = db.query(
        f"""SELECT d.responsible_user_id AS uid,
                   COALESCE(m.name,
                       CASE WHEN d.responsible_user_id IS NULL THEN '(не назначен)'
                            ELSE 'ID ' || d.responsible_user_id::text END) AS manager,
                   COALESCE(NULLIF(d.client_type, ''), '(без типа)') AS ct,
                   count(*)                          AS mql,
                   count(*) FILTER (WHERE d.sold)    AS sold,
                   COALESCE(avg(
                       (EXTRACT(YEAR FROM d.closed_at) * 12 + EXTRACT(MONTH FROM d.closed_at))
                     - (EXTRACT(YEAR FROM d.created_at) * 12 + EXTRACT(MONTH FROM d.created_at))
                     + 1) FILTER (WHERE d.sold AND d.closed_at IS NOT NULL), 0) AS deal_length
              FROM deals d
              LEFT JOIN managers m ON m.amo_user_id = d.responsible_user_id
             WHERE {where}
             GROUP BY 1, 2, 3""",
        params,
    )
    cards: dict = {}
    for r in rows:
        card = cards.setdefault(r["manager"], {"manager": r["manager"],
                                               "mql": 0, "sold": 0, "types": {}})
        card["mql"] += r["mql"]
        card["sold"] += r["sold"]
        card["types"][r["ct"]] = {
            "ct": short_client_type(r["ct"]),
            "color": client_type_color(r["ct"], len(card["types"])),
            "mql": r["mql"], "sold": r["sold"],
            "conv": _div(r["sold"], r["mql"]),
            "deal_length": float(r["deal_length"] or 0),
        }
    out = []
    for card in cards.values():
        card["conv_total"] = _div(card["sold"], card["mql"])
        card["type_list"] = sorted(card["types"].values(),
                                   key=lambda t: t["mql"], reverse=True)
        out.append(card)
    out.sort(key=lambda c: c["mql"], reverse=True)
    return {"cards": out}


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
                COALESCE(sum(d.monthly_payment) FILTER (WHERE d.sold), 0) AS platform_monthly,
                COALESCE(avg(d.monthly_payment) FILTER (WHERE d.sold
                    AND d.monthly_payment IS NOT NULL), 0) AS arppu,
                COALESCE(avg(d.license_months) FILTER (WHERE d.sold), 0) AS lic_months,
                -- длина сделки: число календарных месяцев от создания до закрытия
                -- (включительно): январь→июнь = 6 (по методике заказчика)
                COALESCE(avg(
                    (EXTRACT(YEAR FROM d.closed_at) * 12 + EXTRACT(MONTH FROM d.closed_at))
                  - (EXTRACT(YEAR FROM d.created_at) * 12 + EXTRACT(MONTH FROM d.created_at))
                  + 1
                ) FILTER (WHERE d.sold AND d.closed_at IS NOT NULL), 0) AS deal_length
             FROM deals d
             WHERE {where} AND d.created_at IS NOT NULL
             GROUP BY 1 ORDER BY 1""",
        params,
    )
    ad = _ad_by_month(f)
    op = _opcosts_by_month()

    by_key = {}
    for r in rows:
        r = dict(r)
        _coerce_month(r)
        _add_unit_economics(r, ad.get(r["month"], 0.0), op.get(r["month"]), config)
        _add_step_conversions(r)
        by_key[r["month"]] = r

    # Выбор и порядок отображаемых месяцев
    display = _select_months(by_key, f)
    out = [by_key[m] for m in display]

    total = _month_totals(out, ad, op, config)
    _add_step_conversions(total)

    # Данные для диаграммы конверсий по месяцам (MQL→SQL и SQL→успех)
    chart = {
        "labels": [r["month"] for r in out],
        "mql_sql": [_pct_or_null(r["cr_mql_sql"]) for r in out],
        "sql_won": [_pct_or_null(r["cr_sql_sold"]) for r in out],
    }
    return {"rows": out, "total": total, "chart": chart}


def _pct_or_null(v):
    return round(v * 100, 1) if v is not None else None


def _select_months(by_key: dict, f: dict) -> list:
    """Определяет, какие месяцы показать и в каком порядке."""
    all_months = sorted(by_key)
    if f.get("months"):
        return [m for m in f["months"] if m in by_key]
    if f.get("month_of_year"):
        mm = f"{f['month_of_year']:02d}"
        return [m for m in all_months if m.endswith("-" + mm)]
    return all_months


def _add_step_conversions(r: dict) -> None:
    """Поэтапные конверсии между соседними этапами (§3)."""
    r["cr_mql_sql"] = _div(r["sql"], r["mql"])
    r["cr_sql_scheduled"] = _div(r["meeting_scheduled"], r["sql"])
    r["cr_scheduled_held"] = _div(r["meeting_held"], r["meeting_scheduled"])  # доходимость
    r["cr_held_invoiced"] = _div(r["invoiced"], r["meeting_held"])
    r["cr_invoiced_sold"] = _div(r["sold"], r["invoiced"])
    r["cr_sql_sold"] = _div(r["sold"], r["sql"])       # SQL → успех (для диаграммы)
    r["unqual_pct"] = _div(r["unqualified"], r["mql"])


# Строки транспонированной таблицы «По месяцам»: (тип, подпись, ключ)
# тип: section | num | conv | pct | money | ratio
MONTH_ROWS = [
    ("section", "Воронка", None),
    ("num", "Лиды (MQL)", "mql"),
    ("conv", "MQL → SQL", "cr_mql_sql"),
    ("num", "Возможности (SQL)", "sql"),
    ("conv", "SQL → Встреча назн.", "cr_sql_scheduled"),
    ("num", "Назначено встреч", "meeting_scheduled"),
    ("conv", "Доходимость (назн→пров)", "cr_scheduled_held"),
    ("num", "Проведено встреч", "meeting_held"),
    ("conv", "Встреча → Счёт", "cr_held_invoiced"),
    ("num", "Выставлено счетов", "invoiced"),
    ("conv", "Счёт → Продажа", "cr_invoiced_sold"),
    ("num", "Продажи", "sold"),
    ("conv", "MQL → Продажа", "cr_mql_sale"),
    ("pct", "% неквала", "unqual_pct"),
    ("section", "Экономика", None),
    ("money", "Выручка", "revenue"),
    ("money", "Реклама", "ad_spend"),
    ("money", "Затраты: маркетинг", "marketing_cost"),
    ("money", "Затраты: отдел продаж", "sales_cost"),
    ("money", "Затраты ∑", "total_cost"),
    ("money", "CAC", "cac"),
    ("money", "Средний чек", "avg_check"),
    ("money", "LTV", "ltv"),
    ("ratio", "LTV:CAC", "ltv_cac"),
    ("ratio", "ROAS", "roas"),
    ("dur", "Длина сделки, мес", "deal_length"),
]


def _coerce_month(r: dict) -> None:
    r["revenue"] = float(r["revenue"] or 0)
    r["platform_revenue"] = float(r["platform_revenue"] or 0)
    r["platform_monthly"] = float(r["platform_monthly"] or 0)
    r["arppu"] = float(r["arppu"] or 0)
    r["lic_months"] = float(r["lic_months"] or 0)
    r["deal_length"] = float(r["deal_length"] or 0)


def _add_unit_economics(r: dict, ad_spend: float, oc, config) -> None:
    """CAC / средний чек / LTV / LTV:CAC / ROAS для месяца (по методике заказчика).

    Затраты — прямые месячные тоталы: «Расходы на маркетинг» (уже включает
    рекламу и ЗП маркетинга) и «Расходы на продажи» (ЗП продаж + налоги).
    """
    won = r["sold"]
    marketing_cost = float(oc["cost_marketing"]) if oc else 0.0
    sales_cost = float(oc["cost_sales"]) if oc else 0.0
    total_cost = marketing_cost + sales_cost

    r["ad_spend"] = ad_spend           # реклама по источникам (для ROAS), подмножество маркетинга
    r["marketing_cost"] = marketing_cost
    r["sales_cost"] = sales_cost
    r["total_cost"] = total_cost

    r["cac"] = _div(total_cost, won)
    # средний чек = средний ежемесячный платёж на клиента; LTV = × срок жизни
    r["avg_check"] = _div(r["platform_monthly"], won)
    r["ltv"] = r["avg_check"] * config.LTV_MONTHS if r["avg_check"] is not None else None
    r["ltv_cac"] = _div(r["ltv"], r["cac"]) if r["cac"] else None
    r["roas"] = _div(r["revenue"], ad_spend)
    r["cr_mql_sale"] = _div(won, r["mql"])
    r["reachability"] = _div(r["meeting_held"], r["meeting_scheduled"])


def _month_totals(rows: list, ad: dict, op: dict, config) -> dict:
    keys = ["mql", "sql", "meeting_scheduled", "meeting_held", "invoiced",
            "sold", "unqualified", "revenue", "platform_revenue", "platform_monthly"]
    t = {k: 0 for k in keys}
    for r in rows:
        for k in keys:
            t[k] += r[k] or 0
    t["month"] = "Итого"
    t["arppu"] = _div(sum(r["arppu"] * r["sold"] for r in rows), t["sold"]) or 0
    t["lic_months"] = _div(sum(r["lic_months"] * r["sold"] for r in rows), t["sold"]) or 0
    t["deal_length"] = _div(sum(r["deal_length"] * r["sold"] for r in rows), t["sold"]) or 0
    # суммарные затраты по отображаемым месяцам (только по показанным столбцам)
    shown = {r["month"] for r in rows}
    ad_total = sum(v for m, v in ad.items() if m in shown)
    t["ad_spend"] = ad_total
    t["marketing_cost"] = sum(float(v["cost_marketing"]) for m, v in op.items() if m in shown)
    t["sales_cost"] = sum(float(v["cost_sales"]) for m, v in op.items() if m in shown)
    t["total_cost"] = t["marketing_cost"] + t["sales_cost"]
    t["cac"] = _div(t["total_cost"], t["sold"])
    t["avg_check"] = _div(t["platform_monthly"], t["sold"])
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
        "SELECT to_char(period_month, 'YYYY-MM') AS month, cost_marketing, "
        "cost_sales FROM monthly_costs"
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
    # cost-метрики требуют введённых затрат; без них показываем «—», а не «0 ₽»
    amount = r["amount"]
    if amount:
        r["cpl"] = _div(amount, mql)
        r["price_meeting"] = _div(amount, r["meeting_scheduled"])
        r["price_reached"] = _div(amount, r["meeting_held"])
        r["price_sale"] = _div(amount, r["sold"])
        r["roas"] = _div(r["revenue"], amount)
    else:
        r["cpl"] = r["price_meeting"] = r["price_reached"] = None
        r["price_sale"] = r["roas"] = None
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
    months = db.query(
        """SELECT DISTINCT to_char(date_trunc('month', created_at), 'YYYY-MM') AS m
             FROM deals WHERE created_at IS NOT NULL ORDER BY m DESC"""
    )
    client_types = db.query(
        """SELECT client_type AS ct, count(*) AS n FROM deals
             WHERE client_type IS NOT NULL AND client_type <> ''
             GROUP BY 1 ORDER BY n DESC"""
    )
    return {"managers": managers, "sources": sources,
            "months": [r["m"] for r in months],
            "client_types": [r["ct"] for r in client_types],
            "min_date": bounds["min_d"] if bounds else None,
            "max_date": bounds["max_d"] if bounds else None}


# Цвета типов клиентов для диаграмм и карточек
CLIENT_TYPE_COLORS = {
    "МКК": "#1467F5", "КК": "#00BFDC", "СКК": "#26E0A0",
}
_CT_FALLBACK = ["#F5A623", "#B36BFF", "#F5555A", "#8A8A99"]


def short_client_type(ct: str) -> str:
    """Короткий код типа клиента: «МКК (неключевой до 100)» → «МКК»."""
    import re
    if not ct:
        return ct
    m = re.match(r"^\s*([A-Za-zА-Яа-яЁё]{2,5})\b", ct)
    return m.group(1) if m else ct


def client_type_color(ct: str, idx: int = 0) -> str:
    return CLIENT_TYPE_COLORS.get(short_client_type(ct),
                                  _CT_FALLBACK[idx % len(_CT_FALLBACK)])
