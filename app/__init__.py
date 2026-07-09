"""Фабрика приложения DashboardSales&Marketing."""
from flask import Flask, g

from .config import Config
from . import db, auth


def create_app(config: Config | None = None) -> Flask:
    cfg = config or Config()
    app = Flask(__name__)
    app.config.from_object(cfg)
    app.config["APP_CONFIG"] = cfg

    if cfg.DATABASE_URL:
        db.init_pool(cfg.DATABASE_URL)
        try:
            from .scheduler import init_scheduler
            init_scheduler(cfg)
        except Exception as exc:  # noqa: BLE001 — планировщик не должен ронять веб
            app.logger.warning("Планировщик не запущен: %s", exc)

    # Освобождение соединения и загрузка пользователя
    app.teardown_appcontext(db.put_conn)

    @app.before_request
    def _load_user():
        auth.load_current_user()

    @app.context_processor
    def _inject_globals():
        return {"current_user": getattr(g, "user", None), "app_name": cfg.APP_NAME}

    # --- Jinja-фильтры форматирования чисел (ТЗ §4: числа JetBrains Mono) ---
    @app.template_filter("num")
    def _fmt_num(v):
        if v is None:
            return "—"
        return f"{int(round(v)):,}".replace(",", " ")

    @app.template_filter("money")
    def _fmt_money(v):
        if v is None:
            return "—"
        return f"{int(round(v)):,}".replace(",", " ") + " ₽"

    @app.template_filter("pct")
    def _fmt_pct(v):
        if v is None:
            return "—"
        return f"{v * 100:.1f}%".replace(".", ",")

    @app.template_filter("ratio")
    def _fmt_ratio(v):
        if v is None:
            return "—"
        return f"{v:.2f}".replace(".", ",")

    # Блюпринты
    from .blueprints.dashboard_bp import dashboard_bp
    from .blueprints.admin_bp import admin_bp
    app.register_blueprint(auth.auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(admin_bp)

    @app.route("/healthz")
    def healthz():
        return {"status": "ok", "app": cfg.APP_NAME}

    return app
