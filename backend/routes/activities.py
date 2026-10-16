from datetime import datetime

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, url_for

from backend.models import activity as activity_model
from backend.models import course as course_model
from backend.models import enrollment as enrollment_model
from backend.services import import_service
from backend.utils import validators as v
from backend.utils.decorators import faculty_required, login_required
from backend.utils.scope import can_access_pair, visible_course_ids, visible_student_ids
from extensions import INTEGRITY_ERRORS, get_db

bp = Blueprint("activities", __name__)


@bp.route("/activities")
@login_required
def index():
    db = get_db()
    cids = visible_course_ids(db, g.user)
    sids = visible_student_ids(db, g.user, cids)
    cid, _ = v.parse_int(request.args.get("course_id") or "0", "Course", 0)
    start, _ = v.parse_datetime(request.args.get("start"), allow_blank=True, allow_future=True)
    end, _ = v.parse_datetime(request.args.get("end"), allow_blank=True, allow_future=True)
    if end and not request.args.get("end", "").strip().count(":"):
        end = end.replace(hour=23, minute=59, second=59)
    atype = request.args.get("type") if request.args.get("type") in v.ACTIVITY_TYPES else None
    page = request.args.get("page", 1)
    rows, total = activity_model.list_activities(
        db, sids, [cid] if cid in cids else cids, atype, start, end, request.args.get("q", "").strip(), page, 10)
    courses, _ = course_model.list_courses(db, cids, per_page=200)
    return render_template("activities.html", activities=rows, total=total, page=int(page or 1), per_page=10, courses=courses,
                           now=datetime.now().strftime("%Y-%m-%dT%H:%M"))


@bp.route("/activities", methods=["POST"])
@login_required
def create():
    db = get_db()
    cid, e1 = v.parse_int(request.form.get("course_id"), "Course", 1)
    sid, e2 = (g.user["user_id"], None) if g.user["role"] == "student" else v.parse_int(request.form.get("student_id"), "Student", 1)
    atype, e3 = v.validate_choice(request.form.get("activity_type"), v.ACTIVITY_TYPES, "activity type")
    duration, e4 = v.parse_duration(request.form.get("duration"), atype or "study_session")
    when, e5 = v.parse_datetime(request.form.get("activity_time"))
    errors = [e for e in (e1, e2, e3, e4, e5) if e]
    if errors:
        flash(" ".join(errors), "danger")
    elif not can_access_pair(db, g.user, sid, cid):
        flash("That student is not enrolled in the selected course (or you do not have access).", "danger")
    elif activity_model.exists(db, sid, cid, atype, when):
        flash("An identical activity record already exists.", "warning")
    else:
        try:
            activity_model.add_activity(db, sid, cid, atype, duration, when, "manual")
            flash("Activity recorded.", "success")
        except INTEGRITY_ERRORS:
            flash("Could not save the activity (duplicate or invalid reference).", "danger")
    return redirect(url_for("activities.index"))


@bp.route("/activities/<int:activity_id>/delete", methods=["POST"])
@login_required
def delete(activity_id):
    db = get_db()
    row = activity_model.get_activity(db, activity_id)
    allowed = row and can_access_pair(db, g.user, row["student_id"], row["course_id"]) and (
        g.user["role"] == "faculty" or (row["source"] == "manual" and row["student_id"] == g.user["user_id"]))
    if not allowed:
        flash("Activity not found or you are not allowed to delete it.", "danger")
    else:
        activity_model.delete_activity(db, activity_id)
        flash("Activity deleted.", "success")
    return redirect(url_for("activities.index"))


@bp.route("/activities/import", methods=["POST"])
@faculty_required
def import_csv():
    try:
        summary = import_service.import_activities(get_db(), current_app.config, g.user, request.files.get("file"))
        flash(f"Import finished: {summary['imported']} imported, {summary['rejected']} rejected.",
              "success" if summary["imported"] else "warning")
        return render_template("import_result.html", summary=summary, kind="activities", back=url_for("activities.index"))
    except import_service.ImportError_ as exc:
        flash(str(exc), "danger")
        return redirect(url_for("activities.index"))
