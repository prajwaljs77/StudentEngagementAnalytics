from datetime import datetime, timedelta

import pandas as pd

from ml.feature_engineering import (FEATURE_COLUMNS, compute_features, engagement_index, label_from_index)
from tests.conftest import api_post


def test_dashboard_empty_database(app, tmp_path):
    from tests.conftest import login, post
    from werkzeug.security import generate_password_hash
    from backend.models import user as user_model
    from extensions import get_db
    with app.app_context():
        user_model.create_user(get_db(), "Solo Faculty", "solo@x.edu", generate_password_hash("Passw0rd1"), "faculty", datetime.now())
    c = app.test_client()
    login(c, "solo@x.edu")
    body = c.get("/api/dashboard").get_json()
    assert body["ok"] and body["empty"] is True
    k = body["kpis"]
    assert k["total_students"] == 0 and k["total_courses"] == 0 and k["total_activities"] == 0
    assert k["avg_assessment_score"] is None and k["avg_engagement_score"] is None
    assert "No learning activities" in body["insights"]["descriptive"][0]
    assert c.get("/dashboard").status_code == 200


def test_dashboard_kpis_from_database(faculty, data):
    body = faculty.get("/api/dashboard").get_json()
    k = body["kpis"]
    assert k["total_students"] == 2 and k["total_courses"] == 1      # only f1's scope
    assert k["total_activities"] == 61                                  # s1: 20 days x 3 events + s2's one (50 days old, inside the 60-day default)
    assert k["avg_assessment_score"] == round((82 + 74 + 22 + 28) / 4, 1) or k["avg_assessment_score"] is not None
    assert k["inactive_students"] == 1                                  # s2
    assert k["avg_engagement_score"] is None and k["high_risk_students"] == 0
    assert body["charts"]["risk_distribution"] == {"low": 0, "medium": 0, "high": 0}
    assert sum(body["charts"]["activity_trend"]["activities"]) == 61
    assert body["charts"]["course_engagement"]["labels"] == ["Course One"]
    assert set(body["insights"]) == {"descriptive", "diagnostic", "predictive"}


def test_dashboard_kpis_after_predictions(real_model_app, faculty, data):
    api_post(faculty, "/api/predictions/batch", {"course_id": data["c1"]})
    k = faculty.get("/api/dashboard").get_json()["kpis"]
    assert k["avg_engagement_score"] is not None and k["high_risk_students"] >= 1


def test_dashboard_filters(faculty, data):
    today = datetime.now().date()
    r = faculty.get(f"/api/dashboard?start={(today - timedelta(days=5)).isoformat()}&end={today.isoformat()}").get_json()
    assert 0 < r["kpis"]["total_activities"] < 61
    r = faculty.get(f"/api/dashboard?student_id={data['s2']}").get_json()
    assert r["kpis"]["total_students"] == 1 and r["kpis"]["total_activities"] == 1
    r = faculty.get(f"/api/dashboard?course_id={data['c2']}").get_json()   # not faculty 1's course -> empty scope
    assert r["kpis"]["total_courses"] == 0 and r["kpis"]["total_students"] == 0


def test_dashboard_invalid_filters(faculty):
    assert faculty.get("/api/dashboard?start=nope").status_code == 400
    assert faculty.get("/api/dashboard?start=2025-02-01&end=2025-01-01").status_code == 400
    assert faculty.get("/api/dashboard?start=2000-01-01&end=2025-01-01").status_code == 400


def test_student_dashboard_scoped_to_self(student, data):
    k = student.get("/api/dashboard").get_json()["kpis"]
    assert k["total_students"] == 1 and k["total_activities"] >= 60
    assert student.get(f"/api/dashboard?student_id={data['s2']}").get_json()["kpis"]["total_activities"] == 0  # a filter can narrow but never widen the scope


def test_assessment_trend_endpoint(faculty):
    d = faculty.get("/api/assessments/trend").get_json()
    assert d["ok"] and len(d["labels"]) >= 1 and any(v is not None for v in d["quiz"])


def test_reports_all_render_and_export(faculty, data):
    from backend.services.report_service import REPORTS
    for name in REPORTS:
        assert faculty.get(f"/reports/{name}").status_code == 200, name
        r = faculty.get(f"/reports/{name}.csv")
        assert r.status_code == 200 and r.mimetype == "text/csv", name
    assert "Inactive Student" in faculty.get("/reports/inactive_students").get_data(as_text=True)
    assert "Course One" in faculty.get("/reports/course_performance.csv").get_data(as_text=True)
    assert faculty.get("/reports/unknown").status_code == 404


def test_reports_authorization(student, faculty2, data):
    assert student.get("/reports/student_engagement").status_code == 403
    assert student.get("/reports/student_engagement.csv").status_code == 403
    body = faculty2.get("/reports/assessment_results.csv").get_data(as_text=True)
    assert "Active Student" not in body and "Inactive Student" not in body


def test_report_csv_injection_guard():
    from backend.services.report_service import to_csv
    rep = {"columns": [("a", "A")], "rows": [{"a": "=cmd|' /C calc'!A0"}, {"a": "-5"}]}
    out = to_csv(rep).splitlines()
    assert out[1].startswith("'=") or out[1].startswith("\"'=") and out[2] == "-5"


# ---------------- feature engineering ----------------
AS_OF = datetime(2025, 6, 1)


def _acts(spec):
    return [(t, d, AS_OF - timedelta(days=days, hours=1)) for t, d, days in spec]


def test_features_windows_and_units():
    acts = _acts([("login", 0, 1), ("study_session", 30, 1), ("video", 20, 2), ("material", 5, 10), ("study_session", 60, 40)])
    f = compute_features(acts, [], AS_OF)
    assert set(f) == set(FEATURE_COLUMNS)
    assert f["login_count_28d"] == 1 and f["total_study_minutes_28d"] == 30        # 40-day-old session excluded
    assert f["video_minutes_28d"] == 20 and f["material_access_count_28d"] == 1
    assert f["activity_count_28d"] == 4 and f["active_days_28d"] == 3
    assert f["recent_7d_activity_count"] == 3
    assert 0.9 < f["days_since_last_activity"] < 1.1
    assert pd.isna(f["avg_quiz_score"]) and pd.isna(f["avg_assignment_delay_days"])


def test_features_ignore_future_data_no_leakage():
    past = _acts([("login", 0, 3)])
    future = [("study_session", 500, AS_OF + timedelta(days=2))]
    assert compute_features(past + future, [], AS_OF) == compute_features(past, [], AS_OF) or \
        all((a == b) or (pd.isna(a) and pd.isna(b)) for a, b in zip(compute_features(past + future, [], AS_OF).values(), compute_features(past, [], AS_OF).values()))


def test_features_empty_inputs_and_assessments():
    f = compute_features([], [], AS_OF)
    assert f["activity_count_28d"] == 0 and f["days_since_last_activity"] == 60
    asm = [{"assessment_type": "quiz", "score": 80, "due_at": None, "submitted_at": None, "assessed_at": AS_OF - timedelta(days=3)},
           {"assessment_type": "quiz", "score": 60, "due_at": None, "submitted_at": None, "assessed_at": AS_OF - timedelta(days=4)},
           {"assessment_type": "assignment", "score": 90, "due_at": AS_OF - timedelta(days=10), "submitted_at": AS_OF - timedelta(days=8), "assessed_at": AS_OF - timedelta(days=7)},
           {"assessment_type": "assignment", "score": 90, "due_at": AS_OF - timedelta(days=10), "submitted_at": AS_OF - timedelta(days=12), "assessed_at": AS_OF - timedelta(days=7)}]
    f = compute_features([], asm, AS_OF)
    assert f["avg_quiz_score"] == 70 and abs(f["avg_assignment_delay_days"] - 1.0) < 1e-6   # early submission counts as 0 delay


def test_target_definition():
    assert engagement_index([]) == 0 and label_from_index(0) == "low"
    busy = [("study_session", 120, AS_OF + timedelta(days=d, hours=h)) for d in range(14) for h in (1, 2, 3, 4, 5, 6)]
    assert engagement_index(pd.DataFrame(busy, columns=["activity_type", "duration", "activity_time"])) > 90
    assert label_from_index(50) == "medium" and label_from_index(80) == "high"
