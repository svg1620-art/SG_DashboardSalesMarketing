"""Идемпотентный запуск SQL-миграций + опциональный bootstrap администратора.

Использование:
    python scripts/migrate.py                 # применить новые миграции
    python scripts/migrate.py --create-admin  # + создать/обновить админа из env
"""
import os
import sys

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config          # noqa: E402
from app.auth import hash_password      # noqa: E402

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "migrations")


def _ensure_migrations_table(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename   TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def run_migrations(conn) -> None:
    with conn.cursor() as cur:
        _ensure_migrations_table(cur)
        cur.execute("SELECT filename FROM schema_migrations")
        applied = {row[0] for row in cur.fetchall()}

        files = sorted(f for f in os.listdir(MIGRATIONS_DIR) if f.endswith(".sql"))
        for fname in files:
            if fname in applied:
                continue
            path = os.path.join(MIGRATIONS_DIR, fname)
            with open(path, encoding="utf-8") as fh:
                cur.execute(fh.read())
            cur.execute(
                "INSERT INTO schema_migrations (filename) VALUES (%s)", (fname,)
            )
            print(f"  applied: {fname}")
        if not files:
            print("  нет файлов миграций")
    conn.commit()


def bootstrap_admin(conn, cfg: Config) -> None:
    email = cfg.BOOTSTRAP_ADMIN_EMAIL
    password = cfg.BOOTSTRAP_ADMIN_PASSWORD
    if not email or not password:
        print("  BOOTSTRAP_ADMIN_EMAIL/PASSWORD не заданы — пропуск")
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO app_users (email, password_hash, role)
            VALUES (%s, %s, 'admin')
            ON CONFLICT (email) DO UPDATE
                SET password_hash = EXCLUDED.password_hash,
                    role = 'admin',
                    is_active = TRUE
            """,
            (email.strip().lower(), hash_password(password)),
        )
    conn.commit()
    print(f"  админ готов: {email}")


def main() -> int:
    cfg = Config()
    if not cfg.DATABASE_URL:
        print("DATABASE_URL не задан", file=sys.stderr)
        return 1

    conn = psycopg2.connect(cfg.DATABASE_URL)
    try:
        print("Миграции:")
        run_migrations(conn)
        if "--create-admin" in sys.argv:
            print("Bootstrap администратора:")
            bootstrap_admin(conn, cfg)
    finally:
        conn.close()
    print("Готово.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
