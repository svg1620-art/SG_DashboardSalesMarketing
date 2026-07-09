"""Административные операции. На Stage 1 — проверка подключения к amoCRM."""
from flask import Blueprint, current_app, render_template

from ..amocrm import AmoCRMError, client_from_config
from ..auth import role_required

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
    except Exception as exc:  # noqa: BLE001 — показываем любую ошибку admin
        result["error"] = f"Непредвиденная ошибка: {exc}"

    return render_template("admin/amocrm_check.html", result=result)
