"""Дашборды (ТЗ §4). Stage 3 — «По источникам»; прочие вкладки — заглушки."""
from flask import Blueprint, redirect, render_template, request, url_for

from ..auth import login_required
from .. import metrics

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
    return _placeholder("months", 4)


@dashboard_bp.route("/dashboard/managers")
@login_required
def managers():
    return _placeholder("managers", 5)


@dashboard_bp.route("/dashboard/costs")
@login_required
def costs():
    return _placeholder("costs", 6)


@dashboard_bp.route("/dashboard/deals")
@login_required
def deals():
    return _placeholder("deals", 8)


@dashboard_bp.route("/dashboard/export")
@login_required
def export():
    return _placeholder("export", 7)
