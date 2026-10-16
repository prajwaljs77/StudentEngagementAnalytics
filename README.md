# Online Learning Analytics & Student Engagement Prediction

MCA academic project: a Flask + MySQL web application that records online learning activity and assessments,
shows engagement analytics, predicts student engagement with a trained scikit-learn model, and raises
early-warning alerts so faculty can offer **supportive** help.

Stack: HTML5/CSS3/JavaScript, Bootstrap 5, Chart.js, Flask, Jinja2, MySQL (`mysql-connector-python`),
pandas, NumPy, scikit-learn, joblib, pytest. No React, Node.js, Docker or paid/external AI APIs.

> **Internet needed in the browser:** Bootstrap, Bootstrap Icons and Chart.js are loaded from the jsDelivr CDN.

---------------------------------------------------------------------------------------------------

## 1. Folder structure

```
StudentEngagementAnalytics/
├── app.py                  # entry point (python app.py)
├── config.py               # all settings, read from .env / environment
├── extensions.py           # MySQL access layer + CSRF helpers
├── requirements.txt  .env.example  .gitignore  README.md
├── database/
│   ├── schema.sql          # creates DB + 6 required tables (+ alerts)
│   ├── seed.sql            # demo users, courses, enrolments, activities, assessments
│   ├── sample_students.csv # synthetic ML dataset (900 learner records, features + label)
│   ├── sample_activities.csv / sample_assessments.csv   # examples for the CSV import feature
│   ├── generate_seed.py    # regenerates seed.sql + sample CSVs
│   └── make_sqlite_schema.py  # derives the SQLite schema used ONLY by tests
├── backend/
│   ├── __init__.py         # Flask app factory (templates/static paths are set here)
│   ├── routes/             # auth, dashboard, courses, students, activities, assessments, predictions, alerts, reports
│   ├── models/             # SQL (parameterised) for user, course, enrollment, activity, assessment, prediction, alert
│   ├── services/           # analytics, prediction, alert, import, report business logic
│   └── utils/              # decorators, validators, scope (authorisation), sql helpers
├── frontend/
│   ├── templates/          # Jinja2 pages (+ errors/400,403,404,500)
│   └── static/             # css/style.css, js/script.js, js/charts.js, images/logo.svg, samples/
├── ml/
│   ├── feature_engineering.py   # feature definitions (shared by training AND the live app)
│   ├── simulation.py  generate_data.py   # synthetic learner simulator + dataset generator
│   ├── train_model.py  evaluate_model.py
│   └── saved_models/       # engagement_model.joblib + metrics.json (trained model included)
├── uploads/                # audit copies of imported CSVs (never served by the web app)
└── tests/                  # pytest suite (uses a temporary SQLite file, never your MySQL data)
```
(`backend/__init__.py` is the real name of the package file; it is sometimes written `init.py` in notes.)

---------------------------------------------------------------------------------------------------

## 2. Installation on Windows (VS Code + MySQL Workbench)

### Prerequisites
* **Python 3.12** (3.11+ works) from python.org - tick *"Add python.exe to PATH"* during setup.
* **MySQL Server 8.0+** and **MySQL Workbench** (MySQL Installer for Windows installs both).
* **VS Code** with the *Python* extension.

### Step by step (PowerShell)
1. **Extract** `StudentEngagementAnalytics.zip` (right-click > *Extract All*), e.g. to `C:\Projects\`.
2. **Open in VS Code:** *File > Open Folder...* > choose `StudentEngagementAnalytics`. Open a terminal with *Terminal > New Terminal* (PowerShell).
3. **Create and activate a virtual environment**
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```
   If PowerShell says scripts are disabled, run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then activate again.
   You should see `(venv)` at the start of the prompt.
4. **Install dependencies**
   ```powershell
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```
5. **Create the database (MySQL Workbench)**
   1. Open Workbench and connect to your local instance (the `root` user and the password you chose during installation).
   2. *File > Open SQL Script...* > `database\schema.sql` > click the lightning-bolt **Execute** button. This creates `student_engagement_db` and all tables.
   3. *File > Open SQL Script...* > `database\seed.sql` > **Execute**. This loads the demo data (2 faculty, 18 students, 4 courses, ~3,500 activities, ~100 assessments).
   4. Check: `SELECT COUNT(*) FROM student_engagement_db.users;` returns 20.
6. **Configure `.env`**
   ```powershell
   Copy-Item .env.example .env
   notepad .env
   ```
   Set at least `DB_PASSWORD` (your MySQL password) and `SECRET_KEY`. Generate a key with:
   ```powershell
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
   Never share or commit `.env`.
7. **(Optional) regenerate the sample data** - the ZIP already contains it:
   ```powershell
   python -m ml.generate_data          # rewrites database\sample_students.csv (ML dataset, seed 42)
   python -m database.generate_seed    # rewrites database\seed.sql and the sample import CSVs
   ```
8. **Train the machine-learning model** (a trained model is already included; retrain whenever you change the dataset or package versions):
   ```powershell
   python -m ml.train_model
   python -m ml.evaluate_model         # optional: re-check metrics on the held-out test split
   ```
9. **Start the application**
   ```powershell
   python app.py
   ```
   Open **http://127.0.0.1:5000** in your browser. Stop the server with `Ctrl+C`.
10. **Generate predictions & alerts** (first time): log in as faculty > *Predictions* > choose a course > **Predict whole course**; then *Alerts* > **Generate alerts**. The dashboard's engagement KPIs and risk chart fill in from these stored predictions.

### Demo accounts (seed data - for local demos only)
| Role | Email | Password |
|---|---|---|
| Faculty (Data Structures, DBMS) | `faculty1@example.edu` | `Demo@1234` |
| Faculty (ML Fundamentals, Web Tech) | `faculty2@example.edu` | `Demo@1234` |
| Students | `student01@example.edu` ... `student18@example.edu` | `Demo@1234` |

These are synthetic accounts that exist only if you ran `seed.sql`. Do not use that password anywhere real.
You can also create your own accounts on the **Register** page. Faculty registration requires `FACULTY_INVITE_CODE` from your `.env` (leave it empty to allow open faculty sign-up).
`student03` and `student12` are deliberately inactive and `student06`/`student14` have low scores, so alerts have something to find.

### Run the tests
```powershell
pytest -v
```
Tests use a throw-away SQLite database in a temp folder (`TestConfig`), so they can never modify your MySQL data.

---------------------------------------------------------------------------------------------------

## 3. Features and who can do what

| Area | Faculty | Student |
|---|---|---|
| Register / login / logout, hashed passwords, CSRF, session cookies | yes | yes |
| Dashboard (KPIs, 5 charts, filters, descriptive/diagnostic/predictive insights) | own courses' students | own data only |
| Courses CRUD, faculty assignment, enrolment | own courses | view enrolled courses |
| Students CRUD, search, learning history | students in own courses | own profile only |
| Activities: add / filter / delete | any enrolled student of own courses | add/delete own **manual** records |
| Activities CSV import | yes | no |
| Assessments (quiz / assignment): CRUD, trends, low-score detection, CSV import | yes | view own |
| Predictions (single + whole course), stored in MySQL | yes | view own results |
| Alerts with status (open / acknowledged / resolved) | yes | no |
| Prediction history with filters + CSV export | own scope | own results |
| Reports (7 kinds) as HTML/print/PDF and CSV | yes | no |

* **Safe deletes:** a course/student that still has enrolments, activities, assessments, predictions or alerts cannot be deleted; a clear message explains why (and MySQL foreign keys enforce it too).
* **Manual vs. genuine data:** every activity has a `source`: `manual` (typed), `csv_import`, or `system`. A student's real login automatically records a `system` login event for each enrolled course. Seed data is marked `manual`.
* **Reports:** open *Reports*, pick filters, **View**, then **Print / Save PDF** (browser print dialog) or **CSV**.

### CSV import formats
Activities (`database/sample_activities.csv`) - all columns required:
`student_email, course_name, activity_type, duration, activity_time`
* `activity_type`: `login`, `video`, `material`, `study_session`; `duration` in whole minutes (0-1440; >=1 except logins); `activity_time` like `2025-03-01 14:30`, not in the future.

Assessments (`database/sample_assessments.csv`) - required: `student_email, course_name, assessment_type, title, score`; optional: `due_at, submitted_at, assessed_at`
* `assessment_type`: `quiz` or `assignment`; score 0..`ASSESSMENT_MAX_SCORE`; `due_at` and `submitted_at` must be given together.

Rules: `.csv` only, max `MAX_UPLOAD_MB` (default 2 MB), UTF-8, up to 5,000 rows. Students must exist and be enrolled in one of **your** courses. Duplicates (in the file or already stored) and invalid rows are rejected and listed with their CSV line number; all valid rows are written in a single database transaction. The file is parsed in memory; an audit copy is saved in `uploads/` under a generated safe name and is never served.

---------------------------------------------------------------------------------------------------

## 4. Database design

Required tables (names/columns as specified): `users`, `courses`, `enrollments`, `activities`, `assessments`, `engagement_predictions`.
Added columns (all documented in `schema.sql`):

| Table | Added | Why |
|---|---|---|
| `users`, `courses`, `enrollments` | `created_at` | audit |
| `activities` | `source` (manual / csv_import / system) | separates manual demo entries from real events; `duration` is in **minutes** |
| `assessments` | `title`, `due_at`, `submitted_at`, `assessed_at` | duplicate detection, submission-delay feature, trends |
| `engagement_predictions` | `predicted_at`, `method`, `model_version`, `features_json` | prediction timestamp, ML vs. baseline, reproducibility |

**One extra table, `alerts`:** needed so alert status (open/acknowledged/resolved) persists and duplicate alerts can be prevented.
Constraints: foreign keys everywhere (`ON DELETE RESTRICT`), unique email, unique course name, unique `(course, student)` enrolment, unique activity `(student, course, type, time)`, unique assessment `(student, course, type, title)`, CHECK constraints on duration and scores, indexes on student/course/time columns. Multi-row writes (CSV import, batch predictions, alert generation) run in transactions. **All SQL uses `%s` parameters** - no string-built values.

---------------------------------------------------------------------------------------------------

## 5. Machine learning

**Goal:** estimate how engaged a student will be in a course over the **next 14 days**.

**Features** (`ml/feature_engineering.py`, same code in training and in the live app). Window = days *before* "now"; missing values: counts default to 0, `avg_quiz_score` / `avg_assignment_delay_days` are `NaN` when no data exists and are median-imputed inside the saved pipeline.

| Feature | Meaning | Unit | Window |
|---|---|---|---|
| login_count_28d | login events | count | 28 d |
| active_days_28d | distinct days with any activity | days | 28 d |
| activity_count_28d | all activities | count | 28 d |
| total_study_minutes_28d | study-session time | min | 28 d |
| video_minutes_28d | video-viewing time | min | 28 d |
| material_access_count_28d | material accesses | count | 28 d |
| avg_quiz_score | mean quiz score | 0-100 | 56 d |
| avg_assignment_delay_days | mean lateness (early = 0) | days | 56 d |
| days_since_last_activity | recency, capped at 60 | days | all |
| recent_7d_activity_count | activities in last week | count | 7 d |
| activity_trend | last 7 d minus avg weekly count of the 21 d before | count | 28 d |

**Target (no leakage):** engagement index of the *following* 14 days = `0.4*min(active_days/12,1) + 0.4*min(learning_minutes/1500,1) + 0.2*min(activities/100,1)` (x100). Labels: `<33` low, `<64` medium, else high (roughly balanced classes). Features only use data *before* the cut-off; the target only uses data *after* it.

**Synthetic data (assumptions in `ml/simulation.py`):** every student-course pair has a latent engagement level that drifts over time (so the future differs from the past); active-day probability, session counts/durations, quiz scores and assignment lateness depend on that level plus noise. 900 samples, seed 42, fully reproducible. **This is simulated data - results describe the simulation, not real students.**

**Training (`python -m ml.train_model`):** stratified 80/20 split; pipeline `SimpleImputer -> StandardScaler -> classifier`; candidates Logistic Regression and Random Forest compared by 5-fold stratified cross-validation (macro-F1) on the training split only; best is refit and evaluated once on the untouched test split; saved with joblib (`ml/saved_models/engagement_model.joblib`) with metrics in `metrics.json`. A transparent **rule-based baseline** is evaluated on the same test set for honest comparison.

**Results of the included model** (180 held-out synthetic test rows):

| | CV macro-F1 | Test macro-F1 |
|---|---|---|
| Logistic Regression | 0.498 | 0.540 |
| **Random Forest (selected)** | **0.521** | **0.545** |
| Rule-based baseline | - | 0.371 |

Selected model on the test set: accuracy 0.55, macro precision 0.541, macro recall 0.552, macro F1 0.545 (chance level for 3 balanced classes is ~0.33). Confusion matrix (rows = true, columns = predicted, order low / medium / high): `[[36,21,5],[19,21,20],[5,11,42]]`. The *medium* class is hard to predict (F1 0.37). **These are moderate results, not "highly accurate"**; the target is intentionally noisy because behaviour changes over time. Real data would need its own validation. Regression was not implemented.

**Score and risk:** `score = 100 x (0.5 x P(medium) + 1.0 x P(high))` (expected engagement, 0-100). Risk: **High** < 40, **Medium** 40-64.99, **Low** >= 65 (`RISK_HIGH_BELOW`, `RISK_MEDIUM_BELOW`). If no trained model can be loaded, the app falls back to the rule-based baseline and labels the result "Rule-based baseline (not ML)".
**Indicators** = feature importance x deviation from the training average, direction-aware. **Recommendations** are rule-based supportive suggestions. Predictions are decision-support estimates and never trigger penalties.

**Alert rules** (`alert_service.py`): high predicted risk; no activity for `INACTIVITY_DAYS` (14); at least 2 assessments averaging below `LOW_SCORE_THRESHOLD` (40) with the latest also below. No alert is created if an open/acknowledged one already exists for the student+course.

---------------------------------------------------------------------------------------------------

## 6. JSON endpoints

`GET /api/dashboard?start&end&course_id&student_id` - `GET /api/assessments/trend` - `GET /api/courses/<id>/students` - `POST /api/predictions/run` - `POST /api/predictions/batch`.
Errors are `{"ok": false, "error": "..."}` with 400 / 401 / 403 / 422 / 503. POSTs need the `X-CSRF-Token` header (the bundled JavaScript adds it).

---------------------------------------------------------------------------------------------------

## 7. Troubleshooting

| Problem | Fix |
|---|---|
| `Could not connect to the database` / error 1045 / 2003 | MySQL service not running (Windows *Services* > MySQL80 > Start); wrong `DB_USER`/`DB_PASSWORD`/`DB_PORT` in `.env`; database not created (run `schema.sql`). |
| `Unknown database 'student_engagement_db'` | Run `database\schema.sql` first, and keep `DB_NAME` equal to the name in the script. |
| `Authentication plugin 'caching_sha2_password'...` | Update `mysql-connector-python` (`pip install -U mysql-connector-python`). |
| `ModuleNotFoundError: No module named ...` | Activate the venv (`.\venv\Scripts\Activate.ps1`) and run `pip install -r requirements.txt`. |
| `No trained model found` banner on Predictions | Run `python -m ml.train_model` (it takes a few seconds). |
| "The saved model could not be loaded" after upgrading packages | Re-train: `python -m ml.train_model`. |
| `Address already in use` / port 5000 busy | Set `PORT=5001` in `.env` and open http://127.0.0.1:5001, or stop the other program. |
| Pages look unstyled / charts empty | The browser needs internet for the CDN files (Bootstrap, Chart.js). |
| Logged out after every restart | Set a fixed `SECRET_KEY` in `.env`. |
| Dashboard engagement KPIs show "-" | Run *Predict whole course* (see step 10); KPIs come from stored predictions. |
| Too many failed login attempts | Wait `LOGIN_LOCKOUT_MINUTES` (default 10) or restart the server. |

---------------------------------------------------------------------------------------------------

## 8. Security summary
Werkzeug password hashing (never plain text); server-side validation of every field; parameterised SQL; CSRF token on every POST/AJAX call; HttpOnly + SameSite cookies, optional `Secure`, configurable lifetime; session reset on login; generic login error messages and throttling after repeated failures; role checks (`faculty_required`) and row-level scope checks (`backend/utils/scope.py`) on every record, report and API call; open-redirect protection; CSV-formula escaping in exports; secrets only in `.env`.

## 9. Verification status and known limitations
* **Run and passing in the build environment:** the pytest suite (80 tests) against SQLite via `TestConfig`, covering auth, CSRF, authorisation, CRUD and delete safeguards, validation, CSV import, dashboard/analytics, features, training, prediction, alerts, reports, empty-DB and missing/corrupt-model cases, template/static paths, schema foreign keys, and a load of `seed.sql` into the test schema.
* **Not executed in the build environment:** a real MySQL server was unavailable, so `schema.sql`, `seed.sql` and the `mysql-connector-python` code path were **not run against MySQL** (the SQL is standard and kept portable, but expect to fix small issues if your MySQL version differs). Browser rendering (Bootstrap/Chart.js from CDN) was also not exercised, so **no screenshots are included**.
* MySQL 8.0.16+ is needed for CHECK constraints to be enforced.
* Login throttling is in-memory (per process). The ML model is trained on synthetic data only. Charts need internet access to load libraries.
