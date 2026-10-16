from backend.models import course as course_model
from extensions import get_db
from tests.conftest import post


def test_create_course_and_list(app, faculty, data):
    r = post(faculty, "/courses", {"course_name": "Algorithms", "semester": "Semester 4", "faculty_id": data["f1"]})
    assert r.status_code == 302
    assert "Algorithms" in faculty.get("/courses").get_data(as_text=True)


def test_course_validation_and_duplicate(faculty, data):
    r = post(faculty, "/courses", {"course_name": "ab", "semester": "", "faculty_id": data["f1"]}, follow_redirects=True)
    assert "at least 3 characters" in r.get_data(as_text=True)
    r = post(faculty, "/courses", {"course_name": "Course One", "semester": "S1", "faculty_id": data["f1"]}, follow_redirects=True)
    assert "already exists" in r.get_data(as_text=True)


def test_edit_course(app, faculty, data):
    post(faculty, f"/courses/{data['c1']}/edit", {"course_name": "Course One Renamed", "semester": "Semester 9", "faculty_id": data["f1"]})
    with app.app_context():
        assert course_model.get_course(get_db(), data["c1"])["course_name"] == "Course One Renamed"


def test_cannot_edit_or_view_other_faculty_course(faculty, data):
    assert post(faculty, f"/courses/{data['c2']}/edit", {"course_name": "Hack", "semester": "S", "faculty_id": data["f1"]}).status_code == 403
    assert faculty.get(f"/courses/{data['c2']}").status_code == 403
    assert post(faculty, f"/courses/{data['c2']}/delete").status_code == 403


def test_delete_blocked_when_related_records_exist(app, faculty, data):
    r = post(faculty, f"/courses/{data['c1']}/delete", follow_redirects=True)
    assert "cannot be deleted" in r.get_data(as_text=True)
    with app.app_context():
        assert course_model.get_course(get_db(), data["c1"]) is not None


def test_delete_empty_course(app, faculty, data):
    post(faculty, "/courses", {"course_name": "Temp Course", "semester": "S1", "faculty_id": data["f1"]})
    with app.app_context():
        cid = course_model.get_by_name(get_db(), "Temp Course")["course_id"]
    post(faculty, f"/courses/{cid}/delete")
    with app.app_context():
        assert course_model.get_course(get_db(), cid) is None


def test_student_cannot_manage_courses(student, data):
    assert post(student, "/courses", {"course_name": "Nope Course", "semester": "S", "faculty_id": data["f1"]}).status_code == 403
    assert student.get(f"/courses/{data['c2']}").status_code == 403
    assert student.get("/courses").status_code == 200


def test_enroll_and_unenroll(app, faculty, data):
    assert post(faculty, f"/courses/{data['c1']}/enroll", {"student_id": data["s3"]}).status_code == 302
    r = post(faculty, f"/courses/{data['c1']}/enroll", {"student_id": data["s3"]}, follow_redirects=True)
    assert "already enrolled" in r.get_data(as_text=True)
    r = post(faculty, f"/courses/{data['c1']}/unenroll", {"student_id": data["s3"]}, follow_redirects=True)
    assert "removed" in r.get_data(as_text=True)


def test_unenroll_blocked_when_history_exists(faculty, data):
    r = post(faculty, f"/courses/{data['c1']}/unenroll", {"student_id": data["s1"]}, follow_redirects=True)
    assert "Cannot remove" in r.get_data(as_text=True)


def test_course_search(faculty, data):
    html = faculty.get("/courses?q=One").get_data(as_text=True)
    assert "Course One" in html
    assert "No courses found" in faculty.get("/courses?q=zzz").get_data(as_text=True)
