"""Database access layer (mysql-connector-python) + CSRF helpers.

All SQL in the project is parameterised with %s placeholders. The tiny SQLite branch exists
only so the automated tests can run without a MySQL server; production uses MySQL.
"""
import hmac
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

from flask import abort, current_app, g, request, session

try:
    import mysql.connector as mysql_connector
except ImportError:  # pragma: no cover
    mysql_connector = None

INTEGRITY_ERRORS = (sqlite3.IntegrityError,) + ((mysql_connector.IntegrityError,) if mysql_connector else ())


class DatabaseUnavailable(Exception):
    """Raised when a database connection cannot be opened."""


class DB:
    def __init__(self, cfg):
        self.backend = cfg["DB_BACKEND"]
        self.in_tx = False
        self.rowcount = 0
        try:
            if self.backend == "sqlite":
                self.conn = sqlite3.connect(cfg["SQLITE_PATH"], check_same_thread=False)
                self.conn.row_factory = sqlite3.Row
                self.conn.execute("PRAGMA foreign_keys = ON")
            else:
                if mysql_connector is None:
                    raise DatabaseUnavailable("mysql-connector-python is not installed. Run: pip install -r requirements.txt")
                self.conn = mysql_connector.connect(
                    host=cfg["DB_HOST"], port=cfg["DB_PORT"], user=cfg["DB_USER"],
                    password=cfg["DB_PASSWORD"], database=cfg["DB_NAME"],
                    charset="utf8mb4", autocommit=False, connection_timeout=8)
        except DatabaseUnavailable:
            raise
        except Exception as exc:
            raise DatabaseUnavailable(f"Could not connect to the database: {exc}") from exc

    # -- helpers -----------------------------------------------------------------
    def _prep(self, sql, params):
        params = list(params or [])
        if self.backend == "sqlite":
            sql = sql.replace("%s", "?")
            params = [p.strftime("%Y-%m-%d %H:%M:%S") if isinstance(p, datetime)
                      else p.isoformat() if isinstance(p, date) else p for p in params]
        return sql, params

    @staticmethod
    def _clean(row):
        return {k: (float(v) if isinstance(v, Decimal) else v) for k, v in dict(row).items()}

    def all(self, sql, params=None):
        sql, params = self._prep(sql, params)
        if self.backend == "sqlite":
            return [self._clean(r) for r in self.conn.execute(sql, params).fetchall()]
        cur = self.conn.cursor(dictionary=True, buffered=True)
        try:
            cur.execute(sql, params)
            return [self._clean(r) for r in cur.fetchall()]
        finally:
            cur.close()
            if not self.in_tx:
                self.conn.rollback()  # end the read snapshot

    def one(self, sql, params=None):
        rows = self.all(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql, params=None, default=None):
        row = self.one(sql, params)
        if not row:
            return default
        value = next(iter(row.values()))
        return default if value is None else value

    def execute(self, sql, params=None):
        sql, params = self._prep(sql, params)
        if self.backend == "sqlite":
            cur = self.conn.execute(sql, params)
        else:
            cur = self.conn.cursor()
            cur.execute(sql, params)
        self.rowcount = cur.rowcount
        last = cur.lastrowid
        if self.backend != "sqlite":
            cur.close()
        if not self.in_tx:
            self.conn.commit()
        return last

    @contextmanager
    def tx(self):
        """Run several statements atomically: commit on success, roll back on any error."""
        self.in_tx = True
        try:
            yield self
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            self.in_tx = False

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass


def get_db():
    if "db" not in g:
        g.db = DB(current_app.config)
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ---------------- CSRF ----------------
def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(24)
    return session["_csrf"]


def csrf_protect():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
        expected = session.get("_csrf", "")
        if not expected or not sent or not hmac.compare_digest(sent, expected):
            abort(400, description="Security token missing or expired. Please reload the page and try again.")
