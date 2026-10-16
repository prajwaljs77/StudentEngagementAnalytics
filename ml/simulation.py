"""Synthetic learner simulator (documented assumptions - see README "Synthetic data").

Assumptions
 * Every student-course pair has a latent engagement level in [0,1] (Beta(2.2, 2.0)).
 * The level drifts linearly over time (drift ~ Normal(0, 0.15) per 14 days), so the FUTURE differs
   from the PAST: students can disengage or recover. This keeps prediction non-trivial.
 * P(active day) = 0.05 + 0.9*level (weekends x0.7). On an active day: 1 login, Poisson study sessions,
   video views and material accesses whose number/duration grow with the level.
 * Quiz scores ~ 35 + 45*level + Normal(0,12); assignment lateness ~ Exponential(0.3 + 2.5*(1-level)) days.
It is SYNTHETIC: results describe the simulation, not real students.
"""
from datetime import datetime, timedelta

import numpy as np

HISTORY_DAYS = 56
FUTURE_DAYS = 14


def simulate_pair(rng, as_of, history_days=HISTORY_DAYS, future_days=FUTURE_DAYS):
    base = float(rng.beta(2.2, 2.0))
    drift = float(rng.normal(0, 0.15))
    acts = []
    for off in range(-history_days, future_days):
        day = as_of + timedelta(days=off)
        level = float(np.clip(base + drift * (off / 14.0), 0.02, 0.98))
        weekend = 0.7 if day.weekday() >= 5 else 1.0
        if rng.random() > 0.05 + 0.9 * level * weekend:
            continue

        def stamp(h0=7, h1=23):
            return day.replace(hour=int(rng.integers(h0, h1)), minute=int(rng.integers(0, 60)),
                               second=int(rng.integers(0, 60)), microsecond=0)
        acts.append(("login", 0, stamp(7, 12)))
        for _ in range(rng.poisson(0.6 + 1.8 * level)):
            acts.append(("study_session", int(np.clip(rng.lognormal(np.log(20 + 40 * level), 0.4), 5, 240)), stamp()))
        for _ in range(rng.poisson(0.3 + 1.4 * level)):
            acts.append(("video", int(np.clip(rng.normal(12 + 25 * level, 8), 3, 120)), stamp()))
        for _ in range(rng.poisson(0.2 + 1.0 * level)):
            acts.append(("material", int(np.clip(rng.normal(5 + 10 * level, 3), 1, 60)), stamp()))

    assess = []
    for i in range(int(rng.integers(0, 5))):  # quizzes
        when = as_of - timedelta(days=int(rng.integers(1, 55)), hours=int(rng.integers(0, 12)))
        assess.append({"assessment_type": "quiz", "title": f"Quiz {i + 1}", "due_at": None, "submitted_at": None,
                       "assessed_at": when,
                       "score": round(float(np.clip(35 + 45 * level_at(base, drift, -20) + rng.normal(0, 12), 0, 100)), 1)})
    for i in range(int(rng.integers(0, 3))):  # assignments
        when = as_of - timedelta(days=int(rng.integers(1, 50)))
        due = when - timedelta(days=int(rng.integers(1, 6)))
        late = float(rng.exponential(0.3 + 2.5 * (1 - base)))
        assess.append({"assessment_type": "assignment", "title": f"Assignment {i + 1}", "due_at": due,
                       "submitted_at": due + timedelta(days=late), "assessed_at": when,
                       "score": round(float(np.clip(35 + 45 * base + rng.normal(0, 12), 0, 100)), 1)})
    return acts, assess


def level_at(base, drift, off):
    return float(np.clip(base + drift * (off / 14.0), 0.02, 0.98))
