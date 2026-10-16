"""Safe CSV import for activities and assessments (faculty only).
 * extension / size / required-column checks, row-by-row validation, duplicate handling
 * the upload is parsed in memory; a copy is kept under uploads/ with a generated safe name (never served)
 * valid rows are written in ONE database transaction; invalid rows are reported and skipped."""
import csv
import io
import os
import uuid
from datetime import datetime

from werkzeug.utils import secure_filename

from backend.models import activity as activity_model
from backend.models import assessment as assessment_model
from backend.utils import validators as v
from backend.utils.scope import visible_course_ids
from backend.utils.sql import in_clause

ACTIVITY_COLUMNS = ["student_email", "course_name", "activity_type", "duration", "activity_time"]
ASSESSMENT_COLUMNS = ["student_email", "course_name", "assessment_type", "title", "score"]
ASSESSMENT_OPTIONAL = ["due_at", "submitted_at", "assessed_at"]
MAX_ROWS = 5000


class ImportError_(Exception):
    """A file-level problem (bad extension, size, columns) - shown to the user as-is."""


def _read_csv(file_storage, cfg, required):
    if file_storage is None or not file_storage.filename:
        raise ImportError_("Please choose a CSV file.")
    name = secure_filename(file_storage.filename)
    if not name.lower().endswith(".csv"):
        raise ImportError_("Only .csv files are accepted.")
    data = file_storage.read(cfg["MAX_CONTENT_LENGTH"] + 1)
    if len(data) > cfg["MAX_CONTENT_LENGTH"]:
        raise ImportError_(f"File is larger than {cfg['MAX_UPLOAD_MB']} MB.")
    if not data.strip():
        raise ImportError_("The file is empty.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ImportError_("The file must be UTF-8 encoded text.")
    reader = csv.DictReader(io.StringIO(text))
    headers = [(h or "").strip().lower() for h in (reader.fieldnames or [])]
    missing = [c for c in required if c not in headers]
    if missing:
        raise ImportError_("Missing required column(s): " + ", ".join(missing) + ". Expected: " + ", ".join(required))
    rows = []
    for i, raw in enumerate(reader, start=2):
        if i - 1 > MAX_ROWS:
            raise ImportError_(f"Too many rows (maximum {MAX_ROWS}).")
        rows.append((i, {(k or "").strip().lower(): (val or "").strip() for k, val in raw.items()}))
    if not rows:
        raise ImportError_("The file has a header but no data rows.")
    try:  # keep an audit copy under a generated safe name; the folder is not web-accessible
        os.makedirs(cfg["UPLOAD_FOLDER"], exist_ok=True)
        with open(os.path.join(cfg["UPLOAD_FOLDER"], f"{uuid.uuid4().hex[:12]}_{name}"), "wb") as fh:
            fh.write(data)
    except OSError:
        pass
    return rows


def _lookups(db, user):
    course_ids = visible_course_ids(db, user)
    courses = {}
    if course_ids:
        for r in db.all(f"SELECT course_id, course_name FROM courses WHERE {in_clause('course_id', course_ids)[0]}", course_ids):
            courses[r["course_name"].lower()] = r["course_id"]
    students = {r["email"]: r["user_id"] for r in db.all("SELECT user_id, email FROM users WHERE role='student'")}
    enrolled = {(r["student_id"], r["course_id"]) for r in db.all("SELECT student_id, course_id FROM enrollments")}
    return courses, students, enrolled


def _summary(total, ok, rejected):
    return {"total": total, "imported": ok, "rejected": len(rejected), "errors": rejected[:50],
            "more_errors": max(0, len(rejected) - 50)}


def _resolve(row, courses, students, enrolled):
    sid = students.get(row.get("student_email", "").lower())
    if not sid:
        return None, None, "student email not found (or not a student)"
    cid = courses.get(row.get("course_name", "").lower())
    if not cid:
        return None, None, "course not found among your courses"
    if (sid, cid) not in enrolled:
        return None, None, "student is not enrolled in this course"
    return sid, cid, None


def import_activities(db, cfg, user, file_storage):
    rows = _read_csv(file_storage, cfg, ACTIVITY_COLUMNS)
    courses, students, enrolled = _lookups(db, user)
    good, rejected, seen = [], [], set()
    for line, row in rows:
        sid, cid, err = _resolve(row, courses, students, enrolled)
        atype = row.get("activity_type", "").lower()
        if not err and atype not in v.ACTIVITY_TYPES:
            err = f"activity_type must be one of: {', '.join(v.ACTIVITY_TYPES)}"
        duration = when = None
        if not err:
            duration, err = v.parse_duration(row.get("duration"), atype)
        if not err:
            when, err = v.parse_datetime(row.get("activity_time"))
        if not err:
            key = (sid, cid, atype, when)
            if key in seen or activity_model.exists(db, sid, cid, atype, when):
                err = "duplicate record"
            seen.add(key)
        if err:
            rejected.append({"line": line, "error": err})
        else:
            good.append((sid, cid, atype, duration, when))
    with db.tx():
        for sid, cid, atype, duration, when in good:
            activity_model.add_activity(db, sid, cid, atype, duration, when, "csv_import")
    return _summary(len(rows), len(good), rejected)


def import_assessments(db, cfg, user, file_storage):
    rows = _read_csv(file_storage, cfg, ASSESSMENT_COLUMNS)
    courses, students, enrolled = _lookups(db, user)
    good, rejected, seen = [], [], set()
    now = datetime.now().replace(microsecond=0)
    for line, row in rows:
        sid, cid, err = _resolve(row, courses, students, enrolled)
        atype = row.get("assessment_type", "").lower()
        if not err and atype not in v.ASSESSMENT_TYPES:
            err = "assessment_type must be quiz or assignment"
        title = v.clean_text(row.get("title"), 150)
        if not err and not title:
            err = "title is required"
        score = due = sub = when = None
        if not err:
            score, err = v.parse_score(row.get("score"), cfg["ASSESSMENT_MAX_SCORE"])
        if not err:
            due, err = v.parse_datetime(row.get("due_at"), allow_blank=True, allow_future=True)
        if not err:
            sub, err = v.parse_datetime(row.get("submitted_at"), allow_blank=True)
        if not err:
            when, err = v.parse_datetime(row.get("assessed_at"), allow_blank=True)
            when = when or now
        if not err and (due is None) != (sub is None):
            err = "due_at and submitted_at must be supplied together"
        if not err:
            key = (sid, cid, atype, title.lower())
            if key in seen or assessment_model.exists(db, sid, cid, atype, title):
                err = "duplicate assessment (same student, course, type and title)"
            seen.add(key)
        if err:
            rejected.append({"line": line, "error": err})
        else:
            good.append((sid, cid, score, atype, title, due, sub, when))
    with db.tx():
        for g in good:
            assessment_model.add_assessment(db, *g)
    return _summary(len(rows), len(good), rejected)
