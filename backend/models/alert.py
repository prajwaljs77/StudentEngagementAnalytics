from backend.utils.sql import build_where, in_clause, page_args


def open_exists(db, student_id, course_id):
    return db.one("""SELECT alert_id FROM alerts WHERE student_id=%s AND course_id=%s
                     AND status IN ('open','acknowledged')""", [student_id, course_id]) is not None


def create_alert(db, student_id, course_id, prediction_id, score, risk, reason, action, now):
    return db.execute(
        """INSERT INTO alerts (student_id, course_id, prediction_id, engagement_score, risk_level, reason,
           suggested_action, status, created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,'open',%s,%s)""",
        [student_id, course_id, prediction_id, score, risk, reason, action, now, now])


def get_alert(db, alert_id):
    return db.one("SELECT * FROM alerts WHERE alert_id=%s", [alert_id])


def set_status(db, alert_id, status, now):
    db.execute("UPDATE alerts SET status=%s, updated_at=%s WHERE alert_id=%s", [status, now, alert_id])


def list_alerts(db, student_ids, course_ids, status=None, risk=None, page=1, per_page=10, paginate=True):
    conds = [in_clause("a.student_id", student_ids), in_clause("a.course_id", course_ids)]
    if status:
        conds.append(("a.status = %s", [status]))
    if risk:
        conds.append(("a.risk_level = %s", [risk]))
    where, params = build_where(conds)
    base = """FROM alerts a JOIN users u ON u.user_id=a.student_id JOIN courses c ON c.course_id=a.course_id"""
    total = db.scalar(f"SELECT COUNT(*) {base}{where}", params, 0)
    sql = f"""SELECT a.*, u.name AS student_name, c.course_name {base}{where}
              ORDER BY CASE a.status WHEN 'open' THEN 0 WHEN 'acknowledged' THEN 1 ELSE 2 END, a.engagement_score ASC,
              a.created_at DESC"""
    if paginate:
        page, per_page, offset = page_args(page, per_page)
        return db.all(sql + " LIMIT %s OFFSET %s", params + [per_page, offset]), total
    return db.all(sql, params), total
