"""Административные операции: проверка amoCRM, запуск синхронизации, логи."""
from flask import (
    Blueprint, current_app, jsonify, redirect, render_template, url_for,
)

from ..amocrm import AmoCRMError, client_from_config
from ..auth import role_required
from .. import db, sync

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/amocrm-check")
@role_required("admin")
def amocrm_check():
    """Проверка токена, доступности субдомена и глубины истории событий."""
    result = {"ok": False, "account": None, "pipelines": None,
              "events": None, "error": None}
    try:
        cfg = current_app.config["APP_CONFIG"]
        client = client_from_config(cfg)
        account = client.account()
        pipelines = client.pipelines()
        events = client.probe_events_depth()
        result.update(
            ok=True,
            account={
                "id": account.get("id"),
                "name": account.get("name"),
                "subdomain": account.get("subdomain"),
            },
            pipelines=[
                {
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "statuses": [
                        {"id": s.get("id"), "name": s.get("name"), "sort": s.get("sort")}
                        for s in p.get("_embedded", {}).get("statuses", [])
                    ],
                }
                for p in pipelines
            ],
            events=events,
        )
    except AmoCRMError as exc:
        result["error"] = str(exc)
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"Непредвиденная ошибка: {exc}"

    return render_template("admin/amocrm_check.html", result=result)


@admin_bp.route("/sync")
@role_required("marketer")
def sync_page():
    """Страница синхронизации: статус, кнопки, журнал последних запусков."""
    logs = db.query(
        """SELECT id, started_at, finished_at, deals_synced, events_synced,
                  status, message
             FROM sync_log ORDER BY started_at DESC LIMIT 20"""
    )
    stats = db.query(
        """SELECT
             (SELECT count(*) FROM deals) AS deals,
             (SELECT count(*) FROM deal_stage_history) AS events,
             (SELECT count(*) FROM managers) AS managers,
             (SELECT count(*) FROM sources) AS sources,
             (SELECT count(*) FROM pipeline_statuses) AS statuses""",
        fetchone=True,
    )
    return render_template("admin/sync.html", logs=logs, stats=stats,
                           progress=sync.PROGRESS.snapshot())


@admin_bp.route("/sync/run", methods=["POST"])
@role_required("marketer")
def sync_run():
    """Кнопка «Обновить сейчас» — инкрементальный синк (admin/marketer)."""
    started = sync.run_sync_background(current_app.config["APP_CONFIG"], full=False)
    if not started:
        return jsonify({"started": False, "reason": "already_running"}), 409
    return jsonify({"started": True})


@admin_bp.route("/sync/backfill", methods=["POST"])
@role_required("admin")
def sync_backfill():
    """Первичный бэкофилл всей истории (только admin)."""
    started = sync.run_sync_background(current_app.config["APP_CONFIG"], full=True)
    if not started:
        return jsonify({"started": False, "reason": "already_running"}), 409
    return jsonify({"started": True})


@admin_bp.route("/sync/progress")
@role_required("marketer")
def sync_progress():
    """JSON-статус для опроса фронтендом."""
    return jsonify(sync.PROGRESS.snapshot())
