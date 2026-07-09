"""Доступ к PostgreSQL через простой пул соединений psycopg2."""
import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool
from flask import current_app, g

_pool: ThreadedConnectionPool | None = None


def init_pool(database_url: str, minconn: int = 1, maxconn: int = 10) -> None:
    global _pool
    if _pool is None:
        _pool = ThreadedConnectionPool(minconn, maxconn, dsn=database_url)


def _get_pool() -> ThreadedConnectionPool:
    if _pool is None:
        init_pool(current_app.config["DATABASE_URL"])
    assert _pool is not None
    return _pool


def get_conn():
    """Соединение на время запроса, хранится в g."""
    if "db_conn" not in g:
        g.db_conn = _get_pool().getconn()
    return g.db_conn


def put_conn(exception=None) -> None:
    conn = g.pop("db_conn", None)
    if conn is not None:
        if exception is None:
            conn.commit()
        else:
            conn.rollback()
        _get_pool().putconn(conn)


def query(sql: str, params=None, *, fetchone: bool = False):
    """SELECT с возвратом словарей."""
    conn = get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params or ())
        return cur.fetchone() if fetchone else cur.fetchall()


def execute(sql: str, params=None, *, returning: bool = False):
    """INSERT/UPDATE/DELETE. При returning=True возвращает первую строку."""
    conn = get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params or ())
        return cur.fetchone() if returning else None
