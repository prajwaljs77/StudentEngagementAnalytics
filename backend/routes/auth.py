import time
from datetime import datetime

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from backend.models import activity as activity_model
from backend.models import enrollment as enrollment_model
from backend.models import user as user_model
from backend.utils import validators as v
from backend.utils.decorators import login_required
from extensions import INTEGRITY_ERRORS, get_db

bp = Blueprint("auth", __name__)
_failed = {}  # (email, ip) -> [timestamps]   (in-memory throttle; resets on restart)
_DUMMY_HASH = generate_password_hash("dummy-password-for-timing")


def _locked(key):
    cfg = current_app.config
    window = cfg["LOGIN_LOCKOUT_MINUTES"] * 60
    attempts = [t for t in _failed.get(key, []) if time.time() - t < window]
    _failed[key] = attempts
    return len(attempts) >= cfg["LOGIN_MAX_ATTEMPTS"]


def _safe_next(target):
    return target if target and target.startswith("/") and not target.startswith("//") else None


@bp.route("/")
def index():
    return redirect(url_for("dashboard.index" if g.user else "auth.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        email, _ = v.validate_email(request.form.get("email"))
        password = request.form.get("password") or ""
        key = ((email or request.form.get("email", "")).lower(), request.remote_addr)
        if _locked(key):
            flash("Too many failed attempts. Please wait a few minutes and try again.", "danger")
            return render_template("login.html"), 429
        db = get_db()
        user = user_model.get_by_email(db, email) if email else None
        ok = check_password_hash(user["password_hash"] if user else _DUMMY_HASH, password) and user is not None
        if not ok:
            _failed.setdefault(key, []).append(time.time())
            flash("Invalid email or password.", "danger")  # same message for unknown email / wrong password
            return render_template("login.html"), 401
        _failed.pop(key, None)
        session.clear()
        session.permanent = True
        session.update(user_id=user["user_id"], role=user["role"], name=user["name"])
        if user["role"] == "student":  # genuine system-captured login events (one per enrolled course)
            now = datetime.now().replace(microsecond=0)
            for c in enrollment_model.courses_of_student(db, user["user_id"]):
                try:
                    activity_model.add_activity(db, user["user_id"], c["course_id"], "login", 0, now, "system")
                except INTEGRITY_ERRORS:
                    pass
        flash(f"Welcome back, {user['name']}!", "success")
        return redirect(_safe_next(request.args.get("next")) or url_for("dashboard.index"))
    return render_template("login.html")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("dashboard.index"))
    form, errors = {}, {}
    if request.method == "POST":
        cfg = current_app.config
        form = {k: request.form.get(k, "") for k in ("name", "email", "role")}
        name, errors["name"] = v.validate_name(request.form.get("name"))
        email, errors["email"] = v.validate_email(request.form.get("email"))
        password, errors["password"] = v.validate_password(request.form.get("password"))
        role, errors["role"] = v.validate_role(request.form.get("role"))
        if request.form.get("password") != request.form.get("confirm_password"):
            errors["confirm_password"] = "Passwords do not match."
        if role == "faculty" and cfg["FACULTY_INVITE_CODE"] and request.form.get("invite_code") != cfg["FACULTY_INVITE_CODE"]:
            errors["invite_code"] = "Invalid faculty invitation code."
        errors = {k: m for k, m in errors.items() if m}
        if not errors:
            db = get_db()
            try:
                user_model.create_user(db, name, email, generate_password_hash(password), role, datetime.now().replace(microsecond=0))
                flash("Account created. You can now log in.", "success")
                return redirect(url_for("auth.login"))
            except INTEGRITY_ERRORS:
                errors["email"] = "An account with this email already exists."
        return render_template("register.html", form=form, errors=errors,
                               invite_required=bool(cfg["FACULTY_INVITE_CODE"])), 400
    return render_template("register.html", form=form, errors=errors, invite_required=bool(current_app.config["FACULTY_INVITE_CODE"]))


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
