from datetime import datetime, timedelta

from backend.models import activity as activity_model
from backend.models import user as user_model
from extensions import get_db
from tests.conftest import PASSWORD, post


def test_create_edit_delete_student(app, faculty, data):
    post(faculty, "/students", {"name": "Brand New", "email": "brand@x.edu", "password": PASSWORD})
    with app.app_context():
        sid = user_model.get_by_email(get_db(), "brand@x.edu")["user_id"]
    post(faculty, f"/students/{sid}/edit", {"name": "Brand Newer", "email": "brand@x.edu", "password": ""})
    with app.app_context():
        assert user_model.get_user(get_db(), sid)["name"] == "Brand Newer"
    post(faculty, f"/students/{sid}/delete")
    with app.app_context():
        assert user_model.get_user(get_db(), sid) is None


def test_delete_student_with_records_is_blocked(app, faculty, data):
    r = post(faculty, f"/students/{data['s1']}/delete", follow_redirects=True)
    assert "cannot be deleted" in r.get_data(as_text=True)
    with app.app_context():
        assert user_model.get_user(get_db(), data["s1"]) is not None


def test_student_search_and_validation(faculty, data):
    assert "Active Student" in faculty.get("/students?q=Active").get_data(as_text=True)
    assert "No students found" in faculty.get("/students?q=nomatch").get_data(as_text=True)
    r = post(faculty, "/students", {"name": "X", "email": "nope", "password": "123"}, follow_redirects=True)
    assert "valid email" in r.get_data(as_text=True)


def test_student_access_control(student, faculty, data):
    assert student.get(f"/students/{data['s1']}").status_code == 200
    assert student.get(f"/students/{data['s2']}").status_code == 403
    assert faculty.get(f"/students/{data['s1']}").status_code == 200
    assert faculty.get(f"/students/{data['s3']}").status_code == 403  # enrolled only with another faculty
    assert faculty.get("/students/99999").status_code == 404


def test_add_activity_validation(app, faculty, data):
    base = {"course_id": data["c1"], "student_id": data["s2"], "activity_type": "video", "duration": "25",
            "activity_time": (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")}
    r = post(faculty, "/activities", {**base, "duration": "-5"}, follow_redirects=True)
    assert "at least 0" in r.get_data(as_text=True)
    r = post(faculty, "/activities", {**base, "duration": "abc"}, follow_redirects=True)
    assert "whole number" in r.get_data(as_text=True)
    r = post(faculty, "/activities", {**base, "duration": "9999"}, follow_redirects=True)
    assert "must not exceed" in r.get_data(as_text=True)
    r = post(faculty, "/activities", {**base, "activity_time": (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")}, follow_redirects=True)
    assert "future" in r.get_data(as_text=True)
    r = post(faculty, "/activities", {**base, "activity_type": "hack"}, follow_redirects=True)
    assert "valid activity type" in r.get_data(as_text=True)
    assert post(faculty, "/activities", base).status_code == 302
    r = post(faculty, "/activities", base, follow_redirects=True)
    assert "already exists" in r.get_data(as_text=True)


def test_activity_for_unenrolled_student_rejected(faculty, data):
    r = post(faculty, "/activities", {"course_id": data["c1"], "student_id": data["s3"], "activity_type": "video", "duration": "10",
                                      "activity_time": "2024-01-01T10:00"}, follow_redirects=True)
    assert "not enrolled" in r.get_data(as_text=True)


def test_student_records_only_own_activity(app, student, data):
    r = post(student, "/activities", {"course_id": data["c1"], "student_id": data["s2"], "activity_type": "study_session",
                                      "duration": "30", "activity_time": "2024-02-01T09:00"})
    assert r.status_code == 302
    with app.app_context():
        rows = get_db().all("SELECT student_id FROM activities WHERE activity_time='2024-02-01 09:00:00'")
    assert [r["student_id"] for r in rows] == [data["s1"]]


def test_student_sees_only_own_activities(student, data):
    html = student.get("/activities").get_data(as_text=True)
    assert "Inactive Student" not in html and "Course Two" not in html


def test_delete_activity_permissions(app, faculty, student, data):
    with app.app_context():
        aid = get_db().scalar("SELECT activity_id FROM activities WHERE student_id=%s LIMIT 1", [data["s1"]])
        other = get_db().scalar("SELECT activity_id FROM activities WHERE student_id=%s LIMIT 1", [data["s2"]])
    post(student, f"/activities/{other}/delete")
    with app.app_context():
        assert activity_model.get_activity(get_db(), other) is not None
    post(faculty, f"/activities/{aid}/delete")
    with app.app_context():
        assert activity_model.get_activity(get_db(), aid) is None


def test_assessment_crud_and_validation(app, faculty, data):
    base = {"course_id": data["c1"], "student_id": data["s2"], "assessment_type": "assignment", "title": "Assignment 9", "score": "70"}
    r = post(faculty, "/assessments", {**base, "score": "101"}, follow_redirects=True)
    assert "cannot exceed" in r.get_data(as_text=True)
    r = post(faculty, "/assessments", {**base, "score": "-1"}, follow_redirects=True)
    assert "cannot be negative" in r.get_data(as_text=True)
    r = post(faculty, "/assessments", {**base, "due_at": "2024-01-01T10:00"}, follow_redirects=True)
    assert "both due date" in r.get_data(as_text=True)
    assert "saved" in post(faculty, "/assessments", base, follow_redirects=True).get_data(as_text=True)
    assert "already has" in post(faculty, "/assessments", base, follow_redirects=True).get_data(as_text=True)
    with app.app_context():
        aid = get_db().scalar("SELECT assessment_id FROM assessments WHERE title='Assignment 9'")
    post(faculty, f"/assessments/{aid}/edit", {"assessment_type": "assignment", "title": "Assignment 9", "score": "88"})
    with app.app_context():
        assert get_db().scalar("SELECT score FROM assessments WHERE assessment_id=%s", [aid]) == 88
    post(faculty, f"/assessments/{aid}/delete")
    with app.app_context():
        assert get_db().scalar("SELECT COUNT(*) FROM assessments WHERE assessment_id=%s", [aid]) == 0


def test_assessment_permissions(student, faculty2, data):
    assert post(student, "/assessments", {"course_id": data["c1"], "student_id": data["s1"], "assessment_type": "quiz", "title": "Q", "score": "50"}).status_code == 403
    r = post(faculty2, "/assessments", {"course_id": data["c1"], "student_id": data["s1"], "assessment_type": "quiz", "title": "Q", "score": "50"}, follow_redirects=True)
    assert "not enrolled in one of your courses" in r.get_data(as_text=True)
    html = student.get("/assessments").get_data(as_text=True)
    assert "Quiz 2" not in html  # s2's result is not visible to s1


def test_low_score_students_identified(faculty):
    assert "Inactive Student" in faculty.get("/assessments").get_data(as_text=True)
