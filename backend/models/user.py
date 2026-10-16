from backend.utils.sql import build_where, like, page_args


def create_user(db, name, email, password_hash, role, created_at):
    return db.execute(
        "INSERT INTO users (name, email, password_hash, role, created_at) VALUES (%s,%s,%s,%s,%s)",
        [name, email, password_hash, role, created_at])


def get_user(db, user_id):
    return db.one("SELECT user_id, name, email, role, created_at FROM users WHERE user_id=%s", [user_id])


def get_by_email(db, email):
    return db.one("SELECT * FROM users WHERE email=%s", [email])


def list_faculty(db):
    return db.all("SELECT user_id, name FROM users WHERE role='faculty' ORDER BY name")


def list_students(db, search=None, course_id=None, page=1, per_page=10):
    conds = [("u.role = 'student'", [])]
    if search:
        conds.append(("(u.name LIKE %s ESCAPE '!' OR u.email LIKE %s ESCAPE '!')", [like(search), like(search)]))
    if course_id:
        conds.append(("u.user_id IN (SELECT student_id FROM enrollments WHERE course_id=%s)", [course_id]))
    where, params = build_where(conds)
    page, per_page, offset = page_args(page, per_page)
    total = db.scalar(f"SELECT COUNT(*) FROM users u{where}", params, 0)
    rows = db.all(
        f"""SELECT u.user_id, u.name, u.email, u.created_at,
                   (SELECT COUNT(*) FROM enrollments e WHERE e.student_id=u.user_id) AS course_count,
                   (SELECT MAX(a.activity_time) FROM activities a WHERE a.student_id=u.user_id) AS last_activity
            FROM users u{where} ORDER BY u.name LIMIT %s OFFSET %s""", params + [per_page, offset])
    return rows, total


def update_user(db, user_id, name, email, password_hash=None):
    if password_hash:
        db.execute("UPDATE users SET name=%s, email=%s, password_hash=%s WHERE user_id=%s",
                   [name, email, password_hash, user_id])
    else:
        db.execute("UPDATE users SET name=%s, email=%s WHERE user_id=%s", [name, email, user_id])


def dependency_counts(db, user_id):
    """Rows that reference this user (block deletion when > 0)."""
    q = {
        "enrollments": "SELECT COUNT(*) FROM enrollments WHERE student_id=%s",
        "activities": "SELECT COUNT(*) FROM activities WHERE student_id=%s",
        "assessments": "SELECT COUNT(*) FROM assessments WHERE student_id=%s",
        "predictions": "SELECT COUNT(*) FROM engagement_predictions WHERE student_id=%s",
        "alerts": "SELECT COUNT(*) FROM alerts WHERE student_id=%s",
        "courses": "SELECT COUNT(*) FROM courses WHERE faculty_id=%s",
    }
    return {k: db.scalar(v, [user_id], 0) for k, v in q.items()}


def delete_user(db, user_id):
    db.execute("DELETE FROM users WHERE user_id=%s", [user_id])


def student_taught_by_others(db, faculty_id, student_id):
    row = db.one("""SELECT 1 AS x FROM enrollments e JOIN courses c ON c.course_id=e.course_id
                    WHERE e.student_id=%s AND c.faculty_id<>%s""", [student_id, faculty_id])
    return row is not None
