from backend.models import user as user_model
from extensions import get_db
from tests.conftest import PASSWORD, TOKEN, login, post


def test_register_student_and_login(app, client):
    r = post(client, "/register", {"name": "New Student", "email": "new@x.edu", "password": PASSWORD,
                                   "confirm_password": PASSWORD, "role": "student"})
    assert r.status_code == 302
    with app.app_context():
        row = user_model.get_by_email(get_db(), "new@x.edu")
        assert row["password_hash"] != PASSWORD and row["password_hash"].startswith(("scrypt:", "pbkdf2:"))
    assert login(client, "new@x.edu").status_code == 302
    assert client.get("/dashboard").status_code == 200


def test_register_validation_errors(client):
    r = post(client, "/register", {"name": "A", "email": "bad", "password": "short", "confirm_password": "x", "role": "student"})
    assert r.status_code == 400
    html = r.get_data(as_text=True)
    assert "valid email" in html and "at least 8" in html and "do not match" in html


def test_duplicate_email_rejected(client, data):
    r = post(client, "/register", {"name": "Dup", "email": "s1@x.edu", "password": PASSWORD, "confirm_password": PASSWORD, "role": "student"})
    assert r.status_code == 400 and "already exists" in r.get_data(as_text=True)


def test_faculty_registration_needs_invite_code(client):
    base = {"name": "Prof New", "email": "prof@x.edu", "password": PASSWORD, "confirm_password": PASSWORD, "role": "faculty"}
    assert post(client, "/register", base).status_code == 400
    assert post(client, "/register", {**base, "invite_code": "TEST-CODE"}).status_code == 302


def test_login_wrong_password_generic_message(client, data):
    r = login(client, "s1@x.edu", "WrongPass1")
    assert r.status_code == 401 and "Invalid email or password" in r.get_data(as_text=True)
    r2 = login(client, "nobody@x.edu")
    assert r2.status_code == 401 and "Invalid email or password" in r2.get_data(as_text=True)


def test_login_lockout_after_repeated_failures(client, data):
    for _ in range(5):
        login(client, "s1@x.edu", "WrongPass1")
    assert login(client, "s1@x.edu").status_code == 429


def test_logout_and_protected_routes(app, data):
    c = app.test_client()
    assert c.get("/dashboard").status_code == 302
    assert c.get("/api/dashboard").status_code == 401
    login(c, "s1@x.edu")
    assert c.get("/dashboard").status_code == 200
    assert post(c, "/logout").status_code == 302
    assert c.get("/dashboard").status_code == 302


def test_csrf_required_on_post(client, data):
    r = client.post("/login", data={"email": "s1@x.edu", "password": PASSWORD})
    assert r.status_code == 400


def test_open_redirect_blocked(client, data):
    with client.session_transaction() as s:
        s["_csrf"] = TOKEN
    r = client.post("/login?next=//evil.example", data={"email": "s1@x.edu", "password": PASSWORD, "csrf_token": TOKEN})
    assert r.status_code == 302 and "evil" not in r.headers["Location"]


def test_student_login_records_system_activity(app, student, data):
    with app.app_context():
        n = get_db().scalar("SELECT COUNT(*) FROM activities WHERE source='system' AND student_id=%s", [data["s1"]])
    assert n == 1


def test_role_restrictions(student, faculty):
    for url in ("/students", "/alerts", "/reports"):
        assert student.get(url).status_code == 403
        assert faculty.get(url).status_code == 200


def test_session_cookie_flags(app):
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True and app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
