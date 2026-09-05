from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.metrics import build_report
from app.models import PageView, User
from tests.conftest import login


def test_metrics_access_is_limited_to_named_admin(client, app):
    assert client.get("/admin/metrics").status_code == 302
    login(client, "Ivanov", "ИВ-23")
    assert client.get("/admin/metrics").status_code == 403
    client.post("/logout")
    with app.app_context():
        other = db.session.scalar(db.select(User).where(User.login == "Other"))
        other.role = "ADMIN"
        db.session.commit()
    login(client, "Other", "password")
    assert client.get("/admin/metrics?student=1").status_code == 403
    assert '/admin/metrics' not in client.get("/admin").get_data(as_text=True)
    client.post("/logout")
    login(client, "admin", "change-me")
    response = client.get("/admin/metrics")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "Нет посещений" in response.get_data(as_text=True)
    assert '/admin/metrics' in client.get("/admin").get_data(as_text=True)
    with app.app_context():
        admin = db.session.scalar(db.select(User).where(User.login == "admin"))
        admin.role = "STUDENT"
        db.session.commit()
    assert client.get("/admin/metrics").status_code == 403


def test_only_successful_page_gets_are_counted(client, app):
    client.get("/")
    client.get("/login")
    login(client, "Ivanov", "ИВ-23")
    for path in ["/", "/profile", "/chat", "/materials", "/notifications", "/"]:
        assert client.get(path).status_code == 200
    client.head("/")
    client.get("/api/calendar?days=1")
    client.get("/static/css/app.css")
    client.get("/uploads/avatars/missing.png")
    client.get("/materials/files/missing.pdf")
    client.get("/missing")
    client.get("/admin/metrics")
    client.post("/logout")
    with app.app_context():
        rows = db.session.scalars(db.select(PageView)).all()
        assert len(rows) == 6
        assert {row.user.login for row in rows} == {"Ivanov"}
    login(client, "admin", "change-me")
    client.get("/admin/metrics")
    client.get("/admin/metrics")
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(PageView.id))) == 6


def test_report_boundaries_unique_users_and_inactive_students(app, client):
    with app.app_context():
        users = {user.login: user.id for user in db.session.scalars(db.select(User))}
        for who, timestamp in [
            ("Ivanov", "2026-08-31T23:59:59"),
            ("Ivanov", "2026-09-01T00:00:00"),
            ("Ivanov", "2026-09-01T12:00:00"),
            ("Ivanov", "2026-09-03T23:59:59"),
            ("admin", "2026-09-01T12:00:00"),
            ("Ivanov", "2026-09-04T00:00:00"),
        ]:
            db.session.add(PageView(user_id=users[who], endpoint="main.dashboard",
                                    created_at=datetime.fromisoformat(timestamp).replace(tzinfo=timezone.utc)))
        db.session.commit()
        report = build_report(date(2026, 9, 1), date(2026, 9, 3))
        assert (report["summary"].views, report["summary"].users) == (4, 2)
        assert [(day["views"], day["users"]) for day in report["daily"]] == [(3, 2), (0, 0), (1, 1)]
        students = {row["User"].login: row for row in report["students"]}
        assert (students["Ivanov"]["views"], students["Ivanov"]["days"]) == (3, 2)
        assert students["Other"]["views"] == 0
        assert students["Other"]["last_seen"] is None
        filtered = build_report(date(2026, 9, 1), date(2026, 9, 3), users["Ivanov"])
        assert (filtered["summary"].views, filtered["summary"].users) == (3, 1)
        assert len(filtered["students"]) == 1
    login(client, "admin", "change-me")
    page = client.get(f'/admin/metrics?start=2026-09-01&end=2026-09-03&student={users["Ivanov"]}')
    assert page.status_code == 200
    assert "03.09.2026 23:59" in page.get_data(as_text=True)


@pytest.mark.parametrize("query", [
    "start=bad", "start=2026-09-03&end=2026-09-01",
    "start=2020-01-01&end=2026-01-01", "student=abc", "end=9999-12-31",
])
def test_invalid_metrics_filters(client, query):
    login(client, "admin", "change-me")
    assert client.get("/admin/metrics?" + query).status_code == 400


def test_unknown_or_admin_student_filter(client, app):
    login(client, "admin", "change-me")
    with app.app_context():
        admin_id = db.session.scalar(db.select(User.id).where(User.login == "admin"))
    assert client.get(f"/admin/metrics?student={admin_id}").status_code == 404
    assert client.get("/admin/metrics?student=999999").status_code == 404


def test_tracking_failure_does_not_break_page(client, monkeypatch):
    login(client, "Ivanov", "ИВ-23")
    def fail_commit(_session):
        raise SQLAlchemyError("analytics unavailable")
    monkeypatch.setattr("app.metrics.Session.commit", fail_commit)
    assert client.get("/").status_code == 200


def test_deleting_student_removes_page_views(client, app):
    login(client, "Ivanov", "ИВ-23")
    client.get("/")
    client.post("/logout")
    login(client, "admin", "change-me")
    with app.app_context():
        user_id = db.session.scalar(db.select(User.id).where(User.login == "Ivanov"))
    assert client.post(f"/admin/students/{user_id}/delete").status_code == 302
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(PageView.id))) == 0


def test_page_view_migration_upgrade_and_downgrade(app):
    from flask_migrate import downgrade, stamp, upgrade
    from sqlalchemy import inspect

    with app.app_context():
        PageView.__table__.drop(db.engine)
        stamp(revision="58ef019bc621")
        upgrade()
        inspector = inspect(db.engine)
        assert "page_view" in inspector.get_table_names()
        assert {index["name"] for index in inspector.get_indexes("page_view")} == {
            "ix_page_view_created_at", "ix_page_view_user_created",
        }
        assert db.session.scalar(db.select(db.func.count(User.id))) == 3
        downgrade(revision="58ef019bc621")
        assert "page_view" not in inspect(db.engine).get_table_names()
        upgrade()
        assert "page_view" in inspect(db.engine).get_table_names()
