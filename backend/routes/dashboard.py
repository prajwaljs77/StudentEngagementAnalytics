from datetime import date, timedelta

from flask import Blueprint, current_app, g, jsonify, render_template, request

from backend.models import course as course_model
from backend.services import analytics_service
from backend.utils import validators as v
from backend.utils.decorators import login_required
from backend.utils.scope import visible_course_ids, visible_student_ids
from backend.utils.sql import in_clause
from extensions import get_db

bp = Blueprint("dashboard", __name__)


def _parse_filters():
    today = date.today()
    start = v.parse_date(request.args.get("start")) if request.args.get("start") else today - timedelta(days=60)
    end = v.parse_date(request.args.get("end")) if request.args.get("end") else today
    if not start or not end:
        return None, "Dates must use the format YYYY-MM-DD."
    if start > end:
        return None, "Start date must not be after the end date."
    if (end - start).days > 730:
        return None, "Please choose a range of at most two years."
    course_id, _ = v.parse_int(request.args.get("course_id") or "0", "Course", 0)
    student_id, _ = v.parse_int(request.args.get("student_id") or "0", "Student", 0)
    return {"start": start, "end": end, "course_id": course_id or None, "student_id": student_id or None}, None


@bp.route("/dashboard")
@login_required
def index():
    db = get_db()
    cids = visible_course_ids(db, g.user)
    courses, _ = course_model.list_courses(db, cids, per_page=200)
    students = []
    if g.user["role"] == "faculty":
        sids = visible_student_ids(db, g.user, cids)
        if sids:
            students = db.all(f"SELECT user_id, name FROM users WHERE {in_clause('user_id', sids)[0]} ORDER BY name", sids)
    today = date.today()
    return render_template("dashboard.html", courses=courses, students=students,
                           default_start=(today - timedelta(days=60)).isoformat(), default_end=today.isoformat())


@bp.route("/api/dashboard")
@login_required
def api_dashboard():
    filters, err = _parse_filters()
    if err:
        return jsonify(ok=False, error=err), 400
    data = analytics_service.dashboard_data(get_db(), current_app.config, g.user, **filters)
    return jsonify(ok=True, **data)


@bp.route("/api/assessments/trend")
@login_required
def api_assessment_trend():
    cid, _ = v.parse_int(request.args.get("course_id") or "0", "Course", 0)
    sid, _ = v.parse_int(request.args.get("student_id") or "0", "Student", 0)
    return jsonify(ok=True, **analytics_service.assessment_trend(get_db(), g.user, cid or None, sid or None))
