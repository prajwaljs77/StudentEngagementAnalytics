import io

from extensions import get_db
from tests.conftest import TOKEN


def _upload(client, url, content, name="data.csv"):
    with client.session_transaction() as s:
        s["_csrf"] = TOKEN
    return client.post(url, data={"csrf_token": TOKEN, "file": (io.BytesIO(content.encode()), name)},
                       content_type="multipart/form-data", follow_redirects=True)


HEAD = "student_email,course_name,activity_type,duration,activity_time\n"


def test_import_activities_summary(app, faculty, data):
    csv = HEAD + "\n".join([
        "s2@x.edu,Course One,video,30,2024-03-01 10:00",
        "s2@x.edu,Course One,video,30,2024-03-01 10:00",       # duplicate in file
        "s2@x.edu,Course One,video,-4,2024-03-02 10:00",       # negative duration
        "ghost@x.edu,Course One,video,10,2024-03-03 10:00",    # unknown student
        "s3@x.edu,Course One,video,10,2024-03-03 10:00",       # not enrolled
        "s2@x.edu,Course Two,video,10,2024-03-03 10:00",       # other faculty's course
        "s2@x.edu,Course One,dance,10,2024-03-03 10:00",       # invalid type
        "s2@x.edu,Course One,video,10,2999-01-01 10:00",       # future
    ])
    html = _upload(faculty, "/activities/import", csv).get_data(as_text=True)
    assert "Imported" in html and "Rejected" in html
    with app.app_context():
        assert get_db().scalar("SELECT COUNT(*) FROM activities WHERE source='csv_import'") == 1
    # importing the same file again: everything is a duplicate
    html = _upload(faculty, "/activities/import", csv).get_data(as_text=True)
    with app.app_context():
        assert get_db().scalar("SELECT COUNT(*) FROM activities WHERE source='csv_import'") == 1
    assert "duplicate record" in html


def test_import_file_level_errors(faculty, data):
    assert "Only .csv" in _upload(faculty, "/activities/import", HEAD, "x.txt").get_data(as_text=True)
    assert "Missing required" in _upload(faculty, "/activities/import", "a,b\n1,2\n").get_data(as_text=True)
    assert "no data rows" in _upload(faculty, "/activities/import", HEAD).get_data(as_text=True)
    assert "empty" in _upload(faculty, "/activities/import", "").get_data(as_text=True)


def test_import_too_large(app, faculty, data):
    app.config["MAX_CONTENT_LENGTH"] = 100
    big = HEAD + "s2@x.edu,Course One,video,30,2024-03-01 10:00\n" * 10
    html = _upload(faculty, "/activities/import", big).get_data(as_text=True)
    assert "too large" in html or "larger than" in html


def test_import_assessments(app, faculty, data):
    csv = ("student_email,course_name,assessment_type,title,score,due_at,submitted_at,assessed_at\n"
           "s2@x.edu,Course One,quiz,Imported Quiz,66,,,2024-03-05 10:00\n"
           "s2@x.edu,Course One,quiz,Bad Score,150,,,2024-03-05 10:00\n"
           "s2@x.edu,Course One,quiz,Quiz 1,50,,,2024-03-05 10:00\n")  # duplicates seeded Quiz 1
    html = _upload(faculty, "/assessments/import", csv).get_data(as_text=True)
    assert "cannot exceed" in html and "duplicate assessment" in html
    with app.app_context():
        assert get_db().scalar("SELECT COUNT(*) FROM assessments WHERE title='Imported Quiz'") == 1


def test_import_forbidden_for_students_and_saved_name_is_safe(app, student, faculty, data, tmp_path):
    assert _upload(student, "/activities/import", HEAD + "x").status_code == 403
    _upload(faculty, "/activities/import", HEAD + "s2@x.edu,Course One,video,5,2024-04-01 10:00\n", "../../evil name.csv")
    saved = list((tmp_path / "uploads").iterdir())
    assert saved and all(".." not in p.name and "/" not in p.name for p in saved)
