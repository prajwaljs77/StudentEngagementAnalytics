"""Small helpers for building safe, parameterised SQL fragments."""


def in_clause(column, values):
    """('col IN (%s,%s)', [1,2]) ; empty list => always-false clause."""
    values = list(values)
    if not values:
        return "1=0", []
    return f"{column} IN ({','.join(['%s'] * len(values))})", values


def build_where(conditions):
    """conditions: list of (sql_fragment, list_of_params). Returns (' WHERE ...', params)."""
    sqls, params = [], []
    for sql, p in conditions:
        sqls.append(sql)
        params.extend(p)
    return (" WHERE " + " AND ".join(sqls) if sqls else ""), params


def like(term):
    """Pattern for `LIKE %s ESCAPE '!'` (works the same on MySQL and SQLite)."""
    term = (term or "").replace("!", "!!").replace("%", "!%").replace("_", "!_")
    return f"%{term}%"


def page_args(page, per_page):
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1
    return page, per_page, (page - 1) * per_page
