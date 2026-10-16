from backend.utils.sql import build_where, in_clause, like, page_args


def list_courses(db, course_ids, search=None, semester=None, page=1, per_page=10):
    clause, p = in_clause("c.course_id", course_ids)
    conds = [(clause, p)]
    if search:
        conds.append(("c.course_name LIKE %s ESCAPE '!'", [like(search)]))
    if semester:
        conds.append(("c.semester = %s", [semester]))
    where, params = build_where(conds)
    page, per_page, offset = page_args(page, per_page)
    total = db.scalar(f"SELECT COUNT(*) FROM courses c{where}", params, 0)
    rows = db.all(
        f"""SELECT c.course_id, c.course_name, c.semester, c.faculty_id, u.name AS faculty_name,
                   (SELECT COUNT(*) FROM enrollments e WHERE e.course_id=c.course_id) AS enrolled_count
            FROM courses c JOIN users u ON u.user_id=c.faculty_id{where}
            ORDER BY c.course_name LIMIT %s OFFSET %s""", params + [per_page, offset])
    return rows, total


def semesters(db, course_ids):
    clause, p = in_clause("course_id", course_ids)
    return [r["semester"] for r in db.all(f"SELECT DISTINCT semester FROM courses WHERE {clause} ORDER BY semester", p)]


def get_course(db, course_id):
    return db.one("""SELECT c.*, u.name AS faculty_name FROM courses c
                     JOIN users u ON u.user_id=c.faculty_id WHERE c.course_id=%s""", [course_id])


def get_by_name(db, name):
    return db.one("SELECT * FROM courses WHERE course_name=%s", [name])


def create_course(db, name, faculty_id, semester, created_at):
    return db.execute("INSERT INTO courses (course_name, faculty_id, semester, created_at) VALUES (%s,%s,%s,%s)",
                      [name, faculty_id, semester, created_at])


def update_course(db, course_id, name, faculty_id, semester):
    db.execute("UPDATE courses SET course_name=%s, faculty_id=%s, semester=%s WHERE course_id=%s",
               [name, faculty_id, semester, course_id])


def dependency_counts(db, course_id):
    q = {
        "enrollments": "SELECT COUNT(*) FROM enrollments WHERE course_id=%s",
        "activities": "SELECT COUNT(*) FROM activities WHERE course_id=%s",
        "assessments": "SELECT COUNT(*) FROM assessments WHERE course_id=%s",
        "predictions": "SELECT COUNT(*) FROM engagement_predictions WHERE course_id=%s",
        "alerts": "SELECT COUNT(*) FROM alerts WHERE course_id=%s",
    }
    return {k: db.scalar(v, [course_id], 0) for k, v in q.items()}


def delete_course(db, course_id):
    db.execute("DELETE FROM courses WHERE course_id=%s", [course_id])
