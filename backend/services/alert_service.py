"""Early-warning alerts. Rules (all thresholds configurable in .env):
  R1  predicted risk is HIGH (model or baseline)            -> RISK_HIGH_BELOW
  R2  no activity for >= INACTIVITY_DAYS days
  R3  >= 2 assessments and average score < LOW_SCORE_THRESHOLD
An alert is only created if no open/acknowledged alert already exists for the student+course pair."""
from datetime import datetime

from backend.models import alert as alert_model
from backend.models import enrollment as enrollment_model
from backend.models import prediction as prediction_model
from backend.services import prediction_service


def _low_scores(db, student_id, course_id):
    rows = db.all("SELECT score FROM assessments WHERE student_id=%s AND course_id=%s", [student_id, course_id])
    if len(rows) >= 2:
        avg = sum(r["score"] for r in rows) / len(rows)
        return avg
    return None


def generate_alerts(db, cfg, course_ids):
    created, skipped, checked = 0, 0, 0
    for pair in enrollment_model.pairs(db, course_ids):
        checked += 1
        sid, cid = pair["student_id"], pair["course_id"]
        result = prediction_service.predict(db, cfg, sid, cid, store=True)
        f, reasons = result["features"], []
        if result["risk_level"] == "high":
            reasons.append(f"Predicted high engagement risk (score {result['engagement_score']:.0f}/100)")
        if f["days_since_last_activity"] >= cfg["INACTIVITY_DAYS"]:
            reasons.append(f"No learning activity for {f['days_since_last_activity']:.0f} days")
        avg = _low_scores(db, sid, cid)
        if avg is not None and avg < cfg["LOW_SCORE_THRESHOLD"]:
            reasons.append(f"Consistently low assessment scores (average {avg:.0f})")
        if not reasons:
            continue
        if alert_model.open_exists(db, sid, cid):
            skipped += 1
            continue
        action = result["recommendations"][0] if result["recommendations"] else "Check in with the student."
        risk = "high" if result["risk_level"] == "high" or len(reasons) > 1 else (
            "medium" if result["risk_level"] == "low" else result["risk_level"])  # an alert is never "low" risk
        alert_model.create_alert(db, sid, cid, result["prediction_id"], result["engagement_score"], risk,
                                 "; ".join(reasons)[:500], action[:500], datetime.now().replace(microsecond=0))
        created += 1
    return {"checked": checked, "created": created, "skipped_duplicates": skipped}
