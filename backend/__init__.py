"""Flask application factory."""
import logging
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, g, jsonify, render_template, request, session

from config import Config
from extensions import DatabaseUnavailable, close_db, csrf_protect, csrf_token, get_db

ROOT = Path(__file__).resolve().parent.parent


def create_app(config_object=None, overrides=None):
    app = Flask(__name__, template_folder=str(ROOT / "frontend" / "templates"),
                static_folder=str(ROOT / "frontend" / "static"), static_url_path="/static")
    app.config.from_object(config_object or Config)
    app.config.update(overrides or {})
    app.permanent_session_lifetime = timedelta(minutes=app.config["PERMANENT_SESSION_LIFETIME_MINUTES"])
    if not app.config.get("TESTING") and not app.config.get("SECRET_KEY_FROM_ENV"):
        app.logger.warning("SECRET_KEY is not set in .env: using a random key (sessions reset on restart).")

    app.teardown_appcontext(close_db)
    app.before_request(csrf_protect)

    @app.before_request
    def load_user():
        g.user = None
        if "user_id" in session:
            try:
                row = get_db().one("SELECT user_id, name, email, role FROM users WHERE user_id=%s", [session["user_id"]])
            except DatabaseUnavailable:
                row = None
            if row:
                g.user = row
            else:
                session.clear()

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if request.endpoint != "static":
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    @app.context_processor
    def inject():
        from backend.utils.validators import ACTIVITY_TYPES, ASSESSMENT_TYPES
        return {"csrf_token": csrf_token, "current_user": g.get("user"), "ACTIVITY_TYPES": ACTIVITY_TYPES,
                "ASSESSMENT_TYPES": ASSESSMENT_TYPES, "now_year": datetime.now().year,
                "endpoint": request.endpoint or ""}

    @app.template_filter("dt")
    def fmt_dt(value, fmt="%d %b %Y, %H:%M"):
        if not value:
            return "-"
        if isinstance(value, str):
            for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    value = datetime.strptime(value, f)
                    break
                except ValueError:
                    continue
            else:
                return value
        return value.strftime(fmt)

    @app.template_filter("dtinput")
    def fmt_dtinput(value):
        return fmt_dt(value, "%Y-%m-%dT%H:%M") if value else ""

    @app.template_filter("num")
    def fmt_num(value, digits=1):
        return "-" if value is None else f"{float(value):.{digits}f}"

    from backend.routes import (activities, alerts, assessments, auth, courses, dashboard, predictions, reports,
                                students)
    for module in (auth, dashboard, courses, students, activities, assessments, predictions, alerts, reports):
        app.register_blueprint(module.bp)

    def _error(code, title, message):
        if request.path.startswith("/api/"):
            return jsonify(ok=False, error=message), code
        return render_template(f"errors/{code}.html", message=message), code

    @app.errorhandler(400)
    def bad_request(e):
        return _error(400, "Bad request", getattr(e, "description", "Bad request."))

    @app.errorhandler(403)
    def forbidden(e):
        return _error(403, "Forbidden", "You do not have permission to view this page.")

    @app.errorhandler(404)
    def not_found(e):
        return _error(404, "Not found", "The page or record you requested does not exist.")

    @app.errorhandler(413)
    def too_large(e):
        return _error(400, "Too large", "The uploaded file is too large.")

    @app.errorhandler(DatabaseUnavailable)
    def db_down(e):
        logging.getLogger(__name__).error("Database unavailable: %s", e)
        if request.path.startswith("/api/"):
            return jsonify(ok=False, error="Database unavailable."), 503
        return render_template("errors/500.html", message=str(e)), 503

    @app.errorhandler(500)
    def server_error(e):
        return _error(500, "Server error", "Something went wrong on the server. Please try again.")

    return app
