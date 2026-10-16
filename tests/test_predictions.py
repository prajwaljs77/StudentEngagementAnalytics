import json
import math
from datetime import datetime

from backend.services import prediction_service as ps
from extensions import get_db
from tests.conftest import api_post, post


def _run(client, sid, cid):
    return api_post(client, "/api/predictions/run", {"student_id": sid, "course_id": cid})


def test_missing_model_falls_back_to_labelled_baseline(app, faculty, data):
    r = _run(faculty, data["s1"], data["c1"])
    assert r.status_code == 200
    res = r.get_json()["result"]
    assert res["method"] == "rule_based_baseline" and res["model_version"] is None
    assert any("No trained model" in w for w in res["warnings"])
    assert 0 <= res["engagement_score"] <= 100
    assert "Predictions" in faculty.get("/predictions").get_data(as_text=True)
    assert "No trained model available" in faculty.get("/predictions").get_data(as_text=True)


def test_model_prediction_is_stored_and_complete(real_model_app, faculty, data):
    res = _run(faculty, data["s1"], data["c1"]).get_json()["result"]
    assert res["method"] == "ml_model" and res["model_version"]
    assert res["risk_level"] in ("low", "medium", "high") and res["recommendations"] and res["indicators"]
    assert abs(sum(res["probabilities"].values()) - 1) < 1e-3
    datetime.strptime(res["predicted_at"], "%Y-%m-%d %H:%M:%S")
    with real_model_app.app_context():
        row = get_db().one("SELECT * FROM engagement_predictions WHERE prediction_id=%s", [res["prediction_id"]])
    assert row["student_id"] == data["s1"] and row["engagement_score"] == res["engagement_score"]
    assert json.loads(row["features_json"])["login_count_28d"] >= 1


def test_active_student_scores_higher_than_inactive(real_model_app, faculty, data):
    active = _run(faculty, data["s1"], data["c1"]).get_json()["result"]
    idle = _run(faculty, data["s2"], data["c1"]).get_json()["result"]
    assert active["engagement_score"] > idle["engagement_score"]
    assert idle["risk_level"] == "high"
    assert any("no recent activity" in t.lower() or "check in" in t.lower() for t in idle["recommendations"])


def test_student_without_any_activity_gets_warning(app, faculty, data):
    with app.app_context():
        get_db().execute("DELETE FROM activities WHERE student_id=%s", [data["s2"]])
    res = _run(faculty, data["s2"], data["c1"]).get_json()["result"]
    assert any("No activity records" in w for w in res["warnings"])


def test_prediction_authorization_and_validation(student, faculty, data):
    assert _run(student, data["s1"], data["c1"]).status_code == 403
    assert _run(faculty, data["s3"], data["c1"]).status_code == 403   # s3 not in c1
    assert _run(faculty, data["s3"], data["c2"]).status_code == 403   # c2 belongs to another faculty
    assert _run(faculty, "abc", data["c1"]).status_code == 400
    assert _run(faculty, "", "").status_code == 400


def test_corrupt_model_file_handled(app, faculty, data, tmp_path):
    bad = tmp_path / "bad.joblib"
    bad.write_text("not a model")
    app.config["MODEL_PATH"] = str(bad)
    assert not ps.model_status(str(bad))["available"]
    res = _run(faculty, data["s1"], data["c1"]).get_json()["result"]
    assert res["method"] == "rule_based_baseline"


def test_invalid_features_rejected():
    feats = {c: 1.0 for c in ps.FEATURE_COLUMNS}
    ps.validate_features(feats)
    for bad in (float("inf"), -3.0):
        broken = dict(feats, login_count_28d=bad)
        try:
            ps.validate_features(broken)
            raise AssertionError("should have failed")
        except ps.PredictionError:
            pass
    nan_ok = dict(feats, avg_quiz_score=float("nan"))
    ps.validate_features(nan_ok)
    try:
        ps.validate_features(dict(feats, active_days_28d=float("nan")))
        raise AssertionError("should have failed")
    except ps.PredictionError:
        pass


def test_risk_thresholds():
    cfg = {"RISK_HIGH_BELOW": 40, "RISK_MEDIUM_BELOW": 65}
    assert ps.risk_level(39.9, cfg) == "high" and ps.risk_level(40, cfg) == "medium"
    assert ps.risk_level(64.9, cfg) == "medium" and ps.risk_level(65, cfg) == "low"


def test_batch_prediction_and_history_filters(real_model_app, faculty, data):
    r = api_post(faculty, "/api/predictions/batch", {"course_id": data["c1"]})
    assert r.get_json()["predicted"] == 2
    assert api_post(faculty, "/api/predictions/batch", {"course_id": data["c2"]}).status_code == 403
    html = faculty.get("/history").get_data(as_text=True)
    assert "Active Student" in html and "Inactive Student" in html
    only_high = faculty.get("/history.csv?risk=high").get_data(as_text=True)
    assert "Inactive Student" in only_high and "Active Student" not in only_high.replace("Inactive Student", "")
    assert "No predictions match" in faculty.get("/history?risk=low&student_id=%d" % data["s2"]).get_data(as_text=True)
    csv = faculty.get("/history.csv")
    assert csv.mimetype == "text/csv" and "Engagement score" in csv.get_data(as_text=True)


def test_student_history_limited_to_self(real_model_app, faculty, student, data):
    api_post(faculty, "/api/predictions/batch", {"course_id": data["c1"]})
    html = student.get("/history").get_data(as_text=True)
    assert "Course One" in html and "Inactive Student" not in html
    assert "Active Student" in html


def test_alerts_generated_once_and_status_updates(real_model_app, faculty, student, data):
    post(faculty, "/alerts/generate")
    html = faculty.get("/alerts").get_data(as_text=True)
    assert "Inactive Student" in html and "No learning activity" in html
    with real_model_app.app_context():
        n1 = get_db().scalar("SELECT COUNT(*) FROM alerts")
    post(faculty, "/alerts/generate")
    with real_model_app.app_context():
        assert get_db().scalar("SELECT COUNT(*) FROM alerts") == n1   # no duplicates
        aid = get_db().scalar("SELECT alert_id FROM alerts LIMIT 1")
    post(faculty, f"/alerts/{aid}/status", {"status": "resolved"})
    with real_model_app.app_context():
        assert get_db().scalar("SELECT status FROM alerts WHERE alert_id=%s", [aid]) == "resolved"
    assert student.get("/alerts").status_code == 403


def test_student_prediction_page_has_no_run_form(student):
    html = student.get("/predictions").get_data(as_text=True)
    assert 'id="predForm"' not in html
