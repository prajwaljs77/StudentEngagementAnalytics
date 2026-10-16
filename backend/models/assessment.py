from backend.utils.sql import build_where, in_clause, like, page_args


def _conds(student_ids, course_ids, assessment_type=None, start=None, end=None, search=None):
    conds = [in_clause("a.student_id", student_ids), in_clause("a.course_id", course_ids)]
    if assessment_type:
        conds.append(("a.assessment_type = %s", [assessment_type]))
    if start:
        conds.append(("a.assessed_at >= %s", [start]))
    if end:
        conds.append(("a.assessed_at <= %s", [end]))
    if search:
        conds.append(("(u.name LIKE %s ESCAPE '!' OR a.title LIKE %s ESCAPE '!')", [like(search), like(search)]))
    return conds


def add_assessment(db, student_id, course_id, score, assessment_type, title, due_at, submitted_at, assessed_at):
    return db.execute(
        """INSERT INTO assessments (student_id, course_id, score, assessment_type, title, due_at, submitted_at, assessed_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        [student_id, course_id, score, assessment_type, title, due_at, submitted_at, assessed_at])


def update_assessment(db, assessment_id, score, assessment_type, title, due_at, submitted_at, assessed_at):
    db.execute("""UPDATE assessments SET score=%s, assessment_type=%s, title=%s, due_at=%s, submitted_at=%s,
                  assessed_at=%s WHERE assessment_id=%s""",
               [score, assessment_type, title, due_at, submitted_at, assessed_at, assessment_id])


def exists(db, student_id, course_id, assessment_type, title, exclude_id=None):
    row = db.one("""SELECT assessment_id FROM assessments WHERE student_id=%s AND course_id=%s
                    AND assessment_type=%s AND title=%s""", [student_id, course_id, assessment_type, title])
    return bool(row) and row["assessment_id"] != exclude_id


def get_assessment(db, assessment_id):
    return db.one("SELECT * FROM assessments WHERE assessment_id=%s", [assessment_id])


def delete_assessment(db, assessment_id):
    db.execute("DELETE FROM assessments WHERE assessment_id=%s", [assessment_id])


def list_assessments(db, student_ids, course_ids, assessment_type=None, start=None, end=None, search=None,
                     page=1, per_page=10, paginate=True):
    where, params = build_where(_conds(student_ids, course_ids, assessment_type, start, end, search))
    base = """FROM assessments a JOIN users u ON u.user_id=a.student_id
              JOIN courses c ON c.course_id=a.course_id"""
    total = db.scalar(f"SELECT COUNT(*) {base}{where}", params, 0)
    sql = f"""SELECT a.*, u.name AS student_name, c.course_name {base}{where}
              ORDER BY a.assessed_at DESC, a.assessment_id DESC"""
    if paginate:
        page, per_page, offset = page_args(page, per_page)
        return db.all(sql + " LIMIT %s OFFSET %s", params + [per_page, offset]), total
    return db.all(sql, params), total


def recent_for_student_course(db, student_id, course_id, since):
    return db.all("""SELECT assessment_type, score, due_at, submitted_at, assessed_at FROM assessments
                     WHERE student_id=%s AND course_id=%s AND assessed_at >= %s""", [student_id, course_id, since])
