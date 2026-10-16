from flask import Blueprint, Response, abort, current_app, g, render_template, request

from backend.models import course as course_model
from backend.services import report_service
from backend.utils import validators as v
from backend.utils.decorators import faculty_required
from backend.utils.scope import visible_course_ids
from extensions import get_db

bp = Blueprint("reports", __name__)


def _args():
    cid, _ = v.parse_int(request.args.get("course_id") or "0", "Course", 0)
    start = v.parse_date(request.args.get("start")) if request.args.get("start") else None
    end = v.parse_date(request.args.get("end")) if request.args.get("end") else None
    return cid or None, start, end


@bp.route("/reports")
@faculty_required
def index():
    db = get_db()
    courses, _ = course_model.list_courses(db, visible_course_ids(db, g.user), per_page=200)
    return render_template("reports.html", reports=report_service.REPORTS, courses=courses, report=None)


@bp.route("/reports/<name>")
@faculty_required
def view(name):
    if name not in report_service.REPORTS:
        abort(404)
    db = get_db()
    cid, start, end = _args()
    report = report_service.build_report(db, current_app.config, g.user, name, cid, start, end)
    courses, _ = course_model.list_courses(db, visible_course_ids(db, g.user), per_page=200)
    return render_template("reports.html", reports=report_service.REPORTS, courses=courses, report=report)


@bp.route("/reports/<name>.csv")
@faculty_required
def csv_export(name):
    if name not in report_service.REPORTS:
        abort(404)
    cid, start, end = _args()
    report = report_service.build_report(get_db(), current_app.config, g.user, name, cid, start, end)
    return Response(report_service.to_csv(report), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={name}.csv"})
