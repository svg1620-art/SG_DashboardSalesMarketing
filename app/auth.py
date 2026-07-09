"""Аутентификация (email + пароль, сессии) и контроль ролей."""
import functools
import hashlib
import hmac
import os

from flask import (
    Blueprint, current_app, flash, g, redirect,
    render_template, request, session, url_for,
)

from . import db

auth_bp = Blueprint("auth", __name__)

# Порядок ролей по возрастанию прав
ROLE_LEVEL = {"viewer": 0, "marketer": 1, "admin": 2}


# --- Хэширование паролей (PBKDF2-HMAC-SHA256, соль на пользователя) ---

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"pbkdf2_sha256$200000${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


# --- Текущий пользователь ---

def load_current_user() -> None:
    g.user = None
    user_id = session.get("user_id")
    if user_id is not None:
        g.user = db.query(
            "SELECT id, email, role, is_active FROM app_users WHERE id = %s",
            (user_id,),
            fetchone=True,
        )
        if g.user and not g.user["is_active"]:
            g.user = None
            session.clear()


# --- Декораторы доступа ---

def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if getattr(g, "user", None) is None:
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def role_required(min_role: str):
    def decorator(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            user = getattr(g, "user", None)
            if user is None:
                return redirect(url_for("auth.login", next=request.path))
            if ROLE_LEVEL.get(user["role"], -1) < ROLE_LEVEL[min_role]:
                return render_template("403.html"), 403
            return view(*args, **kwargs)
        return wrapped
    return decorator


# --- Маршруты ---

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if getattr(g, "user", None) is not None:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = db.query(
            "SELECT id, password_hash, is_active FROM app_users WHERE email = %s",
            (email,),
            fetchone=True,
        )
        if user and user["is_active"] and verify_password(password, user["password_hash"]):
            session.clear()
            session["user_id"] = user["id"]
            nxt = request.args.get("next")
            return redirect(nxt if nxt and nxt.startswith("/") else url_for("dashboard.index"))
        flash("Неверный email или пароль", "error")

    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
