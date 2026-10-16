"""Generate the synthetic training dataset -> database/sample_students.csv
Usage:  python -m ml.generate_data [--samples 900] [--seed 42]
"""
import argparse
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from ml.feature_engineering import (FEATURE_COLUMNS, FUTURE_DAYS, compute_features, engagement_index,
                                    label_from_index)
from ml.simulation import simulate_pair

OUT = Path(__file__).resolve().parent.parent / "database" / "sample_students.csv"
AS_OF = datetime(2025, 6, 1)  # fixed reference date => fully reproducible CSV


def generate(samples=900, seed=42):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(samples):
        acts, assess = simulate_pair(rng, AS_OF)
        hist = [a for a in acts if a[2] < AS_OF]
        future = [a for a in acts if a[2] >= AS_OF]
        feats = compute_features(hist, assess, AS_OF)          # uses ONLY the past
        idx = engagement_index(pd.DataFrame(future, columns=["activity_type", "duration", "activity_time"]))
        rows.append({"student_ref": f"S{i % 300 + 1:04d}", "course_ref": f"C{i % 6 + 1}", **feats,
                     "future_engagement_index": idx, "engagement_label": label_from_index(idx)})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=900)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    df = generate(args.samples, args.seed)
    df.round(3).to_csv(OUT, index=False)
    print(f"Wrote {len(df)} rows to {OUT}")
    print(df["engagement_label"].value_counts(normalize=True).round(3).to_string())
    print("missing quiz:", df["avg_quiz_score"].isna().mean().round(3), "missing delay:", df["avg_assignment_delay_days"].isna().mean().round(3))
