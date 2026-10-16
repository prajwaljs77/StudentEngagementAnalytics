from datetime import datetime

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from backend.models import assessment as assessment_model
from backend.models import course as course_model
from backend.services import analytics_service, import_service
from backend.utils import validators as v
from backend.utils.decorators import faculty_required, login_required
from backend.utils.scope import can_access_pair, visible_course_ids, visible_student_ids
from extensions import INTEGRITY_ERRORS, get_db

bp = Blueprint("assessments", __name__)


def _parse_form(student_default=None):
    cfg = current_app.config
    cid, e1 = v.parse_int(request.form.get("course_id"), "Course", 1)
    sid, e2 = v.parse_int(request.form.get("student_id"), "Student", 1)
    atype, e3 = v.validate_choice(request.form.get("assessment_type"), v.ASSESSMENT_TYPES, "assessment type")
    title = v.clean_text(request.form.get("title"), 150)
    e4 = None if title else "Title is required."
    score, e5 = v.parse_score(request.form.get("score"), cfg["ASSESSMENT_MAX_SCORE"])
    due, e6 = v.parse_datetime(request.form.get("due_at"), allow_blank=True, allow_future=True)
    sub, e7 = v.parse_datetime(request.form.get("submitted_at"), allow_blank=True)
    when, e8 = v.parse_datetime(request.form.get("assessed_at"), allow_blank=True)
    e9 = "Provide both due date and submission time, or neither." if (due is None) != (sub is None) else None
    errors = [e for e in (e1, e2, e3, e4, e5, e6, e7, e8, e9) if e]
    return dict(student_id=sid, course_id=cid, score=score, assessment_type=atype, title=title, due_at=due,
                submitted_at=sub, assessed_at=when or datetime.now().replace(microsecond=0)), errors


@bp.route("/assessments")
@login_required
def index():
    db = get_db()
    cfg = current_app.config
    cids = visible_course_ids(db, g.user)
    sids = visible_student_ids(db, g.user, cids)
    cid, _ = v.parse_int(request.args.get("course_id") or "0", "Course", 0)
    use_c = [cid] if cid in cids else cids
    atype = request.args.get("type") if request.args.get("type") in v.ASSESSMENT_TYPES else None
    page = request.args.get("page", 1)
    q = request.args.get("q", "").strip()
    rows, total = assessment_model.list_assessments(db, sids, use_c, atype, search=q, page=page, per_page=10)
    courses, _ = course_model.list_courses(db, cids, per_page=200)
    return render_template("assessments.html", assessments=rows, total=total, page=int(page or 1), per_page=10, courses=courses,
                           summary=analytics_service.assessment_summary(db, sids, use_c),
                           low=analytics_service.low_performers(db, cfg, sids, use_c),
                           max_score=cfg["ASSESSMENT_MAX_SCORE"], low_threshold=cfg["LOW_SCORE_THRESHOLD"])


@bp.route("/assessments", methods=["POST"])
@faculty_required
def create():
    db = get_db()
    data, errors = _parse_form()
    if errors:
        flash(" ".join(errors), "danger")
    elif not can_access_pair(db, g.user, data["student_id"], data["course_id"]):
        flash("That student is not enrolled in one of your courses.", "danger")
    elif assessment_model.exists(db, data["student_id"], data["course_id"], data["assessment_type"], data["title"]):
        flash("This student already has an assessment with the same type and title.", "warning")
    else:
        try:
            assessment_model.add_assessment(db, **data)
            flash("Assessment saved.", "success")
        except INTEGRITY_ERRORS:
            flash("Could not save the assessment (duplicate or invalid reference).", "danger")
    return redirect(url_for("assessments.index"))


@bp.route("/assessments/<int:assessment_id>/edit", methods=["POST"])
@faculty_required
def edit(assessment_id):
    db = get_db()
    row = assessment_model.get_assessment(db, assessment_id)
    if not row:
        abort(404)
    if not can_access_pair(db, g.user, row["student_id"], row["course_id"]):
        abort(403)
    data, errors = _parse_form()
    data.update(student_id=row["student_id"], course_id=row["course_id"])  # identity cannot be changed
    errors = [e for e in errors if "Course" not in e and "Student" not in e]
    if errors:
        flash(" ".join(errors), "danger")
    elif assessment_model.exists(db, row["student_id"], row["course_id"], data["assessment_type"], data["title"], exclude_id=assessment_id):
        flash("Another assessment with the same type and title exists for this student.", "warning")
    else:
        assessment_model.update_assessment(db, assessment_id, data["score"], data["assessment_type"], data["title"],
                                           data["due_at"], data["submitted_at"], data["assessed_at"])
        flash("Assessment updated.", "success")
    return redirect(url_for("assessments.index"))


@bp.route("/assessments/<int:assessment_id>/delete", methods=["POST"])
@faculty_required
def delete(assessment_id):
    db = get_db()
    row = assessment_model.get_assessment(db, assessment_id)
    if not row:
        abort(404)
    if not can_access_pair(db, g.user, row["student_id"], row["course_id"]):
        abort(403)
    assessment_model.delete_assessment(db, assessment_id)
    flash("Assessment deleted.", "success")
    return redirect(url_for("assessments.index"))


@bp.route("/assessments/import", methods=["POST"])
@faculty_required
def import_csv():
    try:
        summary = import_service.import_assessments(get_db(), current_app.config, g.user, request.files.get("file"))
        flash(f"Import finished: {summary['imported']} imported, {summary['rejected']} rejected.",
              "success" if summary["imported"] else "warning")
        return render_template("import_result.html", summary=summary, kind="assessments", back=url_for("assessments.index"))
    except import_service.ImportError_ as exc:
        flash(str(exc), "danger")
        return redirect(url_for("assessments.index"))
