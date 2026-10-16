from backend.utils.sql import in_clause


def enroll(db, course_id, student_id, enrolled_at):
    return db.execute("INSERT INTO enrollments (course_id, student_id, enrolled_at) VALUES (%s,%s,%s)",
                      [course_id, student_id, enrolled_at])


def is_enrolled(db, student_id, course_id):
    return db.one("SELECT 1 AS x FROM enrollments WHERE student_id=%s AND course_id=%s", [student_id, course_id]) is not None


def unenroll(db, course_id, student_id):
    db.execute("DELETE FROM enrollments WHERE course_id=%s AND student_id=%s", [course_id, student_id])


def students_in_course(db, course_id):
    return db.all("""SELECT u.user_id, u.name, u.email, e.enrolled_at FROM enrollments e
                     JOIN users u ON u.user_id=e.student_id WHERE e.course_id=%s ORDER BY u.name""", [course_id])


def courses_of_student(db, student_id, course_ids=None):
    sql = """SELECT c.course_id, c.course_name, c.semester, e.enrolled_at FROM enrollments e
             JOIN courses c ON c.course_id=e.course_id WHERE e.student_id=%s"""
    params = [student_id]
    if course_ids is not None:
        clause, p = in_clause("c.course_id", course_ids)
        sql += f" AND {clause}"
        params += p
    return db.all(sql + " ORDER BY c.course_name", params)


def pairs(db, course_ids, student_ids=None):
    """All (student, course) enrollments inside the given scope."""
    clause, params = in_clause("e.course_id", course_ids)
    sql = f"""SELECT e.student_id, e.course_id, u.name AS student_name, c.course_name
              FROM enrollments e JOIN users u ON u.user_id=e.student_id
              JOIN courses c ON c.course_id=e.course_id WHERE {clause}"""
    if student_ids is not None:
        c2, p2 = in_clause("e.student_id", student_ids)
        sql += f" AND {c2}"
        params += p2
    return db.all(sql + " ORDER BY u.name, c.course_name", params)


def unenrolled_students(db, course_id):
    return db.all("""SELECT user_id, name, email FROM users WHERE role='student' AND user_id NOT IN
                     (SELECT student_id FROM enrollments WHERE course_id=%s) ORDER BY name""", [course_id])
