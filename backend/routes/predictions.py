import json
from pathlib import Path

from flask import Blueprint, Response, current_app, g, jsonify, render_template, request

from backend.models import course as course_model
from backend.models import enrollment as enrollment_model
from backend.models import prediction as prediction_model
from backend.services import prediction_service, report_service
from backend.utils import validators as v
from backend.utils.decorators import faculty_required, login_required
from backend.utils.scope import can_access_pair, visible_course_ids, visible_student_ids
from extensions import get_db
from ml.feature_engineering import METRICS_FILE

bp = Blueprint("predictions", __name__)


def _metrics():
    try:
        return json.loads(Path(METRICS_FILE).read_text())
    except (OSError, ValueError):
        return None


@bp.route("/predictions")
@login_required
def index():
    db = get_db()
    cfg = current_app.config
    cids = visible_course_ids(db, g.user)
    courses, _ = course_model.list_courses(db, cids, per_page=200)
    latest = prediction_model.latest_predictions(db, visible_student_ids(db, g.user, cids), cids)
    return render_template("predictions.html", courses=courses, latest=latest, status=prediction_service.model_status(cfg["MODEL_PATH"]),
                           metrics=_metrics(), high_below=cfg["RISK_HIGH_BELOW"], medium_below=cfg["RISK_MEDIUM_BELOW"])


@bp.route("/api/predictions/run", methods=["POST"])
@faculty_required
def api_run():
    payload = request.get_json(silent=True) or request.form
    sid, e1 = v.parse_int(payload.get("student_id"), "Student", 1)
    cid, e2 = v.parse_int(payload.get("course_id"), "Course", 1)
    if e1 or e2:
        return jsonify(ok=False, error=e1 or e2), 400
    db = get_db()
    if not can_access_pair(db, g.user, sid, cid):
        return jsonify(ok=False, error="This student is not enrolled in one of your courses."), 403
    try:
        result = prediction_service.predict(db, current_app.config, sid, cid, store=True)
    except prediction_service.PredictionError as exc:
        return jsonify(ok=False, error=f"Invalid feature data: {exc}"), 422
    return jsonify(ok=True, result=result)


@bp.route("/api/predictions/batch", methods=["POST"])
@faculty_required
def api_batch():
    payload = request.get_json(silent=True) or request.form
    cid, err = v.parse_int(payload.get("course_id"), "Course", 1)
    db = get_db()
    if err:
        return jsonify(ok=False, error=err), 400
    if cid not in visible_course_ids(db, g.user):
        return jsonify(ok=False, error="Course not found or not permitted."), 403
    done = failed = 0
    with db.tx():
        for p in enrollment_model.pairs(db, [cid]):
            try:
                prediction_service.predict(db, current_app.config, p["student_id"], cid, store=True)
                done += 1
            except prediction_service.PredictionError:
                failed += 1
    return jsonify(ok=True, predicted=done, failed=failed)


def _history_args():
    db = get_db()
    cids = visible_course_ids(db, g.user)
    sids = visible_student_ids(db, g.user, cids)
    sid, _ = v.parse_int(request.args.get("student_id") or "0", "Student", 0)
    cid, _ = v.parse_int(request.args.get("course_id") or "0", "Course", 0)
    risk = request.args.get("risk") if request.args.get("risk") in ("low", "medium", "high") else None
    start, _ = v.parse_datetime(request.args.get("start"), allow_blank=True, allow_future=True)
    end, _ = v.parse_datetime(request.args.get("end"), allow_blank=True, allow_future=True)
    if end and ":" not in request.args.get("end", ""):
        end = end.replace(hour=23, minute=59, second=59)
    return db, cids, sids, dict(student_id=sid if sid in sids else None, course_id=cid if cid in cids else None,
                                risk=risk, start=start, end=end)


@bp.route("/history")
@login_required
def history():
    db, cids, sids, f = _history_args()
    page = request.args.get("page", 1)
    rows, total = prediction_model.list_history(db, sids, cids, page=page, per_page=10, **f)
    courses, _ = course_model.list_courses(db, cids, per_page=200)
    student_opts = db.all("SELECT user_id, name FROM users WHERE user_id IN (%s) ORDER BY name" % ",".join(["%s"] * len(sids)), sids) if sids and g.user["role"] == "faculty" else []
    return render_template("history.html", history=rows, total=total, page=int(page or 1), per_page=10, courses=courses, student_opts=student_opts)


@bp.route("/history.csv")
@login_required
def history_csv():
    db, cids, sids, f = _history_args()
    rows, _ = prediction_model.list_history(db, sids, cids, paginate=False, **f)
    report = {"columns": [("student_name", "Student"), ("course_name", "Course"), ("engagement_score", "Engagement score"),
                          ("risk_level", "Risk level"), ("method", "Method"), ("predicted_at", "Predicted at")], "rows": rows}
    return Response(report_service.to_csv(report), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=prediction_history.csv"})
