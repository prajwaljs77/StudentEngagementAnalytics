"""Application configuration. Every secret/credential comes from environment variables (.env)."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def load_env(path=BASE_DIR / ".env"):
    """Tiny .env reader (KEY=VALUE per line). Real environment variables win."""
    if not Path(path).exists():
        return
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _float(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)  # random per run if unset
    SECRET_KEY_FROM_ENV = bool(os.environ.get("SECRET_KEY"))
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
    PERMANENT_SESSION_LIFETIME_MINUTES = _int("SESSION_LIFETIME_MINUTES", 120)

    DB_BACKEND = "mysql"  # 'sqlite' is used ONLY by the automated tests
    DB_HOST = os.environ.get("DB_HOST", "localhost")
    DB_PORT = _int("DB_PORT", 3306)
    DB_USER = os.environ.get("DB_USER", "root")
    DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
    DB_NAME = os.environ.get("DB_NAME", "student_engagement_db")
    SQLITE_PATH = None

    FACULTY_INVITE_CODE = os.environ.get("FACULTY_INVITE_CODE", "")  # empty = open faculty registration
    MAX_UPLOAD_MB = _int("MAX_UPLOAD_MB", 2)
    MAX_CONTENT_LENGTH = _int("MAX_UPLOAD_MB", 2) * 1024 * 1024
    UPLOAD_FOLDER = str(BASE_DIR / "uploads")

    # Business rules (documented in README)
    ASSESSMENT_MAX_SCORE = _float("ASSESSMENT_MAX_SCORE", 100)
    INACTIVITY_DAYS = _int("INACTIVITY_DAYS", 14)           # no activity for N days => inactive
    LOW_SCORE_THRESHOLD = _float("LOW_SCORE_THRESHOLD", 40)  # consistently low assessment average
    RISK_HIGH_BELOW = _float("RISK_HIGH_BELOW", 40)          # score < 40  => high risk
    RISK_MEDIUM_BELOW = _float("RISK_MEDIUM_BELOW", 65)      # score < 65  => medium risk, else low
    MODEL_PATH = str(BASE_DIR / "ml" / "saved_models" / "engagement_model.joblib")
    PER_PAGE = 10
    LOGIN_MAX_ATTEMPTS = _int("LOGIN_MAX_ATTEMPTS", 5)
    LOGIN_LOCKOUT_MINUTES = _int("LOGIN_LOCKOUT_MINUTES", 10)
    TESTING = False


class TestConfig(Config):
    """Separate configuration for pytest: temporary SQLite file, never your MySQL database."""
    TESTING = True
    SECRET_KEY = "test-only-secret"
    DB_BACKEND = "sqlite"
    FACULTY_INVITE_CODE = "TEST-CODE"
    MODEL_PATH = str(BASE_DIR / "tests" / "_tmp_missing_model.joblib")
