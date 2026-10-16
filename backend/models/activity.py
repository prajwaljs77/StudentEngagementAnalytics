from backend.utils.sql import build_where, in_clause, like, page_args


def _conds(student_ids, course_ids, activity_type=None, start=None, end=None, search=None):
    conds = [in_clause("a.student_id", student_ids), in_clause("a.course_id", course_ids)]
    if activity_type:
        conds.append(("a.activity_type = %s", [activity_type]))
    if start:
        conds.append(("a.activity_time >= %s", [start]))
    if end:
        conds.append(("a.activity_time <= %s", [end]))
    if search:
        conds.append(("u.name LIKE %s ESCAPE '!'", [like(search)]))
    return conds


def add_activity(db, student_id, course_id, activity_type, duration, activity_time, source="manual"):
    return db.execute(
        """INSERT INTO activities (student_id, course_id, activity_type, duration, activity_time, source)
           VALUES (%s,%s,%s,%s,%s,%s)""", [student_id, course_id, activity_type, duration, activity_time, source])


def exists(db, student_id, course_id, activity_type, activity_time):
    return db.one("""SELECT 1 AS x FROM activities WHERE student_id=%s AND course_id=%s
                     AND activity_type=%s AND activity_time=%s""",
                  [student_id, course_id, activity_type, activity_time]) is not None


def get_activity(db, activity_id):
    return db.one("SELECT * FROM activities WHERE activity_id=%s", [activity_id])


def delete_activity(db, activity_id):
    db.execute("DELETE FROM activities WHERE activity_id=%s", [activity_id])


def list_activities(db, student_ids, course_ids, activity_type=None, start=None, end=None, search=None,
                    page=1, per_page=10, paginate=True):
    where, params = build_where(_conds(student_ids, course_ids, activity_type, start, end, search))
    base = """FROM activities a JOIN users u ON u.user_id=a.student_id
              JOIN courses c ON c.course_id=a.course_id"""
    total = db.scalar(f"SELECT COUNT(*) {base}{where}", params, 0)
    sql = f"""SELECT a.activity_id, a.student_id, u.name AS student_name, a.course_id, c.course_name,
                     a.activity_type, a.duration, a.activity_time, a.source {base}{where}
              ORDER BY a.activity_time DESC, a.activity_id DESC"""
    if paginate:
        page, per_page, offset = page_args(page, per_page)
        return db.all(sql + " LIMIT %s OFFSET %s", params + [per_page, offset]), total
    return db.all(sql, params), total


def raw_rows(db, student_ids, course_ids, start=None, end=None):
    """Lightweight rows for pandas analytics."""
    where, params = build_where(_conds(student_ids, course_ids, None, start, end))
    return db.all(f"""SELECT a.student_id, a.course_id, a.activity_type, a.duration, a.activity_time
                      FROM activities a{where}""", params)


def last_activity_by_student(db, student_ids, course_ids):
    c1, p1 = in_clause("student_id", student_ids)
    c2, p2 = in_clause("course_id", course_ids)
    return db.all(f"""SELECT student_id, MAX(activity_time) AS last_time FROM activities
                      WHERE {c1} AND {c2} GROUP BY student_id""", p1 + p2)


def for_student_course(db, student_id, course_id, since):
    return db.all("""SELECT activity_type, duration, activity_time FROM activities
                     WHERE student_id=%s AND course_id=%s AND activity_time >= %s""", [student_id, course_id, since])
