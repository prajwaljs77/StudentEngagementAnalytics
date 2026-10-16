"""Shared pytest fixtures. Tests use a throw-away SQLite file in a temp folder (TestConfig) and
can never touch your MySQL database."""
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import create_app  # noqa: E402
from backend.models import activity as activity_model  # noqa: E402
from backend.models import assessment as assessment_model  # noqa: E402
from backend.models import course as course_model  # noqa: E402
from backend.models import enrollment as enrollment_model  # noqa: E402
from backend.models import user as user_model  # noqa: E402
from backend.routes import auth  # noqa: E402
from config import TestConfig  # noqa: E402
from extensions import get_db  # noqa: E402

PASSWORD = "Passw0rd1"
TOKEN = "test-csrf-token"


@pytest.fixture(autouse=True)
def _reset_login_throttle():
    auth._failed.clear()
    yield
    auth._failed.clear()


@pytest.fixture
def app(tmp_path):
    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(db_file)
    conn.executescript((ROOT / "tests" / "sqlite_schema.sql").read_text())
    conn.close()
    return create_app(TestConfig, {"SQLITE_PATH": str(db_file), "UPLOAD_FOLDER": str(tmp_path / "uploads")})


@pytest.fixture
def client(app):
    return app.test_client()


def new_client(app):
    return app.test_client()


def post(client, url, data=None, **kwargs):
    with client.session_transaction() as s:
        s["_csrf"] = TOKEN
    data = dict(data or {})
    data["csrf_token"] = TOKEN
    return client.post(url, data=data, **kwargs)


def api_post(client, url, payload):
    with client.session_transaction() as s:
        s["_csrf"] = TOKEN
    return client.post(url, json=payload, headers={"X-CSRF-Token": TOKEN})


def login(client, email, password=PASSWORD):
    return post(client, "/login", {"email": email, "password": password})


@pytest.fixture
def data(app):
    """Two faculty, three students, two courses and some learning records."""
    now = datetime.now().replace(microsecond=0)
    ids = {}
    with app.app_context():
        db = get_db()
        h = generate_password_hash(PASSWORD)
        ids["f1"] = user_model.create_user(db, "Faculty One", "f1@x.edu", h, "faculty", now)
        ids["f2"] = user_model.create_user(db, "Faculty Two", "f2@x.edu", h, "faculty", now)
        ids["s1"] = user_model.create_user(db, "Active Student", "s1@x.edu", h, "student", now)
        ids["s2"] = user_model.create_user(db, "Inactive Student", "s2@x.edu", h, "student", now)
        ids["s3"] = user_model.create_user(db, "Other Student", "s3@x.edu", h, "student", now)
        ids["c1"] = course_model.create_course(db, "Course One", ids["f1"], "Semester 1", now)
        ids["c2"] = course_model.create_course(db, "Course Two", ids["f2"], "Semester 1", now)
        for s, c in ((ids["s1"], ids["c1"]), (ids["s2"], ids["c1"]), (ids["s3"], ids["c2"])):
            enrollment_model.enroll(db, c, s, now)
        for d in range(20):  # s1: steady activity over the last 20 days
            for kind, dur in (("login", 0), ("study_session", 40), ("video", 20)):
                t = now - timedelta(days=d, hours=1 + (kind == "video"))
                activity_model.add_activity(db, ids["s1"], ids["c1"], kind, dur, t, "manual")
        activity_model.add_activity(db, ids["s2"], ids["c1"], "study_session", 15, now - timedelta(days=50), "manual")
        assessment_model.add_assessment(db, ids["s1"], ids["c1"], 82, "quiz", "Quiz 1", None, None, now - timedelta(days=3))
        assessment_model.add_assessment(db, ids["s1"], ids["c1"], 74, "assignment", "Assignment 1", now - timedelta(days=9),
                                        now - timedelta(days=8), now - timedelta(days=7))
        assessment_model.add_assessment(db, ids["s2"], ids["c1"], 22, "quiz", "Quiz 1", None, None, now - timedelta(days=12))
        assessment_model.add_assessment(db, ids["s2"], ids["c1"], 28, "quiz", "Quiz 2", None, None, now - timedelta(days=5))
    return ids


@pytest.fixture
def faculty(app, data):
    c = app.test_client()
    assert login(c, "f1@x.edu").status_code == 302
    return c


@pytest.fixture
def faculty2(app, data):
    c = app.test_client()
    assert login(c, "f2@x.edu").status_code == 302
    return c


@pytest.fixture
def student(app, data):
    c = app.test_client()
    assert login(c, "s1@x.edu").status_code == 302
    return c


@pytest.fixture
def real_model_app(app):
    """App configured with the trained model shipped in ml/saved_models."""
    app.config["MODEL_PATH"] = str(ROOT / "ml" / "saved_models" / "engagement_model.joblib")
    return app
