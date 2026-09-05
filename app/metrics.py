"""Authenticated page views; background traffic is deliberately excluded."""
from datetime import date, datetime, time, timedelta, timezone

from flask import abort, current_app, render_template, request
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .extensions import db
from .models import PageView, User


TRACKED_PAGES = {
    "main.dashboard", "main.profile", "main.notifications", "main.chat", "main.materials",
    "admin.dashboard", "admin.students", "admin.edit_student", "admin.events",
    "admin.edit_event", "admin.schedule", "admin.edit_schedule", "admin.tags", "admin.edit_tag",
}


def record_page_view(response):
    if (request.method == "GET" and response.status_code == 200
            and response.mimetype == "text/html" and request.endpoint in TRACKED_PAGES
            and current_user.is_authenticated):
        # A separate transaction keeps analytics failures out of application writes.
        try:
            with Session(db.engine) as session:
                session.add(PageView(user_id=current_user.id, endpoint=request.endpoint))
                session.commit()
        except SQLAlchemyError:
            current_app.logger.exception("Could not record page view")
    return response


def build_report(start, end, student_id=None):
    conditions = [
        PageView.created_at >= datetime.combine(start, time.min, timezone.utc),
        PageView.created_at < datetime.combine(end + timedelta(days=1), time.min, timezone.utc),
    ]
    if student_id is not None:
        conditions.append(PageView.user_id == student_id)
    # PostgreSQL casts timestamptz using the connection timezone unless made explicit.
    timestamp = PageView.created_at
    if db.engine.dialect.name == "postgresql":
        timestamp = db.func.timezone("UTC", timestamp)
    day = db.func.date(timestamp)
    summary = db.session.execute(db.select(
        db.func.count(PageView.id).label("views"),
        db.func.count(db.distinct(PageView.user_id)).label("users"),
    ).where(*conditions)).one()
    daily_rows = db.session.execute(db.select(
        day.label("day"), db.func.count(PageView.id).label("views"),
        db.func.count(db.distinct(PageView.user_id)).label("users"),
    ).where(*conditions).group_by(day)).all()
    daily_map = {str(row.day): row for row in daily_rows}
    daily = []
    for offset in range((end - start).days + 1):
        value = start + timedelta(days=offset)
        row = daily_map.get(value.isoformat())
        daily.append({"date": value, "views": row.views if row else 0, "users": row.users if row else 0})
    totals = db.select(
        PageView.user_id, db.func.count(PageView.id).label("views"),
        db.func.count(db.distinct(day)).label("days"),
        db.func.min(PageView.created_at).label("first_seen"),
        db.func.max(PageView.created_at).label("last_seen"),
    ).where(*conditions).group_by(PageView.user_id).subquery()
    students_query = db.select(
        User, db.func.coalesce(totals.c.views, 0).label("views"),
        db.func.coalesce(totals.c.days, 0).label("days"),
        totals.c.first_seen, totals.c.last_seen,
    ).outerjoin(totals, User.id == totals.c.user_id).where(User.role == "STUDENT")
    if student_id is not None:
        students_query = students_query.where(User.id == student_id)
    students = db.session.execute(students_query.order_by(User.last_name, User.first_name, User.id)).all()
    # SQLite returns naive UTC, PostgreSQL may return another connection timezone.
    students = [{
        "User": row.User, "views": row.views, "days": row.days,
        "first_seen": _as_utc(row.first_seen), "last_seen": _as_utc(row.last_seen),
    } for row in students]
    return {"summary": summary, "daily": daily, "students": students}


def _as_utc(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@login_required
def metrics():
    if not current_user.can_view_metrics:
        abort(403)
    today = datetime.now(timezone.utc).date()
    try:
        start = date.fromisoformat(request.args.get("start", (today - timedelta(days=29)).isoformat()))
        end = date.fromisoformat(request.args.get("end", today.isoformat()))
        if start > end or (end - start).days >= 366 or end == date.max:
            raise ValueError
        raw_student = request.args.get("student", "")
        student_id = int(raw_student) if raw_student else None
    except ValueError:
        abort(400, description="Укажите корректный период до 366 дней и студента.")
    if student_id is not None:
        student = db.session.get(User, student_id)
        if student is None or student.role != "STUDENT":
            abort(404)
    choices = db.session.scalars(db.select(User).where(User.role == "STUDENT").order_by(User.last_name, User.first_name)).all()
    response = current_app.make_response(render_template(
        "admin/metrics.html", start=start, end=end, student_id=student_id,
        choices=choices, **build_report(start, end, student_id),
    ))
    response.headers["Cache-Control"] = "private, no-store"
    return response
