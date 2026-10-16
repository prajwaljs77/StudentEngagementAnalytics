from datetime import datetime

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, url_for

from backend.models import alert as alert_model
from backend.services import alert_service
from backend.utils.decorators import faculty_required
from backend.utils.scope import can_access_pair, visible_course_ids, visible_student_ids
from extensions import get_db

bp = Blueprint("alerts", __name__)


@bp.route("/alerts")
@faculty_required
def index():
    db = get_db()
    cids = visible_course_ids(db, g.user)
    sids = visible_student_ids(db, g.user, cids)
    status = request.args.get("status", "open")
    status = status if status in ("open", "acknowledged", "resolved") else None
    risk = request.args.get("risk") if request.args.get("risk") in ("medium", "high") else None
    page = request.args.get("page", 1)
    rows, total = alert_model.list_alerts(db, sids, cids, status, risk, page, 10)
    return render_template("alerts.html", alerts=rows, total=total, page=int(page or 1), per_page=10, status=status or "")


@bp.route("/alerts/generate", methods=["POST"])
@faculty_required
def generate():
    db = get_db()
    cids = visible_course_ids(db, g.user)
    with db.tx():
        res = alert_service.generate_alerts(db, current_app.config, cids)
    flash(f"Checked {res['checked']} enrolment(s): {res['created']} new alert(s), {res['skipped_duplicates']} already open.",
          "success" if res["created"] else "info")
    return redirect(url_for("alerts.index"))


@bp.route("/alerts/<int:alert_id>/status", methods=["POST"])
@faculty_required
def set_status(alert_id):
    db = get_db()
    alert = alert_model.get_alert(db, alert_id)
    status = request.form.get("status")
    if not alert or status not in ("open", "acknowledged", "resolved"):
        flash("Alert not found or invalid status.", "danger")
    elif not can_access_pair(db, g.user, alert["student_id"], alert["course_id"]):
        flash("You do not have access to this alert.", "danger")
    else:
        alert_model.set_status(db, alert_id, status, datetime.now().replace(microsecond=0))
        flash(f"Alert marked {status}.", "success")
    return redirect(request.referrer or url_for("alerts.index"))
