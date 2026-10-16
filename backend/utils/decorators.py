from functools import wraps

from flask import abort, jsonify, redirect, request, session, url_for, flash


def _wants_json():
    return request.path.startswith("/api/")


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            if _wants_json():
                return jsonify(ok=False, error="Authentication required."), 401
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapper


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(*args, **kwargs):
            if session.get("role") not in roles:
                if _wants_json():
                    return jsonify(ok=False, error="You do not have permission for this action."), 403
                abort(403)
            return view(*args, **kwargs)
        return wrapper
    return decorator


faculty_required = role_required("faculty")
