"""Server-side validation helpers. Each returns (value, error_message)."""
import re
from datetime import datetime, timedelta

ACTIVITY_TYPES = {
    "login": "Login",
    "video": "Video viewing",
    "material": "Learning material access",
    "study_session": "Study session",
}
ASSESSMENT_TYPES = {"quiz": "Quiz", "assignment": "Assignment"}
MAX_DURATION_MIN = 1440
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
DT_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d")


def clean_text(value, max_len=150):
    return re.sub(r"\s+", " ", (value or "")).strip()[:max_len]


def validate_name(value):
    value = clean_text(value, 100)
    if len(value) < 2:
        return None, "Name must be at least 2 characters."
    return value, None


def validate_email(value):
    value = (value or "").strip().lower()
    if not EMAIL_RE.match(value) or len(value) > 150:
        return None, "Enter a valid email address."
    return value, None


def validate_password(value):
    value = value or ""
    if len(value) < 8:
        return None, "Password must be at least 8 characters."
    if not (re.search(r"[A-Za-z]", value) and re.search(r"\d", value)):
        return None, "Password must contain at least one letter and one number."
    return value, None


def validate_role(value):
    return (value, None) if value in ("student", "faculty") else (None, "Choose a valid role.")


def validate_course_name(value):
    value = clean_text(value, 150)
    return (value, None) if len(value) >= 3 else (None, "Course name must be at least 3 characters.")


def validate_semester(value):
    value = clean_text(value, 30)
    return (value, None) if value else (None, "Semester is required (for example: Semester 3).")


def parse_int(value, field="Value", minimum=None, maximum=None):
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None, f"{field} must be a whole number."
    if minimum is not None and number < minimum:
        return None, f"{field} must be at least {minimum}."
    if maximum is not None and number > maximum:
        return None, f"{field} must not exceed {maximum}."
    return number, None


def parse_duration(value, activity_type="study_session"):
    number, err = parse_int(value, "Duration (minutes)", 0, MAX_DURATION_MIN)
    if err:
        return None, err
    if activity_type != "login" and number < 1:
        return None, "Duration must be at least 1 minute for this activity type."
    return number, None


def parse_score(value, max_score=100):
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None, "Score must be a number."
    if number != number or number in (float("inf"), float("-inf")):
        return None, "Score must be a finite number."
    if number < 0:
        return None, "Score cannot be negative."
    if number > max_score:
        return None, f"Score cannot exceed the maximum of {max_score:g}."
    return round(number, 2), None


def parse_datetime(value, allow_blank=False, allow_future=False):
    value = (value or "").strip()
    if not value:
        return (None, None) if allow_blank else (None, "Date and time is required.")
    for fmt in DT_FORMATS:
        try:
            parsed = datetime.strptime(value, fmt)
            break
        except ValueError:
            parsed = None
    if parsed is None:
        return None, "Use the format YYYY-MM-DD HH:MM."
    if not allow_future and parsed > datetime.now() + timedelta(minutes=5):
        return None, "Date and time cannot be in the future."
    if parsed.year < 2000:
        return None, "Date is too far in the past."
    return parsed, None


def parse_date(value):
    try:
        return datetime.strptime((value or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def validate_choice(value, allowed, label):
    return (value, None) if value in allowed else (None, f"Choose a valid {label}.")
