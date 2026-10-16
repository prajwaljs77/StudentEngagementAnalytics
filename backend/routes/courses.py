from datetime import datetime

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for

from backend.models import course as course_model
from backend.models import enrollment as enrollment_model
from backend.models import user as user_model
from backend.utils import validators as v
from backend.utils.decorators import faculty_required, login_required
from backend.utils.scope import can_access_course, visible_course_ids
from extensions import INTEGRITY_ERRORS, get_db

bp = Blueprint("courses", __name__)


def _course_form(db):
    name, e1 = v.validate_course_name(request.form.get("course_name"))
    semester, e2 = v.validate_semester(request.form.get("semester"))
    fid, e3 = v.parse_int(request.form.get("faculty_id") or g.user["user_id"], "Faculty", 1)
    errors = [e for e in (e1, e2, e3) if e]
    if not errors:
        f = user_model.get_user(db, fid)
        if not f or f["role"] != "faculty":
            errors.append("Selected faculty member does not exist.")
    return name, semester, fid, errors


def _owned_course_or_404(db, course_id):
    course = course_model.get_course(db, course_id)
    if not course or not can_access_course(db, g.user, course_id):
        abort(404 if not course else 403)
    return course


@bp.route("/courses")
@login_required
def index():
    db = get_db()
    cids = visible_course_ids(db, g.user)
    rows, total = course_model.list_courses(db, cids, request.args.get("q", "").strip(), request.args.get("semester") or None,
                                            request.args.get("page", 1), 10)
    return render_template("courses.html", courses=rows, total=total, page=int(request.args.get("page", 1) or 1), per_page=10,
                           semesters=course_model.semesters(db, cids), faculty_list=user_model.list_faculty(db))


@bp.route("/courses", methods=["POST"])
@faculty_required
def create():
    db = get_db()
    name, semester, fid, errors = _course_form(db)
    if errors:
        flash(" ".join(errors), "danger")
        return redirect(url_for("courses.index"))
    try:
        course_model.create_course(db, name, fid, semester, datetime.now().replace(microsecond=0))
        flash(f"Course '{name}' created.", "success")
    except INTEGRITY_ERRORS:
        flash("A course with this name already exists.", "danger")
    return redirect(url_for("courses.index"))


@bp.route("/courses/<int:course_id>")
@login_required
def detail(course_id):
    db = get_db()
    course = _owned_course_or_404(db, course_id)
    students = enrollment_model.students_in_course(db, course_id) if g.user["role"] == "faculty" else []
    available = enrollment_model.unenrolled_students(db, course_id) if g.user["role"] == "faculty" else []
    return render_template("courses.html", course=course, students=students, available=available, detail=True,
                           faculty_list=user_model.list_faculty(db), courses=[], total=0, page=1, per_page=10, semesters=[])


@bp.route("/courses/<int:course_id>/edit", methods=["POST"])
@faculty_required
def edit(course_id):
    db = get_db()
    _owned_course_or_404(db, course_id)
    name, semester, fid, errors = _course_form(db)
    if errors:
        flash(" ".join(errors), "danger")
        return redirect(url_for("courses.index"))
    try:
        course_model.update_course(db, course_id, name, fid, semester)
        flash("Course updated.", "success")
    except INTEGRITY_ERRORS:
        flash("Another course already uses this name.", "danger")
    return redirect(url_for("courses.index"))


@bp.route("/courses/<int:course_id>/delete", methods=["POST"])
@faculty_required
def delete(course_id):
    db = get_db()
    course = _owned_course_or_404(db, course_id)
    deps = {k: n for k, n in course_model.dependency_counts(db, course_id).items() if n}
    if deps:
        detail = ", ".join(f"{n} {k}" for k, n in deps.items())
        flash(f"'{course['course_name']}' cannot be deleted because it still has related records ({detail}). "
              "Remove or move those records first.", "danger")
        return redirect(url_for("courses.index"))
    try:
        course_model.delete_course(db, course_id)
        flash("Course deleted.", "success")
    except INTEGRITY_ERRORS:
        flash("Course could not be deleted because other records depend on it.", "danger")
    return redirect(url_for("courses.index"))


@bp.route("/courses/<int:course_id>/enroll", methods=["POST"])
@faculty_required
def enroll(course_id):
    db = get_db()
    _owned_course_or_404(db, course_id)
    sid, err = v.parse_int(request.form.get("student_id"), "Student", 1)
    student = user_model.get_user(db, sid) if not err else None
    if not student or student["role"] != "student":
        flash("Please choose a valid student.", "danger")
    else:
        try:
            enrollment_model.enroll(db, course_id, sid, datetime.now().replace(microsecond=0))
            flash(f"{student['name']} enrolled.", "success")
        except INTEGRITY_ERRORS:
            flash("That student is already enrolled.", "warning")
    return redirect(url_for("courses.detail", course_id=course_id))


@bp.route("/courses/<int:course_id>/unenroll", methods=["POST"])
@faculty_required
def unenroll(course_id):
    db = get_db()
    _owned_course_or_404(db, course_id)
    sid, err = v.parse_int(request.form.get("student_id"), "Student", 1)
    if err or not enrollment_model.is_enrolled(db, sid, course_id):
        flash("Enrollment not found.", "danger")
        return redirect(url_for("courses.detail", course_id=course_id))
    linked = db.scalar("SELECT (SELECT COUNT(*) FROM activities WHERE student_id=%s AND course_id=%s) + "
                       "(SELECT COUNT(*) FROM assessments WHERE student_id=%s AND course_id=%s)", [sid, course_id, sid, course_id], 0)
    if linked:
        flash(f"Cannot remove this student: {int(linked)} activity/assessment record(s) exist for the course. "
              "Their learning history is kept for consistency.", "danger")
    else:
        enrollment_model.unenroll(db, course_id, sid)
        flash("Student removed from the course.", "success")
    return redirect(url_for("courses.detail", course_id=course_id))


@bp.route("/api/courses/<int:course_id>/students")
@login_required
def api_students(course_id):
    db = get_db()
    if not can_access_course(db, g.user, course_id):
        return jsonify(ok=False, error="Course not found or not permitted."), 403
    rows = enrollment_model.students_in_course(db, course_id)
    if g.user["role"] == "student":
        rows = [r for r in rows if r["user_id"] == g.user["user_id"]]
    return jsonify(ok=True, students=[{"id": r["user_id"], "name": r["name"]} for r in rows])
