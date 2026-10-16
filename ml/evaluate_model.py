"""Re-evaluate the saved model on the (reproducible) held-out test split.
Usage: python -m ml.evaluate_model
"""
import json
import sys

import joblib

from ml.feature_engineering import MODEL_FILE, load_dataset, split_dataset
from ml.train_model import baseline_predictions, classification_report_dict


def main():
    if not MODEL_FILE.exists():
        print("No trained model found. Run: python -m ml.train_model")
        sys.exit(1)
    bundle = joblib.load(MODEL_FILE)
    _, X_test, _, y_test = split_dataset(load_dataset())
    report = classification_report_dict(y_test, bundle["pipeline"].predict(X_test))
    base = classification_report_dict(y_test, baseline_predictions(X_test))
    print(f"Model {bundle['model_name']} (version {bundle['version']}) on {len(y_test)} test rows")
    print(json.dumps(report, indent=2))
    print("Rule-based baseline F1(macro):", base["f1_macro"], "| accuracy:", base["accuracy"])


if __name__ == "__main__":
    main()
