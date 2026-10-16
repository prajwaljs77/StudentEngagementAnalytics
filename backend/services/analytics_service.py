"""Descriptive, diagnostic and predictive analytics computed from stored data (pandas)."""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from backend.models import activity as activity_model
from backend.models import assessment as assessment_model
from backend.models import prediction as prediction_model
from backend.services import prediction_service
from backend.utils.scope import visible_course_ids, visible_student_ids
from backend.utils.sql import in_clause

TYPE_LABELS = {"login": "Logins", "video": "Video viewing", "material": "Learning material", "study_session": "Study sessions"}


def _num(x, nd=1):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), nd)


def resolve_scope(db, user, course_id=None, student_id=None):
    """Apply role scope first, then optional filters; filters can never widen access."""
    course_ids = visible_course_ids(db, user)
    if course_id:
        course_ids = [c for c in course_ids if c == course_id]
    student_ids = visible_student_ids(db, user, course_ids)
    if student_id:
        student_ids = [s for s in student_ids if s == student_id]
    return course_ids, student_ids


def _activity_df(rows):
    df = pd.DataFrame(rows, columns=["student_id", "course_id", "activity_type", "duration", "activity_time"])
    if not df.empty:
        df["activity_time"] = pd.to_datetime(df["activity_time"])
        df["duration"] = pd.to_numeric(df["duration"])
    return df


def dashboard_data(db, cfg, user, start, end, course_id=None, student_id=None):
    course_ids, student_ids = resolve_scope(db, user, course_id, student_id)
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end, datetime.max.time()).replace(microsecond=0)
    names = {r["course_id"]: r["course_name"] for r in db.all(
        f"SELECT course_id, course_name FROM courses WHERE {in_clause('course_id', course_ids)[0]}", course_ids)} if course_ids else {}
    sname = {r["user_id"]: r["name"] for r in db.all(
        f"SELECT user_id, name FROM users WHERE {in_clause('user_id', student_ids)[0]}", student_ids)} if student_ids else {}

    acts = _activity_df(activity_model.raw_rows(db, student_ids, course_ids, start_dt, end_dt))
    asm_rows, _ = assessment_model.list_assessments(db, student_ids, course_ids, start=start_dt, end=end_dt, paginate=False)
    asm = pd.DataFrame(asm_rows)
    if not asm.empty:
        asm["assessed_at"] = pd.to_datetime(asm["assessed_at"])
        asm["score"] = pd.to_numeric(asm["score"])
    preds = prediction_model.latest_predictions(db, student_ids, course_ids)
    pdf = pd.DataFrame(preds)

    now = datetime.now()
    last = {r["student_id"]: pd.to_datetime(r["last_time"]) for r in activity_model.last_activity_by_student(db, student_ids, course_ids)}
    cutoff = pd.Timestamp(now - timedelta(days=cfg["INACTIVITY_DAYS"]))
    inactive_ids = [s for s in student_ids if s not in last or last[s] < cutoff]

    kpis = {
        "total_students": len(student_ids), "total_courses": len(course_ids), "total_activities": int(len(acts)),
        "avg_assessment_score": _num(asm["score"].mean()) if not asm.empty else None,
        "avg_engagement_score": _num(pdf["engagement_score"].mean()) if not pdf.empty else None,
        "inactive_students": len(inactive_ids),
        "high_risk_students": int(pdf[pdf["risk_level"] == "high"]["student_id"].nunique()) if not pdf.empty else 0,
    }

    # ---- charts ----
    charts = {}
    ce_labels = [names[c] for c in course_ids]
    eng_by_course = pdf.groupby("course_id")["engagement_score"].mean().to_dict() if not pdf.empty else {}
    min_by_course = acts[acts["activity_type"] != "login"].groupby("course_id")["duration"].sum().to_dict() if not acts.empty else {}
    charts["course_engagement"] = {"labels": ce_labels,
                                   "engagement": [_num(eng_by_course.get(c)) for c in course_ids],
                                   "minutes": [_num(min_by_course.get(c, 0), 0) for c in course_ids]}
    days = (end - start).days + 1
    freq = "W" if days > 90 else "D"
    trend = {"labels": [], "activities": [], "minutes": []}
    if not acts.empty:
        g = acts.set_index("activity_time").sort_index()
        cnt = g["duration"].resample(freq).count()
        mins = g.loc[g["activity_type"] != "login", "duration"].resample(freq).sum()
        mins = mins.reindex(cnt.index, fill_value=0)
        trend = {"labels": [d.strftime("%d %b") for d in cnt.index], "activities": [int(v) for v in cnt.values],
                 "minutes": [int(v) for v in mins.values]}
    trend["granularity"] = "weekly" if freq == "W" else "daily"
    charts["activity_trend"] = trend
    perf = {"labels": ce_labels, "quiz": [None] * len(course_ids), "assignment": [None] * len(course_ids)}
    if not asm.empty:
        for i, c in enumerate(course_ids):
            for t in ("quiz", "assignment"):
                sub = asm[(asm["course_id"] == c) & (asm["assessment_type"] == t)]["score"]
                perf[t][i] = _num(sub.mean()) if len(sub) else None
    charts["assessment_performance"] = perf
    dist = {"low": 0, "medium": 0, "high": 0}
    if not pdf.empty:
        for k, v in pdf["risk_level"].value_counts().items():
            dist[k] = int(v)
    charts["risk_distribution"] = dist
    comp = {"labels": [], "minutes": [], "activities": []}
    if not acts.empty:
        s = acts.groupby("student_id").agg(minutes=("duration", lambda x: int(x.sum())), n=("duration", "count"))
        s = s.sort_values("minutes", ascending=False).head(10)
        comp = {"labels": [sname.get(i, str(i)) for i in s.index], "minutes": s["minutes"].tolist(), "activities": s["n"].tolist()}
    charts["student_comparison"] = comp

    return {"range": {"start": start.isoformat(), "end": end.isoformat()}, "kpis": kpis, "charts": charts,
            "insights": _insights(db, cfg, kpis, acts, asm, pdf, names, sname, inactive_ids, student_ids, course_ids, start_dt, end_dt),
            "empty": kpis["total_activities"] == 0 and asm.empty and pdf.empty}


def _insights(db, cfg, kpis, acts, asm, pdf, names, sname, inactive_ids, student_ids, course_ids, start_dt, end_dt):
    descriptive, diagnostic, predictive = [], [], []
    # ---- descriptive: what happened
    if not acts.empty:
        hours = acts.loc[acts["activity_type"] != "login", "duration"].sum() / 60
        active = acts["student_id"].nunique()
        descriptive.append(f"{len(acts)} learning activities by {active} student(s) were recorded in this period, "
                           f"with about {hours:.1f} hours of video, material and study time.")
        top_type = acts["activity_type"].value_counts().idxmax()
        descriptive.append(f"The most common activity type was '{TYPE_LABELS[top_type]}'.")
        top_course = acts["course_id"].value_counts().idxmax()
        descriptive.append(f"'{names.get(top_course, top_course)}' had the most activity.")
    else:
        descriptive.append("No learning activities were recorded in the selected period.")
    if not asm.empty:
        descriptive.append(f"{len(asm)} assessment result(s) averaged {asm['score'].mean():.1f}.")
    # ---- diagnostic: possible reasons
    span = (end_dt - start_dt)
    prev = _activity_df(activity_model.raw_rows(db, student_ids, course_ids, start_dt - span - timedelta(seconds=1), start_dt - timedelta(seconds=1)))
    if len(prev) >= 5:
        change = (len(acts) - len(prev)) / len(prev) * 100
        diagnostic.append(f"Activity volume changed by {change:+.0f}% compared with the previous period of equal length "
                          f"({len(prev)} -> {len(acts)} activities).")
    if not acts.empty and not asm.empty:
        minutes = acts[acts["activity_type"] != "login"].groupby("student_id")["duration"].sum()
        avg_score = asm.groupby("student_id")["score"].mean()
        joined = pd.concat([minutes, avg_score], axis=1, keys=["m", "s"]).dropna()
        if len(joined) >= 5 and joined["m"].std() > 0 and joined["s"].std() > 0:
            r = joined["m"].corr(joined["s"])
            strength = "strong" if abs(r) >= 0.6 else "moderate" if abs(r) >= 0.3 else "weak"
            diagnostic.append(f"Study time and average assessment score show a {strength} {'positive' if r >= 0 else 'negative'} "
                              f"relationship (r = {r:.2f}, n = {len(joined)}). Correlation does not prove causation.")
    if inactive_ids and not asm.empty:
        inactive_scores = asm[asm["student_id"].isin(inactive_ids)]["score"]
        if len(inactive_scores):
            diagnostic.append(f"Inactive students ({len(inactive_ids)}) average {inactive_scores.mean():.1f} on assessments versus "
                              f"{asm[~asm['student_id'].isin(inactive_ids)]['score'].mean() if (~asm['student_id'].isin(inactive_ids)).any() else float('nan'):.1f} for active students.")
    if not pdf.empty:
        weakest = pdf.groupby("course_name")["engagement_score"].mean().sort_values().head(1)
        diagnostic.append(f"Lowest predicted engagement is in '{weakest.index[0]}' (average score {weakest.iloc[0]:.0f}).")
    if not diagnostic:
        diagnostic.append("Not enough data yet to suggest reasons. Record more activities and assessments.")
    # ---- predictive: what may happen next
    status = prediction_service.model_status(cfg["MODEL_PATH"])
    if pdf.empty:
        predictive.append("No engagement predictions yet. Faculty can open the Predictions page and run them for a course.")
    else:
        hi = pdf[pdf["risk_level"] == "high"]
        predictive.append(f"{len(hi)} student-course pair(s) are predicted at HIGH risk of low engagement in the next two weeks.")
        for _, r in pdf.head(3).iterrows():
            predictive.append(f"Lowest predicted score: {r['student_name']} in {r['course_name']} ({r['engagement_score']:.0f}/100, {r['risk_level']} risk).")
    predictive.append("Model: " + (f"trained classifier version {status['version']}." if status["available"]
                                   else "no trained model found - predictions use a rule-based baseline."))
    return {"descriptive": descriptive, "diagnostic": diagnostic, "predictive": predictive}


def assessment_trend(db, user, course_id=None, student_id=None):
    course_ids, student_ids = resolve_scope(db, user, course_id, student_id)
    rows, _ = assessment_model.list_assessments(db, student_ids, course_ids, paginate=False)
    if not rows:
        return {"labels": [], "quiz": [], "assignment": []}
    df = pd.DataFrame(rows)
    df["assessed_at"] = pd.to_datetime(df["assessed_at"])
    df["week"] = df["assessed_at"].dt.to_period("W").apply(lambda p: p.start_time)
    pivot = df.pivot_table(index="week", columns="assessment_type", values="score", aggfunc="mean").sort_index()
    out = {"labels": [d.strftime("%d %b %Y") for d in pivot.index]}
    for t in ("quiz", "assignment"):
        out[t] = [_num(v) for v in pivot[t]] if t in pivot else [None] * len(pivot)
    return out


def low_performers(db, cfg, student_ids, course_ids, min_count=2):
    """Students whose average is below the threshold with at least `min_count` results, and whose latest
    result is also below it (consistently low)."""
    rows, _ = assessment_model.list_assessments(db, student_ids, course_ids, paginate=False)
    if not rows:
        return []
    df = pd.DataFrame(rows).sort_values("assessed_at")
    out = []
    for (sid, cid), g in df.groupby(["student_id", "course_id"]):
        avg = g["score"].mean()
        if len(g) >= min_count and avg < cfg["LOW_SCORE_THRESHOLD"] and g["score"].iloc[-1] < cfg["LOW_SCORE_THRESHOLD"]:
            out.append({"student_id": int(sid), "student_name": g["student_name"].iloc[0], "course_name": g["course_name"].iloc[0],
                        "count": int(len(g)), "average": round(float(avg), 1)})
    return sorted(out, key=lambda r: r["average"])


def assessment_summary(db, student_ids, course_ids):
    rows, _ = assessment_model.list_assessments(db, student_ids, course_ids, paginate=False)
    if not rows:
        return {"count": 0, "average": None, "quiz_avg": None, "assignment_avg": None, "highest": None, "lowest": None}
    df = pd.DataFrame(rows)
    return {"count": len(df), "average": _num(df["score"].mean()),
            "quiz_avg": _num(df[df["assessment_type"] == "quiz"]["score"].mean()),
            "assignment_avg": _num(df[df["assessment_type"] == "assignment"]["score"].mean()),
            "highest": _num(df["score"].max()), "lowest": _num(df["score"].min())}
