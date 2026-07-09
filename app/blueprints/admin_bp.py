"""Административные операции: проверка amoCRM, синхронизация, пользователи."""
from flask import (
    Blueprint, current_app, flash, g, jsonify, redirect, render_template,
    request, url_for,
)

from ..amocrm import AmoCRMError, client_from_config
from ..auth import hash_password, role_required
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


# --- Управление пользователями (ТЗ §5: только admin) ---

ROLES = ("admin", "marketer", "viewer")
ROLE_LABELS = {"admin": "Администратор", "marketer": "Маркетолог", "viewer": "Читатель"}


@admin_bp.route("/users")
@role_required("admin")
def users():
    rows = db.query(
        "SELECT id, email, role, is_active, created_at FROM app_users ORDER BY created_at"
    )
    return render_template("admin/users.html", users=rows, roles=ROLES,
                           role_labels=ROLE_LABELS)


@admin_bp.route("/users/create", methods=["POST"])
@role_required("admin")
def users_create():
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    role = request.form.get("role") or ""
    if not email or "@" not in email:
        flash("Укажите корректный email", "error")
    elif len(password) < 8:
        flash("Пароль не короче 8 символов", "error")
    elif role not in ROLES:
        flash("Некорректная роль", "error")
    else:
        existing = db.query("SELECT id FROM app_users WHERE email = %s", (email,),
                            fetchone=True)
        if existing:
            flash("Пользователь с таким email уже есть", "error")
        else:
            db.execute(
                "INSERT INTO app_users (email, password_hash, role) VALUES (%s, %s, %s)",
                (email, hash_password(password), role),
            )
            flash(f"Пользователь {email} создан", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/update", methods=["POST"])
@role_required("admin")
def users_update(user_id):
    row = db.query("SELECT id, role, is_active FROM app_users WHERE id = %s",
                   (user_id,), fetchone=True)
    if not row:
        flash("Пользователь не найден", "error")
        return redirect(url_for("admin.users"))

    role = request.form.get("role") or row["role"]
    is_active = request.form.get("is_active") == "on"
    new_password = request.form.get("password") or ""

    # Защита от самоблокировки: нельзя снять с себя админа или деактивировать себя
    if user_id == g.user["id"] and (role != "admin" or not is_active):
        flash("Нельзя понизить или отключить собственную учётку", "error")
        return redirect(url_for("admin.users"))
    if role not in ROLES:
        flash("Некорректная роль", "error")
        return redirect(url_for("admin.users"))

    if new_password:
        if len(new_password) < 8:
            flash("Пароль не короче 8 символов", "error")
            return redirect(url_for("admin.users"))
        db.execute("UPDATE app_users SET password_hash = %s WHERE id = %s",
                   (hash_password(new_password), user_id))

    db.execute("UPDATE app_users SET role = %s, is_active = %s WHERE id = %s",
               (role, is_active, user_id))
    flash("Изменения сохранены", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@role_required("admin")
def users_delete(user_id):
    if user_id == g.user["id"]:
        flash("Нельзя удалить собственную учётку", "error")
        return redirect(url_for("admin.users"))
    db.execute("DELETE FROM app_users WHERE id = %s", (user_id,))
    flash("Пользователь удалён", "success")
    return redirect(url_for("admin.users"))
