"""Feature engineering shared by TRAINING and by the LIVE app (single source of truth).

Observation window: the 28 days BEFORE `as_of` (as_of itself is excluded).
Assessment window : the 56 days before `as_of` (assessments are sparse).
Missing values    : avg_quiz_score and avg_assignment_delay_days are NaN when no such record exists
                    and are median-imputed inside the saved sklearn Pipeline. All counts default to 0.
Target (training) : engagement during the FOLLOWING 14 days (see engagement_index) -> no leakage:
                    no information from the target window is used by any feature.
"""
from datetime import timedelta

import numpy as np
import pandas as pd

WINDOW_DAYS = 28
RECENT_DAYS = 7
ASSESSMENT_WINDOW_DAYS = 56
FUTURE_DAYS = 14
MAX_DAYS_SINCE = 60

CLASSES = ["low", "medium", "high"]          # ordinal engagement classes (target)
LABEL_THRESHOLDS = (33.0, 64.0)              # future index <33 low, <64 medium, else high

FEATURE_COLUMNS = [
    "login_count_28d", "active_days_28d", "activity_count_28d", "total_study_minutes_28d",
    "video_minutes_28d", "material_access_count_28d", "avg_quiz_score", "avg_assignment_delay_days",
    "days_since_last_activity", "recent_7d_activity_count", "activity_trend",
]

FEATURE_DOCS = {
    "login_count_28d": ("Number of login events", "count", "last 28 days"),
    "active_days_28d": ("Distinct calendar days with any activity", "days", "last 28 days"),
    "activity_count_28d": ("All recorded learning activities (incl. logins)", "count", "last 28 days"),
    "total_study_minutes_28d": ("Sum of study-session durations", "minutes", "last 28 days"),
    "video_minutes_28d": ("Sum of video-viewing durations", "minutes", "last 28 days"),
    "material_access_count_28d": ("Learning-material access events", "count", "last 28 days"),
    "avg_quiz_score": ("Mean quiz score (NaN if none -> median imputed)", "score 0-100", "last 56 days"),
    "avg_assignment_delay_days": ("Mean lateness of assignment submissions, early = 0 (NaN if none)", "days", "last 56 days"),
    "days_since_last_activity": ("Days since the most recent activity (capped at 60)", "days", "all history"),
    "recent_7d_activity_count": ("Activities in the most recent 7 days", "count", "last 7 days"),
    "activity_trend": ("Recent 7-day count minus average weekly count of the 21 days before", "count", "28 days"),
}

FEATURE_LABELS = {
    "login_count_28d": "Login frequency", "active_days_28d": "Active days", "activity_count_28d": "Total activities",
    "total_study_minutes_28d": "Study time", "video_minutes_28d": "Video viewing time",
    "material_access_count_28d": "Learning material access", "avg_quiz_score": "Average quiz score",
    "avg_assignment_delay_days": "Assignment submission delay", "days_since_last_activity": "Days since last activity",
    "recent_7d_activity_count": "Activity in the last 7 days", "activity_trend": "Activity trend",
}


def _acts_df(acts):
    if isinstance(acts, pd.DataFrame):
        df = acts.copy()
    else:
        df = pd.DataFrame(list(acts), columns=["activity_type", "duration", "activity_time"])
    if df.empty:
        return pd.DataFrame({"activity_type": pd.Series(dtype=str), "duration": pd.Series(dtype=float),
                             "activity_time": pd.Series(dtype="datetime64[ns]")})
    df["activity_time"] = pd.to_datetime(df["activity_time"])
    df["duration"] = pd.to_numeric(df["duration"], errors="coerce").fillna(0).clip(lower=0)
    return df


def _assess_df(rows):
    cols = ["assessment_type", "score", "due_at", "submitted_at", "assessed_at"]
    df = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(list(rows), columns=cols)
    for c in ("due_at", "submitted_at", "assessed_at"):
        df[c] = pd.to_datetime(df[c]) if len(df) else pd.Series(dtype="datetime64[ns]")
    df["score"] = pd.to_numeric(df["score"], errors="coerce") if len(df) else pd.Series(dtype=float)
    return df


def compute_features(activities, assessments, as_of):
    """Return a dict with every column in FEATURE_COLUMNS (floats; NaN where undefined)."""
    acts = _acts_df(activities)
    asm = _assess_df(assessments)
    as_of = pd.Timestamp(as_of)
    before = acts[acts["activity_time"] < as_of]
    win = before[before["activity_time"] >= as_of - timedelta(days=WINDOW_DAYS)]
    recent = win[win["activity_time"] >= as_of - timedelta(days=RECENT_DAYS)]
    prior = win[win["activity_time"] < as_of - timedelta(days=RECENT_DAYS)]

    last = before["activity_time"].max() if len(before) else None
    days_since = MAX_DAYS_SINCE if last is None or pd.isna(last) else min(
        MAX_DAYS_SINCE, max(0.0, (as_of - last).total_seconds() / 86400))

    a_win = asm[(asm["assessed_at"] < as_of) & (asm["assessed_at"] >= as_of - timedelta(days=ASSESSMENT_WINDOW_DAYS))]
    quiz = a_win[a_win["assessment_type"] == "quiz"]["score"].dropna()
    assign = a_win[(a_win["assessment_type"] == "assignment") & a_win["due_at"].notna() & a_win["submitted_at"].notna()]
    delay = ((assign["submitted_at"] - assign["due_at"]).dt.total_seconds() / 86400).clip(lower=0)

    weekly_prior = len(prior) / 3.0
    return {
        "login_count_28d": float((win["activity_type"] == "login").sum()),
        "active_days_28d": float(win["activity_time"].dt.normalize().nunique()) if len(win) else 0.0,
        "activity_count_28d": float(len(win)),
        "total_study_minutes_28d": float(win.loc[win["activity_type"] == "study_session", "duration"].sum()),
        "video_minutes_28d": float(win.loc[win["activity_type"] == "video", "duration"].sum()),
        "material_access_count_28d": float((win["activity_type"] == "material").sum()),
        "avg_quiz_score": float(quiz.mean()) if len(quiz) else float("nan"),
        "avg_assignment_delay_days": float(delay.mean()) if len(delay) else float("nan"),
        "days_since_last_activity": float(days_since),
        "recent_7d_activity_count": float(len(recent)),
        "activity_trend": float(len(recent) - weekly_prior),
    }


def engagement_index(future_acts, days=FUTURE_DAYS):
    """TARGET definition (0-100) from activity in the future window (never used as a feature).
    0.4*active-day share (12 of 14 days = full) + 0.4*learning minutes (1500 = full) + 0.2*activity count (100 = full)."""
    df = _acts_df(future_acts)
    if df.empty:
        return 0.0
    active_days = df["activity_time"].dt.normalize().nunique()
    minutes = df.loc[df["activity_type"] != "login", "duration"].sum()
    count = len(df)
    full_days, full_minutes, full_count = 12.0, 1500.0, 100.0
    value = 0.4 * min(active_days / full_days, 1) + 0.4 * min(minutes / full_minutes, 1) + 0.2 * min(count / full_count, 1)
    return round(100 * value, 2)


def label_from_index(index):
    low, med = LABEL_THRESHOLDS
    return "low" if index < low else "medium" if index < med else "high"


def baseline_score(features):
    """Transparent RULE-BASED baseline (NOT machine learning): used for comparison and as fallback."""
    f = features
    active = min(f["active_days_28d"] / 14.0, 1)
    minutes = min((f["total_study_minutes_28d"] + f["video_minutes_28d"]) / 900.0, 1)
    count = min(f["activity_count_28d"] / 60.0, 1)
    score = 100 * (0.4 * active + 0.4 * minutes + 0.2 * count)
    score -= min(f["days_since_last_activity"], 28) * 0.8   # recency penalty
    return float(np.clip(score, 0, 100))


def to_frame(rows):
    """List of feature dicts -> DataFrame with the exact column order the model expects."""
    return pd.DataFrame(rows)[FEATURE_COLUMNS].astype(float)


# ---------------- dataset helpers shared by train/evaluate ----------------
from pathlib import Path  # noqa: E402

DATASET_PATH = Path(__file__).resolve().parent.parent / "database" / "sample_students.csv"
SAVED_DIR = Path(__file__).resolve().parent / "saved_models"
MODEL_FILE = SAVED_DIR / "engagement_model.joblib"
METRICS_FILE = SAVED_DIR / "metrics.json"
RANDOM_STATE = 42


def load_dataset(path=DATASET_PATH):
    df = pd.read_csv(path)
    missing = [c for c in FEATURE_COLUMNS + ["engagement_label"] if c not in df.columns]
    if missing:
        raise ValueError(f"Dataset is missing columns: {missing}")
    df = df.dropna(subset=["engagement_label"])
    df = df[df["engagement_label"].isin(CLASSES)]
    return df.reset_index(drop=True)


def split_dataset(df, test_size=0.2):
    """Stratified train/test split (identical in training and evaluation)."""
    from sklearn.model_selection import train_test_split
    X, y = df[FEATURE_COLUMNS].astype(float), df["engagement_label"]
    return train_test_split(X, y, test_size=test_size, stratify=y, random_state=RANDOM_STATE)
