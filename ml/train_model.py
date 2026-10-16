"""Train, compare and save the engagement classifier.

Usage (from the project folder, venv active):
    python -m ml.generate_data      # optional: regenerate database/sample_students.csv
    python -m ml.train_model        # trains + saves ml/saved_models/engagement_model.joblib

Pipeline: SimpleImputer(median) -> StandardScaler -> classifier. Candidates: Logistic Regression and
Random Forest, compared with 5-fold STRATIFIED cross-validation (macro-F1) on the training split only;
the winner is refit on the training split and evaluated ONCE on the untouched test split.
"""
import json
import sys
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.feature_engineering import (CLASSES, FEATURE_COLUMNS, METRICS_FILE, MODEL_FILE, RANDOM_STATE, SAVED_DIR,
                                    baseline_score, load_dataset, split_dataset)


def make_pipeline(clf):
    return Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler()), ("clf", clf)])


def candidates():
    return {
        "logistic_regression": make_pipeline(LogisticRegression(max_iter=2000, class_weight="balanced", random_state=RANDOM_STATE)),
        "random_forest": make_pipeline(RandomForestClassifier(n_estimators=200, max_depth=8, min_samples_leaf=3,
                                                              class_weight="balanced", random_state=RANDOM_STATE, n_jobs=1)),
    }


def classification_report_dict(y_true, y_pred):
    acc = accuracy_score(y_true, y_pred)
    p, r, f, _ = precision_recall_fscore_support(y_true, y_pred, labels=CLASSES, average="macro", zero_division=0)
    pc, rc, fc, sc = precision_recall_fscore_support(y_true, y_pred, labels=CLASSES, zero_division=0)
    return {
        "accuracy": round(float(acc), 4), "precision_macro": round(float(p), 4),
        "recall_macro": round(float(r), 4), "f1_macro": round(float(f), 4),
        "per_class": {c: {"precision": round(float(pc[i]), 4), "recall": round(float(rc[i]), 4),
                          "f1": round(float(fc[i]), 4), "support": int(sc[i])} for i, c in enumerate(CLASSES)},
        "confusion_matrix": {"labels": CLASSES, "matrix": confusion_matrix(y_true, y_pred, labels=CLASSES).tolist()},
    }


def baseline_predictions(X):
    """Rule-based baseline mapped to the same 3 classes (for honest comparison)."""
    scores = X.apply(lambda r: baseline_score(r.to_dict()), axis=1)
    return np.where(scores < 40, "low", np.where(scores < 65, "medium", "high"))


def feature_stats(pipe, X_train, y_train):
    """Mean/std, importance and direction per feature - used to explain individual predictions."""
    clf = pipe.named_steps["clf"]
    imp = np.abs(clf.coef_).mean(axis=0) if hasattr(clf, "coef_") else clf.feature_importances_
    imp = imp / imp.sum()
    y_num = y_train.map({c: i for i, c in enumerate(CLASSES)})
    stats = {}
    for i, col in enumerate(FEATURE_COLUMNS):
        s = X_train[col]
        corr = s.corr(y_num, method="spearman")
        stats[col] = {"mean": float(s.mean()), "std": float(s.std() or 1.0), "median": float(s.median()),
                      "importance": float(imp[i]), "direction": 1.0 if (corr if corr == corr else 0) >= 0 else -1.0}
    return stats


def main():
    df = load_dataset()
    X_train, X_test, y_train, y_test = split_dataset(df)
    print(f"Dataset: {len(df)} rows | train {len(X_train)} | test {len(X_test)} | classes {y_train.value_counts().to_dict()}")
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
    results = {}
    for name, pipe in candidates().items():
        scores = cross_val_score(pipe, X_train, y_train, cv=cv, scoring="f1_macro")
        results[name] = {"cv_f1_macro_mean": round(float(scores.mean()), 4), "cv_f1_macro_std": round(float(scores.std()), 4)}
        print(f"  {name:20s} CV macro-F1 = {scores.mean():.3f} +/- {scores.std():.3f}")
    best = max(results, key=lambda k: results[k]["cv_f1_macro_mean"])
    print(f"Selected model (highest CV macro-F1): {best}")

    pipe = candidates()[best].fit(X_train, y_train)
    test_report = classification_report_dict(y_test, pipe.predict(X_test))
    base_report = classification_report_dict(y_test, baseline_predictions(X_test))
    other = {}
    for name, p in candidates().items():  # test scores of every candidate, for the report only
        other[name] = classification_report_dict(y_test, p.fit(X_train, y_train).predict(X_test))["f1_macro"]

    version = datetime.now().strftime("%Y%m%d-%H%M%S")
    bundle = {"pipeline": pipe, "feature_columns": FEATURE_COLUMNS, "classes": list(pipe.classes_), "version": version,
              "model_name": best, "feature_stats": feature_stats(pipe, X_train, y_train),
              "trained_at": datetime.now().isoformat(timespec="seconds")}
    SAVED_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, MODEL_FILE)
    metrics = {
        "model_version": version, "selected_model": best, "dataset_rows": int(len(df)),
        "train_rows": int(len(X_train)), "test_rows": int(len(X_test)),
        "candidates_cv": results, "candidates_test_f1_macro": other, "test_metrics": test_report,
        "rule_based_baseline_test_metrics": base_report,
        "notes": ["Trained on SYNTHETIC data: scores describe the simulation, not real students.",
                  "Test split is stratified and never used for model selection.",
                  "Predictions are decision-support estimates, not judgments about students."],
    }
    METRICS_FILE.write_text(json.dumps(metrics, indent=2))
    t = test_report
    print(f"\nTEST  accuracy={t['accuracy']}  precision(macro)={t['precision_macro']}  recall(macro)={t['recall_macro']}  F1(macro)={t['f1_macro']}")
    print("Confusion matrix (rows=true, cols=pred, order low/medium/high):")
    for row in t["confusion_matrix"]["matrix"]:
        print("  ", row)
    print(f"Rule-based baseline on the same test set: accuracy={base_report['accuracy']} F1(macro)={base_report['f1_macro']}")
    print(f"Saved model   -> {MODEL_FILE}\nSaved metrics -> {METRICS_FILE}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # friendly message for beginners
        print(f"Training failed: {exc}", file=sys.stderr)
        sys.exit(1)
