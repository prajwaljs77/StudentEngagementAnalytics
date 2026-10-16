"""Engagement prediction: feature building from MySQL, model loading, scoring, explanation, storage.

Score  = 100 * (0.5 * P(medium engagement) + 1.0 * P(high engagement))   -> expected engagement, 0..100
Risk   = high if score < RISK_HIGH_BELOW (40), medium if < RISK_MEDIUM_BELOW (65), else low
If no trained model exists the transparent RULE-BASED baseline is used and clearly labelled as such.
"""
import json
import math
import os
from datetime import datetime, timedelta

import joblib
import numpy as np

from backend.models import activity as activity_model
from backend.models import assessment as assessment_model
from backend.models import prediction as prediction_model
from ml.feature_engineering import (ASSESSMENT_WINDOW_DAYS, FEATURE_COLUMNS, FEATURE_DOCS, FEATURE_LABELS,
                                    baseline_score, compute_features, to_frame)

METHOD_ML = "ml_model"
METHOD_BASELINE = "rule_based_baseline"
_NAN_OK = {"avg_quiz_score", "avg_assignment_delay_days"}
_cache = {"path": None, "mtime": None, "bundle": None}


class ModelUnavailable(Exception):
    pass


class PredictionError(Exception):
    pass


def load_model(path):
    if not path or not os.path.exists(path):
        raise ModelUnavailable("No trained model found. Run:  python -m ml.train_model")
    mtime = os.path.getmtime(path)
    if _cache["path"] == path and _cache["mtime"] == mtime:
        return _cache["bundle"]
    try:
        bundle = joblib.load(path)
        if not all(k in bundle for k in ("pipeline", "feature_columns", "classes", "version")):
            raise ValueError("unexpected file content")
    except Exception as exc:
        raise ModelUnavailable(f"The saved model could not be loaded ({exc}). Re-train it with:  python -m ml.train_model") from exc
    _cache.update(path=path, mtime=mtime, bundle=bundle)
    return bundle


def model_status(path):
    try:
        bundle = load_model(path)
        return {"available": True, "version": bundle["version"], "model_name": bundle.get("model_name"),
                "trained_at": bundle.get("trained_at"), "message": "Trained model loaded."}
    except ModelUnavailable as exc:
        return {"available": False, "version": None, "model_name": None, "trained_at": None, "message": str(exc)}


def risk_level(score, cfg):
    if score < cfg["RISK_HIGH_BELOW"]:
        return "high"
    if score < cfg["RISK_MEDIUM_BELOW"]:
        return "medium"
    return "low"


def build_features(db, student_id, course_id, as_of=None):
    as_of = as_of or datetime.now()
    acts = activity_model.for_student_course(db, student_id, course_id, as_of - timedelta(days=90))
    asm = assessment_model.recent_for_student_course(db, student_id, course_id, as_of - timedelta(days=ASSESSMENT_WINDOW_DAYS))
    return compute_features(acts, asm, as_of), len(acts)


def validate_features(features):
    for col in FEATURE_COLUMNS:
        value = features.get(col)
        if value is None or (isinstance(value, float) and math.isnan(value) and col not in _NAN_OK):
            raise PredictionError(f"Feature '{col}' is missing.")
        if isinstance(value, float) and math.isinf(value):
            raise PredictionError(f"Feature '{col}' is not a finite number.")
        if col not in ("activity_trend",) and isinstance(value, float) and not math.isnan(value) and value < 0:
            raise PredictionError(f"Feature '{col}' cannot be negative.")


def explain(features, bundle):
    """Top indicators = feature importance x deviation from the training average (direction-aware)."""
    stats = bundle.get("feature_stats") or {}
    items = []
    for col in FEATURE_COLUMNS:
        st, value = stats.get(col), features[col]
        if not st or (isinstance(value, float) and math.isnan(value)):
            continue
        z = float(np.clip((value - st["mean"]) / (st["std"] or 1.0), -3, 3))
        contrib = st["direction"] * st["importance"] * z
        unit = FEATURE_DOCS[col][1]
        items.append({"feature": col, "label": FEATURE_LABELS[col], "value": round(value, 1), "unit": unit,
                      "weight": round(contrib, 4), "effect": "supports engagement" if contrib >= 0 else "lowers engagement"})
    negatives = sorted([i for i in items if i["weight"] < 0], key=lambda i: i["weight"])[:3]
    positives = sorted([i for i in items if i["weight"] > 0], key=lambda i: -i["weight"])[:2]
    return negatives + positives


def indicators_rule_based(features):
    out = []
    for col in ("active_days_28d", "total_study_minutes_28d", "days_since_last_activity", "recent_7d_activity_count"):
        out.append({"feature": col, "label": FEATURE_LABELS[col], "value": round(features[col], 1),
                    "unit": FEATURE_DOCS[col][1], "weight": 0, "effect": "used by rule-based baseline"})
    return out


def recommendations(features, risk, cfg):
    tips = []
    f = features
    if f["days_since_last_activity"] >= cfg["INACTIVITY_DAYS"]:
        tips.append("Check in personally: there has been no recent activity. Ask whether anything is getting in the way.")
    if f["activity_trend"] <= -3:
        tips.append("Activity is dropping compared with earlier weeks. A short supportive conversation may help.")
    if f["login_count_28d"] < 4:
        tips.append("Send a friendly reminder with the course schedule and the next learning milestones.")
    if f["video_minutes_28d"] < 30:
        tips.append("Share a short list of key recorded lectures to restart video learning.")
    if f["avg_quiz_score"] == f["avg_quiz_score"] and f["avg_quiz_score"] < 50:
        tips.append("Offer revision resources, practice quizzes or office-hour support for the weaker topics.")
    if f["avg_assignment_delay_days"] == f["avg_assignment_delay_days"] and f["avg_assignment_delay_days"] > 2:
        tips.append("Discuss time planning and offer smaller checkpoints for assignments.")
    base = {"high": "Offer an academic guidance session and agree on a simple weekly study plan.",
            "medium": "Provide study resources and encourage participation in upcoming sessions.",
            "low": "Engagement looks healthy: acknowledge the effort and keep the current support."}[risk]
    return ([base] + tips)[:4] if risk != "low" else [base]


def predict(db, cfg, student_id, course_id, store=True, as_of=None, allow_baseline=True):
    """Return a result dict; optionally persist it to engagement_predictions."""
    features, n_acts = build_features(db, student_id, course_id, as_of)
    validate_features(features)
    warnings = []
    if n_acts == 0:
        warnings.append("No activity records exist for this student in this course, so the estimate has low reliability.")
    try:
        bundle = load_model(cfg["MODEL_PATH"])
        frame = to_frame([features])
        probs = dict(zip(bundle["classes"], bundle["pipeline"].predict_proba(frame)[0]))
        score = 100.0 * (0.5 * probs.get("medium", 0) + probs.get("high", 0))
        method, version = METHOD_ML, bundle["version"]
        indicators = explain(features, bundle)
        probs = {k: round(float(v), 4) for k, v in probs.items()}
    except ModelUnavailable as exc:
        if not allow_baseline:
            raise
        score, method, version, probs = baseline_score(features), METHOD_BASELINE, None, None
        indicators = indicators_rule_based(features)
        warnings.append(f"{exc} Showing the rule-based baseline instead (not machine learning).")
    score = round(float(np.clip(score, 0, 100)), 2)
    risk = risk_level(score, cfg)
    now = datetime.now().replace(microsecond=0)
    clean = {k: (None if isinstance(v, float) and math.isnan(v) else round(v, 3)) for k, v in features.items()}
    result = {"student_id": student_id, "course_id": course_id, "engagement_score": score, "risk_level": risk,
              "method": method, "model_version": version, "probabilities": probs, "features": clean,
              "indicators": indicators, "recommendations": recommendations(features, risk, cfg),
              "predicted_at": now.strftime("%Y-%m-%d %H:%M:%S"), "warnings": warnings, "prediction_id": None,
              "disclaimer": "Decision-support estimate only - not a definitive judgment about the student."}
    if store:
        result["prediction_id"] = prediction_model.add_prediction(
            db, student_id, course_id, score, risk, now, method, version, json.dumps(clean))
    return result
