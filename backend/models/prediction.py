from backend.utils.sql import build_where, in_clause, page_args


def add_prediction(db, student_id, course_id, score, risk, predicted_at, method, model_version, features_json):
    return db.execute(
        """INSERT INTO engagement_predictions (student_id, course_id, engagement_score, risk_level, predicted_at,
           method, model_version, features_json) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        [student_id, course_id, score, risk, predicted_at, method, model_version, features_json])


def get_prediction(db, prediction_id):
    return db.one("SELECT * FROM engagement_predictions WHERE prediction_id=%s", [prediction_id])


_LATEST = """(SELECT MAX(prediction_id) AS mid FROM engagement_predictions GROUP BY student_id, course_id)"""


def latest_predictions(db, student_ids, course_ids, risk=None):
    """Most recent prediction for each student/course pair."""
    c1, p1 = in_clause("p.student_id", student_ids)
    c2, p2 = in_clause("p.course_id", course_ids)
    sql = f"""SELECT p.*, u.name AS student_name, c.course_name FROM engagement_predictions p
              JOIN {_LATEST} m ON m.mid = p.prediction_id
              JOIN users u ON u.user_id=p.student_id JOIN courses c ON c.course_id=p.course_id
              WHERE {c1} AND {c2}"""
    params = p1 + p2
    if risk:
        sql += " AND p.risk_level = %s"
        params.append(risk)
    return db.all(sql + " ORDER BY p.engagement_score ASC", params)


def list_history(db, student_ids, course_ids, student_id=None, course_id=None, risk=None, start=None, end=None,
                 page=1, per_page=10, paginate=True):
    conds = [in_clause("p.student_id", student_ids), in_clause("p.course_id", course_ids)]
    if student_id:
        conds.append(("p.student_id = %s", [student_id]))
    if course_id:
        conds.append(("p.course_id = %s", [course_id]))
    if risk:
        conds.append(("p.risk_level = %s", [risk]))
    if start:
        conds.append(("p.predicted_at >= %s", [start]))
    if end:
        conds.append(("p.predicted_at <= %s", [end]))
    where, params = build_where(conds)
    base = """FROM engagement_predictions p JOIN users u ON u.user_id=p.student_id
              JOIN courses c ON c.course_id=p.course_id"""
    total = db.scalar(f"SELECT COUNT(*) {base}{where}", params, 0)
    sql = f"""SELECT p.*, u.name AS student_name, c.course_name {base}{where}
              ORDER BY p.predicted_at DESC, p.prediction_id DESC"""
    if paginate:
        page, per_page, offset = page_args(page, per_page)
        return db.all(sql + " LIMIT %s OFFSET %s", params + [per_page, offset]), total
    return db.all(sql, params), total
