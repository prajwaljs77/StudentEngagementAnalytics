from datetime import datetime

import pandas as pd
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from backend.models import activity as activity_model
from backend.models import assessment as assessment_model
from backend.models import course as course_model
from backend.models import enrollment as enrollment_model
from backend.models import prediction as prediction_model
from backend.models import user as user_model
from backend.utils import validators as v
from backend.utils.decorators import faculty_required, login_required
from backend.utils.scope import can_access_student, visible_course_ids
from extensions import INTEGRITY_ERRORS, get_db

bp = Blueprint("students", __name__)


def _form(require_password):
    name, e1 = v.validate_name(request.form.get("name"))
    email, e2 = v.validate_email(request.form.get("email"))
    pw = request.form.get("password") or ""
    password, e3 = (v.validate_password(pw) if (require_password or pw) else (None, None))
    return name, email, password, [e for e in (e1, e2, e3) if e]


@bp.route("/students")
@faculty_required
def index():
    db = get_db()
    cids = visible_course_ids(db, g.user)
    page = request.args.get("page", 1)
    cid, _ = v.parse_int(request.args.get("course_id") or "0", "Course", 0)
    rows, total = user_model.list_students(db, request.args.get("q", "").strip(), cid if cid in cids else None, page, 10)
    courses, _ = course_model.list_courses(db, cids, per_page=200)
    return render_template("students.html", students=rows, total=total, page=int(page or 1), per_page=10, courses=courses)


@bp.route("/students", methods=["POST"])
@faculty_required
def create():
    name, email, password, errors = _form(True)
    if errors:
        flash(" ".join(errors), "danger")
    else:
        try:
            user_model.create_user(get_db(), name, email, generate_password_hash(password), "student", datetime.now().replace(microsecond=0))
            flash(f"Student '{name}' created.", "success")
        except INTEGRITY_ERRORS:
            flash("A user with this email already exists.", "danger")
    return redirect(url_for("students.index"))


@bp.route("/students/<int:student_id>")
@login_required
def detail(student_id):
    db = get_db()
    student = user_model.get_user(db, student_id)
    if not student or student["role"] != "student":
        abort(404)
    if g.user["role"] == "faculty" and not can_access_student(db, g.user, student_id) and \
            db.scalar("SELECT COUNT(*) FROM enrollments WHERE student_id=%s", [student_id], 0):
        abort(403)  # enrolled elsewhere only: no access to their learning data
    if g.user["role"] == "student" and student_id != g.user["user_id"]:
        abort(403)
    cids = visible_course_ids(db, g.user)
    acts, _ = activity_model.list_activities(db, [student_id], cids, per_page=15)
    asm, _ = assessment_model.list_assessments(db, [student_id], cids, per_page=15)
    preds = prediction_model.latest_predictions(db, [student_id], cids)
    daily = {}
    for a in activity_model.raw_rows(db, [student_id], cids):
        d = pd.to_datetime(a["activity_time"]).strftime("%Y-%m-%d")
        daily[d] = daily.get(d, 0) + (a["duration"] if a["activity_type"] != "login" else 0)
    days = sorted(daily)[-30:]
    return render_template("students.html", detail=True, student=student, courses=enrollment_model.courses_of_student(db, student_id, cids),
                           activities=acts, assessments=asm, predictions=preds, students=[], total=0, page=1, per_page=10,
                           chart={"labels": days, "minutes": [daily[d] for d in days]})


@bp.route("/students/<int:student_id>/edit", methods=["POST"])
@faculty_required
def edit(student_id):
    db = get_db()
    student = user_model.get_user(db, student_id)
    if not student or student["role"] != "student":
        abort(404)
    if user_model.student_taught_by_others(db, g.user["user_id"], student_id):
        abort(403)
    name, email, password, errors = _form(False)
    if errors:
        flash(" ".join(errors), "danger")
    else:
        try:
            user_model.update_user(db, student_id, name, email, generate_password_hash(password) if password else None)
            flash("Student updated.", "success")
        except INTEGRITY_ERRORS:
            flash("Another user already has this email.", "danger")
    return redirect(url_for("students.index"))


@bp.route("/students/<int:student_id>/delete", methods=["POST"])
@faculty_required
def delete(student_id):
    db = get_db()
    student = user_model.get_user(db, student_id)
    if not student or student["role"] != "student":
        abort(404)
    if user_model.student_taught_by_others(db, g.user["user_id"], student_id):
        abort(403)
    deps = {k: n for k, n in user_model.dependency_counts(db, student_id).items() if n}
    if deps:
        flash(f"'{student['name']}' cannot be deleted: related records exist (" +
              ", ".join(f"{n} {k}" for k, n in deps.items()) + ").", "danger")
    else:
        user_model.delete_user(db, student_id)
        flash("Student deleted.", "success")
    return redirect(url_for("students.index"))
