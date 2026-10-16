"""Reports generated from stored data. Every report returns the same shape so HTML, print and CSV share code."""
import csv
import io
from datetime import datetime, timedelta

import pandas as pd

from backend.models import activity as activity_model
from backend.models import assessment as assessment_model
from backend.models import prediction as prediction_model
from backend.services import analytics_service as analytics
from backend.utils.sql import in_clause

REPORTS = {
    "student_engagement": "Student engagement",
    "course_performance": "Course performance",
    "assessment_results": "Assessment results",
    "inactive_students": "Inactive students",
    "high_risk_students": "High-risk students",
    "activity_trends": "Activity trends",
    "prediction_history": "Prediction history",
}


def _fmt(value):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, float):
        return f"{value:.1f}"
    return "" if value is None else str(value)


def build_report(db, cfg, user, name, course_id=None, start=None, end=None):
    if name not in REPORTS:
        raise KeyError(name)
    course_ids, student_ids = analytics.resolve_scope(db, user, course_id)
    start_dt = datetime.combine(start, datetime.min.time()) if start else None
    end_dt = datetime.combine(end, datetime.max.time()).replace(microsecond=0) if end else None
    cols, rows = globals()[f"_{name}"](db, cfg, student_ids, course_ids, start_dt, end_dt)
    return {"name": name, "title": REPORTS[name], "columns": cols, "rows": rows,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "generated_by": user["name"]}


def _student_engagement(db, cfg, sids, cids, s, e):
    rows = [{"student": p["student_name"], "course": p["course_name"], "score": p["engagement_score"],
             "risk": p["risk_level"], "method": p["method"], "predicted_at": _fmt(p["predicted_at"])}
            for p in prediction_model.latest_predictions(db, sids, cids)]
    return [("student", "Student"), ("course", "Course"), ("score", "Engagement score"), ("risk", "Risk level"),
            ("method", "Method"), ("predicted_at", "Predicted at")], rows


def _course_performance(db, cfg, sids, cids, s, e):
    rows = []
    preds = pd.DataFrame(prediction_model.latest_predictions(db, sids, cids))
    for c in db.all(f"SELECT course_id, course_name, semester FROM courses WHERE {in_clause('course_id', cids)[0]} ORDER BY course_name", cids) if cids else []:
        cid = c["course_id"]
        acts, _ = activity_model.list_activities(db, sids, [cid], start=s, end=e, paginate=False)
        asm, _ = assessment_model.list_assessments(db, sids, [cid], start=s, end=e, paginate=False)
        adf, sdf = pd.DataFrame(acts), pd.DataFrame(asm)
        enr = db.scalar("SELECT COUNT(*) FROM enrollments WHERE course_id=%s", [cid], 0)
        avg = lambda t: (round(float(sdf[sdf.assessment_type == t].score.mean()), 1) if len(sdf) and (sdf.assessment_type == t).any() else None)
        rows.append({"course": c["course_name"], "semester": c["semester"], "students": enr, "activities": len(adf),
                     "study_minutes": int(adf[adf.activity_type != "login"].duration.sum()) if len(adf) else 0,
                     "avg_quiz": avg("quiz"), "avg_assignment": avg("assignment"),
                     "avg_engagement": round(float(preds[preds.course_id == cid].engagement_score.mean()), 1)
                     if len(preds) and (preds.course_id == cid).any() else None})
    return [("course", "Course"), ("semester", "Semester"), ("students", "Students"), ("activities", "Activities"),
            ("study_minutes", "Study minutes"), ("avg_quiz", "Avg quiz"), ("avg_assignment", "Avg assignment"),
            ("avg_engagement", "Avg engagement")], rows


def _assessment_results(db, cfg, sids, cids, s, e):
    data, _ = assessment_model.list_assessments(db, sids, cids, start=s, end=e, paginate=False)
    rows = [{"student": a["student_name"], "course": a["course_name"], "type": a["assessment_type"], "title": a["title"],
             "score": a["score"], "assessed_at": _fmt(a["assessed_at"])} for a in data]
    return [("student", "Student"), ("course", "Course"), ("type", "Type"), ("title", "Title"), ("score", "Score"),
            ("assessed_at", "Assessed at")], rows


def _inactive_students(db, cfg, sids, cids, s, e):
    last = {(r["student_id"]): r["last_time"] for r in activity_model.last_activity_by_student(db, sids, cids)}
    cutoff = datetime.now() - timedelta(days=cfg["INACTIVITY_DAYS"])
    rows = []
    for u in db.all(f"SELECT user_id, name, email FROM users WHERE {in_clause('user_id', sids)[0]} ORDER BY name", sids) if sids else []:
        lt = pd.to_datetime(last[u["user_id"]]) if u["user_id"] in last else None
        if lt is None or lt < cutoff:
            rows.append({"student": u["name"], "email": u["email"], "last_activity": _fmt(lt) if lt is not None else "Never",
                         "days_inactive": (datetime.now() - lt.to_pydatetime()).days if lt is not None else "n/a"})
    return [("student", "Student"), ("email", "Email"), ("last_activity", "Last activity"), ("days_inactive", "Days inactive")], rows


def _high_risk_students(db, cfg, sids, cids, s, e):
    rows = [{"student": p["student_name"], "course": p["course_name"], "score": p["engagement_score"],
             "predicted_at": _fmt(p["predicted_at"])} for p in prediction_model.latest_predictions(db, sids, cids, risk="high")]
    return [("student", "Student"), ("course", "Course"), ("score", "Engagement score"), ("predicted_at", "Predicted at")], rows


def _activity_trends(db, cfg, sids, cids, s, e):
    raw = analytics._activity_df(activity_model.raw_rows(db, sids, cids, s, e))
    rows = []
    if not raw.empty:
        raw["day"] = raw["activity_time"].dt.strftime("%Y-%m-%d")
        for day, g in raw.groupby("day"):
            rows.append({"date": day, "activities": len(g), "active_students": g["student_id"].nunique(),
                         "study_minutes": int(g[g.activity_type != "login"].duration.sum()),
                         "logins": int((g.activity_type == "login").sum())})
    return [("date", "Date"), ("activities", "Activities"), ("active_students", "Active students"),
            ("study_minutes", "Study minutes"), ("logins", "Logins")], rows


def _prediction_history(db, cfg, sids, cids, s, e):
    data, _ = prediction_model.list_history(db, sids, cids, start=s, end=e, paginate=False)
    rows = [{"student": p["student_name"], "course": p["course_name"], "score": p["engagement_score"], "risk": p["risk_level"],
             "method": p["method"], "predicted_at": _fmt(p["predicted_at"])} for p in data]
    return [("student", "Student"), ("course", "Course"), ("score", "Engagement score"), ("risk", "Risk level"),
            ("method", "Method"), ("predicted_at", "Predicted at")], rows


def _safe_cell(value):
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") and not text.replace(".", "", 1).lstrip("-").isdigit() else text


def to_csv(report):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([label for _, label in report["columns"]])
    for row in report["rows"]:
        writer.writerow([_safe_cell(row.get(key)) for key, _ in report["columns"]])
    return buf.getvalue()
