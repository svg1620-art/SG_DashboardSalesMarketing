"""Дашборды (ТЗ §4). Stages 3–4 — «По источникам», «По месяцам», «Затраты»."""
from flask import (
    Blueprint, current_app, flash, g, redirect, render_template, request, url_for,
)

from ..auth import login_required, role_required
from .. import db, metrics

dashboard_bp = Blueprint("dashboard", __name__)

# Вкладки из ТЗ §4
TABS = [
    {"key": "sources", "title": "Обзор / По источникам", "endpoint": "dashboard.sources"},
    {"key": "months", "title": "По месяцам", "endpoint": "dashboard.months"},
    {"key": "managers", "title": "По менеджерам", "endpoint": "dashboard.managers"},
    {"key": "costs", "title": "Затраты и касания", "endpoint": "dashboard.costs"},
    {"key": "deals", "title": "Сделки", "endpoint": "dashboard.deals"},
    {"key": "export", "title": "Экспорт", "endpoint": "dashboard.export"},
]


@dashboard_bp.route("/")
@login_required
def index():
    return redirect(url_for("dashboard.sources", **request.args))


@dashboard_bp.route("/dashboard/sources")
@login_required
def sources():
    f = metrics.parse_filters(request.args)
    data = metrics.by_source(f)
    return render_template(
        "dashboard/sources.html",
        tabs=TABS, active="sources", filters=f,
        options=metrics.filter_options(),
        rows=data["rows"], total=data["total"], funnel=data["funnel"],
    )


def _placeholder(key: str, stage: int):
    return render_template(
        "dashboard/placeholder.html",
        tabs=TABS, active=key, filters=metrics.parse_filters(request.args),
        options=metrics.filter_options(), stage=stage,
        title=next(t["title"] for t in TABS if t["key"] == key),
    )


@dashboard_bp.route("/dashboard/months")
@login_required
def months():
    f = metrics.parse_filters(request.args)
    data = metrics.by_month(f, current_app.config["APP_CONFIG"])
    return render_template(
        "dashboard/months.html",
        tabs=TABS, active="months", filters=f,
        options=metrics.filter_options(),
        rows=data["rows"], total=data["total"], metric_rows=metrics.MONTH_ROWS,
        chart=data["chart"],
        ltv_months=current_app.config["APP_CONFIG"].LTV_MONTHS,
        show_month_compare=True,
    )


@dashboard_bp.route("/dashboard/managers")
@login_required
def managers():
    f = metrics.parse_filters(request.args)
    data = metrics.by_manager(f)
    return render_template(
        "dashboard/managers.html",
        tabs=TABS, active="managers", filters=f,
        options=metrics.filter_options(),
        rows=data["rows"], total=data["total"],
    )


# --- Затраты и касания (ТЗ §4 вкладка 4, §5: ввод — marketer+) ---

@dashboard_bp.route("/dashboard/costs")
@login_required
def costs():
    touches = db.query(
        """SELECT id, to_char(period_month, 'YYYY-MM') AS month, source,
                  amount, touches, comment
             FROM costs_touches ORDER BY period_month DESC, source"""
    )
    opcosts = db.query(
        """SELECT to_char(period_month, 'YYYY-MM') AS month, cost_marketing,
                  cost_sales, comment
             FROM monthly_costs ORDER BY period_month DESC"""
    )
    sources = db.query("SELECT name FROM sources WHERE is_active ORDER BY name")
    can_edit = g.user["role"] in ("admin", "marketer")
    return render_template(
        "dashboard/costs.html",
        tabs=TABS, active="costs", filters=metrics.parse_filters(request.args),
        options=metrics.filter_options(),
        touches=touches, opcosts=opcosts, sources=sources, can_edit=can_edit,
    )


def _month_to_date(raw: str):
    """'YYYY-MM' → date первого числа месяца."""
    from datetime import datetime
    raw = (raw or "").strip()
    try:
        return datetime.strptime(raw + "-01", "%Y-%m-%d").date()
    except ValueError:
        return None


def _num_or(raw, default=0):
    try:
        return float(str(raw).replace(",", ".").replace(" ", "")) if raw not in (None, "") else default
    except (ValueError, TypeError):
        return default


@dashboard_bp.route("/dashboard/costs/touches", methods=["POST"])
@role_required("marketer")
def costs_touches_save():
    month = _month_to_date(request.form.get("month"))
    source = (request.form.get("source") or "").strip()
    if not month or not source:
        flash("Укажите месяц и источник", "error")
        return redirect(url_for("dashboard.costs"))
    db.execute(
        """INSERT INTO costs_touches (period_month, source, amount, touches, comment, created_by)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT (period_month, source) DO UPDATE
               SET amount = EXCLUDED.amount, touches = EXCLUDED.touches,
                   comment = EXCLUDED.comment, updated_at = now()""",
        (month, source, _num_or(request.form.get("amount")),
         int(_num_or(request.form.get("touches"))),
         (request.form.get("comment") or "").strip() or None, g.user["id"]),
    )
    flash("Затраты сохранены", "success")
    return redirect(url_for("dashboard.costs"))


@dashboard_bp.route("/dashboard/costs/touches/<int:row_id>/delete", methods=["POST"])
@role_required("marketer")
def costs_touches_delete(row_id):
    db.execute("DELETE FROM costs_touches WHERE id = %s", (row_id,))
    flash("Строка удалена", "success")
    return redirect(url_for("dashboard.costs"))


@dashboard_bp.route("/dashboard/costs/operating", methods=["POST"])
@role_required("marketer")
def costs_operating_save():
    month = _month_to_date(request.form.get("month"))
    if not month:
        flash("Укажите месяц", "error")
        return redirect(url_for("dashboard.costs"))
    db.execute(
        """INSERT INTO monthly_costs (period_month, cost_marketing, cost_sales,
               comment, created_by)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (period_month) DO UPDATE
               SET cost_marketing = EXCLUDED.cost_marketing,
                   cost_sales = EXCLUDED.cost_sales,
                   comment = EXCLUDED.comment, updated_at = now()""",
        (month, _num_or(request.form.get("cost_marketing")),
         _num_or(request.form.get("cost_sales")),
         (request.form.get("comment") or "").strip() or None, g.user["id"]),
    )
    flash("Операционные затраты сохранены", "success")
    return redirect(url_for("dashboard.costs"))


@dashboard_bp.route("/dashboard/costs/operating/<month>/delete", methods=["POST"])
@role_required("marketer")
def costs_operating_delete(month):
    d = _month_to_date(month)
    if d:
        db.execute("DELETE FROM monthly_costs WHERE period_month = %s", (d,))
        flash("Строка удалена", "success")
    return redirect(url_for("dashboard.costs"))


@dashboard_bp.route("/dashboard/deals")
@login_required
def deals():
    f = metrics.parse_filters(request.args)
    q = (request.args.get("q") or "").strip()
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    per_page = 50

    # WHERE для сделок: период/менеджер/источник + поиск (без фильтра MQL —
    # это вкладка проверки данных, показываем всё, включая дубли)
    clauses, params = ["TRUE"], []
    if f.get("date_from"):
        clauses.append("d.created_at >= %s"); params.append(f["date_from"])
    if f.get("date_to"):
        clauses.append("d.created_at < %s"); params.append(metrics._next_day(f["date_to"]))
    if f.get("manager_id"):
        clauses.append("d.responsible_user_id = %s"); params.append(f["manager_id"])
    if f.get("source"):
        clauses.append("d.source = %s"); params.append(f["source"])
    if q:
        clauses.append("(d.amo_lead_id::text = %s OR d.source ILIKE %s "
                       "OR d.client_type ILIKE %s)")
        params += [q, f"%{q}%", f"%{q}%"]
    where = " AND ".join(clauses)

    total_count = db.query(f"SELECT count(*) AS n FROM deals d WHERE {where}",
                           params, fetchone=True)["n"]
    rows = db.query(
        f"""SELECT d.amo_lead_id, d.source, d.created_at, d.closed_at, d.price,
                   d.client_type, d.monthly_payment, d.max_stage_reached,
                   d.is_won, d.is_lost, d.stage_source,
                   COALESCE(m.name, '') AS manager,
                   COALESCE(s.name, '') AS status_name
              FROM deals d
              LEFT JOIN managers m ON m.amo_user_id = d.responsible_user_id
              LEFT JOIN pipeline_statuses s ON s.status_id = d.current_status_id
             WHERE {where}
             ORDER BY d.created_at DESC NULLS LAST
             LIMIT %s OFFSET %s""",
        params + [per_page, (page - 1) * per_page],
    )
    pages = max(1, (total_count + per_page - 1) // per_page)
    return render_template(
        "dashboard/deals.html",
        tabs=TABS, active="deals", filters=f, options=metrics.filter_options(),
        rows=rows, q=q, page=page, pages=pages, total_count=total_count,
    )


@dashboard_bp.route("/dashboard/export")
@login_required
def export():
    return render_template(
        "dashboard/export.html",
        tabs=TABS, active="export", filters=metrics.parse_filters(request.args),
        options=metrics.filter_options(),
    )


@dashboard_bp.route("/dashboard/export.xlsx")
@login_required
def export_xlsx():
    from flask import send_file
    from .. import export as export_mod
    f = metrics.parse_filters(request.args)
    buf = export_mod.build_workbook(f, current_app.config["APP_CONFIG"])
    return send_file(
        buf, as_attachment=True,
        download_name="DashboardSalesMarketing.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
