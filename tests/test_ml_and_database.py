import json
import re
import sqlite3
from pathlib import Path

import joblib

import config
from ml import feature_engineering as fe

ROOT = Path(__file__).resolve().parent.parent


def test_dataset_is_valid_and_balanced():
    df = fe.load_dataset()
    assert len(df) >= 500 and set(df["engagement_label"]) == set(fe.CLASSES)
    assert all(c in df.columns for c in fe.FEATURE_COLUMNS)
    assert df["engagement_label"].value_counts(normalize=True).min() > 0.2


def test_split_is_stratified_and_reproducible():
    df = fe.load_dataset()
    a = fe.split_dataset(df)
    b = fe.split_dataset(df)
    assert list(a[1].index) == list(b[1].index)
    train_share = a[2].value_counts(normalize=True)
    test_share = a[3].value_counts(normalize=True)
    assert (train_share - test_share).abs().max() < 0.03


def test_training_pipeline_end_to_end(tmp_path, monkeypatch):
    from ml import train_model
    monkeypatch.setattr(train_model, "MODEL_FILE", tmp_path / "m.joblib")
    monkeypatch.setattr(train_model, "METRICS_FILE", tmp_path / "metrics.json")
    monkeypatch.setattr(train_model, "SAVED_DIR", tmp_path)
    train_model.main()
    bundle = joblib.load(tmp_path / "m.joblib")
    metrics = json.loads((tmp_path / "metrics.json").read_text())
    assert set(metrics["candidates_cv"]) == {"logistic_regression", "random_forest"}   # two candidates compared
    assert metrics["selected_model"] in metrics["candidates_cv"]
    tm = metrics["test_metrics"]
    for key in ("accuracy", "precision_macro", "recall_macro", "f1_macro"):
        assert 0 <= tm[key] <= 1
    assert len(tm["confusion_matrix"]["matrix"]) == 3
    assert bundle["feature_columns"] == fe.FEATURE_COLUMNS and set(bundle["classes"]) == set(fe.CLASSES)
    proba = bundle["pipeline"].predict_proba(fe.load_dataset()[fe.FEATURE_COLUMNS].head(3))
    assert proba.shape == (3, 3)


def test_shipped_model_loads_and_beats_chance():
    path = ROOT / "ml" / "saved_models" / "engagement_model.joblib"
    assert path.exists()
    bundle = joblib.load(path)
    _, X_test, _, y_test = fe.split_dataset(fe.load_dataset())
    assert (bundle["pipeline"].predict(X_test) == y_test).mean() > 0.40   # chance level is ~0.33


def test_model_handles_missing_values():
    bundle = joblib.load(ROOT / "ml" / "saved_models" / "engagement_model.joblib")
    row = {c: 1.0 for c in fe.FEATURE_COLUMNS}
    row["avg_quiz_score"] = float("nan")
    row["avg_assignment_delay_days"] = float("nan")
    assert bundle["pipeline"].predict_proba(fe.to_frame([row])).shape == (1, 3)


# ------------- database & project structure -------------
def test_schema_has_required_tables_and_foreign_keys(app, tmp_path):
    conn = sqlite3.connect(app.config["SQLITE_PATH"])
    tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
    assert {"users", "courses", "enrollments", "activities", "assessments", "engagement_predictions"} <= tables
    fks = lambda t: {(r[2], r[3]) for r in conn.execute(f"pragma foreign_key_list({t})")}
    assert ("users", "faculty_id") in fks("courses")
    assert {("courses", "course_id"), ("users", "student_id")} <= fks("enrollments")
    for t in ("activities", "assessments", "engagement_predictions"):
        assert {("users", "student_id"), ("courses", "course_id")} <= fks(t)


def test_mysql_schema_file_declares_everything():
    sql = (ROOT / "database" / "schema.sql").read_text()
    for t in ("users", "courses", "enrollments", "activities", "assessments", "engagement_predictions", "alerts"):
        assert re.search(rf"CREATE TABLE {t}\b", sql)
    assert sql.count("FOREIGN KEY") >= 12 and "UNIQUE KEY uq_users_email" in sql


def test_foreign_key_blocks_orphan_rows(app, data):
    from extensions import INTEGRITY_ERRORS, get_db
    with app.app_context():
        try:
            get_db().execute("DELETE FROM users WHERE user_id=%s", [data["f1"]])
            raise AssertionError("deleting a faculty with courses must fail")
        except INTEGRITY_ERRORS:
            pass


def test_seed_sql_is_consistent(tmp_path):
    """Translate MySQL date arithmetic to SQLite and load seed.sql into the test schema."""
    sql = (ROOT / "database" / "seed.sql").read_text()
    sql = re.sub(r"NOW\(\) - INTERVAL (\d+) MINUTE", r"datetime('now','-\1 minutes')", sql)
    sql = "\n".join(l for l in sql.splitlines() if not re.match(r"\s*(USE|SET|TRUNCATE)\b", l))
    conn = sqlite3.connect(tmp_path / "seed.db")
    conn.executescript((ROOT / "tests" / "sqlite_schema.sql").read_text())
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(sql)
    q = lambda s: conn.execute(s).fetchone()[0]
    assert q("select count(*) from users where role='faculty'") == 2 and q("select count(*) from users where role='student'") == 18
    assert q("select count(*) from courses") == 4 and q("select count(*) from enrollments") > 20
    assert q("select count(*) from activities") > 1000 and q("select count(*) from assessments") > 20
    assert conn.execute("pragma foreign_key_check").fetchall() == []
    assert q("select count(*) from activities a left join enrollments e on e.student_id=a.student_id and e.course_id=a.course_id where e.enrollment_id is null") == 0


def test_configuration_is_environment_based():
    text = (ROOT / "config.py").read_text()
    assert "os.environ" in text and "DB_PASSWORD" in text
    assert not re.search(r"DB_PASSWORD\s*=\s*['\"][^'\"]+['\"]", text)
    assert (ROOT / ".env.example").exists()


def test_templates_and_static_paths(app):
    required = ["base", "login", "register", "dashboard", "courses", "students", "activities", "assessments",
                "predictions", "alerts", "history", "reports", "errors/403", "errors/404", "errors/500"]
    for name in required:
        assert (ROOT / "frontend" / "templates" / f"{name}.html").exists(), name
    assert Path(app.template_folder) == ROOT / "frontend" / "templates" and Path(app.static_folder) == ROOT / "frontend" / "static"
    c = app.test_client()
    for f in ("css/style.css", "js/script.js", "js/charts.js", "images/logo.svg"):
        assert c.get(f"/static/{f}").status_code == 200, f


def test_error_pages(app, client, data, faculty):
    assert client.get("/nope").status_code == 404
    assert faculty.get("/nope").status_code == 404
    assert "does not exist" in faculty.get("/nope").get_data(as_text=True)
    assert client.get("/api/nope").get_json()["ok"] is False
    assert client.get("/uploads/anything").status_code == 404   # uploads are never served
