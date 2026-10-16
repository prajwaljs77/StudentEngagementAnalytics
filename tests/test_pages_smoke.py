"""Every page renders (HTTP 200) for the roles that may see it."""
FACULTY_PAGES = ["/dashboard", "/courses", "/students", "/activities", "/assessments", "/predictions", "/alerts",
                 "/history", "/reports", "/reports/student_engagement"]
STUDENT_PAGES = ["/dashboard", "/courses", "/activities", "/assessments", "/predictions", "/history"]


def test_faculty_pages_render(faculty, data):
    for url in FACULTY_PAGES + [f"/courses/{data['c1']}", f"/students/{data['s1']}"]:
        r = faculty.get(url)
        assert r.status_code == 200, url
        assert "csrf-token" in r.get_data(as_text=True), url


def test_student_pages_render(student, data):
    for url in STUDENT_PAGES + [f"/courses/{data['c1']}", f"/students/{data['s1']}"]:
        assert student.get(url).status_code == 200, url
    html = student.get("/courses").get_data(as_text=True)
    assert "New course" not in html and "Course Two" not in html


def test_public_pages_render(client):
    assert client.get("/login").status_code == 200
    assert client.get("/register").status_code == 200
    assert client.get("/").status_code == 302
