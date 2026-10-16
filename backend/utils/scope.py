"""Row-level authorization: which courses / students may the current user see?
Faculty -> courses they own and the students enrolled in them. Student -> only themselves."""
from backend.utils.sql import in_clause


def visible_course_ids(db, user):
    if user["role"] == "faculty":
        rows = db.all("SELECT course_id FROM courses WHERE faculty_id = %s", [user["user_id"]])
    else:
        rows = db.all("SELECT course_id FROM enrollments WHERE student_id = %s", [user["user_id"]])
    return [r["course_id"] for r in rows]


def visible_student_ids(db, user, course_ids=None):
    if user["role"] == "student":
        return [user["user_id"]]
    course_ids = visible_course_ids(db, user) if course_ids is None else course_ids
    clause, params = in_clause("course_id", course_ids)
    rows = db.all(f"SELECT DISTINCT student_id FROM enrollments WHERE {clause}", params)
    return [r["student_id"] for r in rows]


def can_access_course(db, user, course_id):
    return course_id in visible_course_ids(db, user)


def can_access_student(db, user, student_id):
    if user["role"] == "student":
        return student_id == user["user_id"]
    return student_id in visible_student_ids(db, user)


def can_access_pair(db, user, student_id, course_id):
    """Student must be enrolled in the course AND the user must be allowed to see that course."""
    if not can_access_course(db, user, course_id):
        return False
    if user["role"] == "student" and student_id != user["user_id"]:
        return False
    row = db.one("SELECT 1 AS ok FROM enrollments WHERE student_id=%s AND course_id=%s", [student_id, course_id])
    return row is not None
