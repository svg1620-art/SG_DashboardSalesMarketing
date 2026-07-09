"""Заглушки дашбордов. Наполняются на стадиях 3–8 (ТЗ §4)."""
from flask import Blueprint, render_template

from ..auth import login_required

dashboard_bp = Blueprint("dashboard", __name__)

# Вкладки из ТЗ §4 — пока плейсхолдеры, реализуются на следующих стадиях
TABS = [
    {"key": "sources", "title": "Обзор / По источникам", "stage": 3},
    {"key": "months", "title": "По месяцам", "stage": 4},
    {"key": "managers", "title": "По менеджерам", "stage": 5},
    {"key": "costs", "title": "Затраты и касания", "stage": 6},
    {"key": "deals", "title": "Сделки", "stage": 8},
    {"key": "export", "title": "Экспорт", "stage": 7},
]


@dashboard_bp.route("/")
@login_required
def index():
    return render_template("index.html", tabs=TABS)
