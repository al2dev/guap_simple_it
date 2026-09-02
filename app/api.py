import re
from datetime import date, timedelta

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import func

from .decorators import admin_required
from .extensions import db
from .models import CellTag, Comment, Event, Notification, ScheduleItem, Tag, User, iso_date, iso_time
from .services import parse_date, parse_time, valid_color


bp = Blueprint("api", __name__, url_prefix="/api")
MENTION_RE = re.compile(r"@([A-Za-zА-Яа-яЁё0-9_.-]+)")


def json_error(message, status=400):
    return jsonify(error=message), status


def same_group_student(student_id):
    student = db.session.get(User, student_id)
    return student if student and student.group_name == current_user.group_name else None


def can_edit_cell(student):
    return current_user.is_admin or current_user.id == student.id


def serialize_event(event):
    return {"id": event.id, "title": event.title, "description": event.description, "date": iso_date(event.date), "start_time": iso_time(event.start_time), "end_time": iso_time(event.end_time), "type": event.type, "color": event.color, "location": event.location}


def serialize_schedule(item):
    return {"id": item.id, "date": iso_date(item.date), "start_time": iso_time(item.start_time), "end_time": iso_time(item.end_time), "subject": item.subject, "teacher": item.teacher, "room": item.room, "type": item.type, "description": item.description}


@bp.get("/calendar")
@login_required
def calendar():
    try:
        start = parse_date(request.args.get("start", date.today().isoformat()))
        days = min(max(int(request.args.get("days", 180)), 1), 366)
    except (ValueError, TypeError):
        return json_error("Некорректный диапазон дат")
    end = start + timedelta(days=days - 1)
    students = db.session.scalars(db.select(User).where(User.group_name == current_user.group_name).order_by(User.last_name)).all()
    tags = db.session.scalars(db.select(CellTag).join(User, CellTag.student_id == User.id).where(User.group_name == current_user.group_name, CellTag.date.between(start, end))).all()
    events = db.session.scalars(db.select(Event).where(Event.date.between(start, end), db.or_(Event.group_name == current_user.group_name, Event.group_name.is_(None)))).all()
    schedule = db.session.scalars(db.select(ScheduleItem).where(ScheduleItem.date.between(start, end), db.or_(ScheduleItem.group_name == current_user.group_name, ScheduleItem.group_name.is_(None)))).all()
    return jsonify(students=[{"id": s.id, "name": s.full_name, "group": s.group_name} for s in students], tags=[{"student_id": x.student_id, "date": iso_date(x.date), "name": x.tag.name, "color": x.tag.color} for x in tags], events=[serialize_event(x) for x in events], schedule=[serialize_schedule(x) for x in schedule])


@bp.get("/cell/<int:student_id>/<date_value>")
@login_required
def cell(student_id, date_value):
    student = same_group_student(student_id)
    if not student:
        return json_error("Студент не найден", 404)
    try:
        cell_date = parse_date(date_value)
    except ValueError:
        return json_error("Некорректная дата")
    cell_tags = db.session.scalars(db.select(CellTag).where(CellTag.student_id == student_id, CellTag.date == cell_date).order_by(CellTag.created_at)).all()
    comments = db.session.scalars(db.select(Comment).where(Comment.student_id == student_id, Comment.date == cell_date).order_by(Comment.created_at)).all()
    events = db.session.scalars(db.select(Event).where(Event.date == cell_date, db.or_(Event.group_name == current_user.group_name, Event.group_name.is_(None))).order_by(Event.start_time)).all()
    schedule = db.session.scalars(db.select(ScheduleItem).where(ScheduleItem.date == cell_date, db.or_(ScheduleItem.group_name == current_user.group_name, ScheduleItem.group_name.is_(None))).order_by(ScheduleItem.start_time)).all()
    available = db.session.scalars(db.select(Tag).where(db.or_(Tag.is_standard.is_(True), Tag.owner_id == current_user.id)).order_by(Tag.name)).all()
    return jsonify(
        student={"id": student.id, "name": student.full_name, "group": student.group_name},
        date=cell_date.isoformat(), can_edit=can_edit_cell(student),
        tags=[{"cell_tag_id": x.id, "id": x.tag.id, "name": x.tag.name, "color": x.tag.color, "description": x.tag.description, "can_delete": can_edit_cell(student)} for x in cell_tags],
        available_tags=[{"id": x.id, "name": x.name, "color": x.color} for x in available],
        events=[serialize_event(x) for x in events], schedule=[serialize_schedule(x) for x in schedule],
        comments=[{"id": x.id, "author": x.author.full_name, "author_id": x.author_id, "text": x.text, "created_at": x.created_at.isoformat(), "can_delete": current_user.is_admin or x.author_id == current_user.id} for x in comments],
    )


@bp.post("/cell/<int:student_id>/<date_value>/tag")
@login_required
def add_tag(student_id, date_value):
    student = same_group_student(student_id)
    if not student:
        return json_error("Студент не найден", 404)
    if not can_edit_cell(student):
        return json_error("Можно изменять только свои ячейки", 403)
    try:
        cell_date = parse_date(date_value)
    except ValueError:
        return json_error("Некорректная дата")
    data = request.get_json(silent=True) or {}
    tag = None
    if data.get("tag_id"):
        try:
            tag_id = int(data["tag_id"])
        except (TypeError, ValueError):
            return json_error("Некорректная метка")
        tag = db.session.get(Tag, tag_id)
        if not tag or not (tag.is_standard or tag.owner_id == current_user.id):
            return json_error("Метка недоступна", 403)
    else:
        name = str(data.get("name", "")).strip()
        if not name or len(name) > 80:
            return json_error("Укажите название метки")
        tag = Tag(name=name, color=valid_color(data.get("color")), description=str(data.get("description", ""))[:255], owner_id=current_user.id)
        db.session.add(tag)
        db.session.flush()
    exists = db.session.scalar(db.select(CellTag).where(CellTag.student_id == student_id, CellTag.date == cell_date, CellTag.tag_id == tag.id))
    if exists:
        return json_error("Эта метка уже добавлена")
    item = CellTag(student_id=student_id, date=cell_date, tag_id=tag.id, created_by_id=current_user.id)
    db.session.add(item)
    db.session.commit()
    return jsonify(id=item.id, name=tag.name, color=tag.color), 201


@bp.delete("/cell/<int:student_id>/<date_value>/tag/<int:cell_tag_id>")
@login_required
def delete_tag(student_id, date_value, cell_tag_id):
    student = same_group_student(student_id)
    item = db.session.get(CellTag, cell_tag_id)
    if not student or not item or item.student_id != student_id or item.date.isoformat() != date_value:
        return json_error("Метка не найдена", 404)
    if not can_edit_cell(student):
        return json_error("Можно изменять только свои ячейки", 403)
    db.session.delete(item)
    db.session.commit()
    return "", 204


@bp.post("/cell/<int:student_id>/<date_value>/comment")
@login_required
def add_comment(student_id, date_value):
    student = same_group_student(student_id)
    if not student:
        return json_error("Студент не найден", 404)
    try:
        cell_date = parse_date(date_value)
    except ValueError:
        return json_error("Некорректная дата")
    data = request.get_json(silent=True) or {}
    text = str(data.get("text", "")).strip()
    if not text or len(text) > 2000:
        return json_error("Комментарий должен содержать от 1 до 2000 символов")
    comment = Comment(student_id=student_id, date=cell_date, author_id=current_user.id, text=text)
    db.session.add(comment)
    db.session.flush()
    recipients = set()
    recipient_id = data.get("recipient_id")
    if recipient_id:
        try:
            recipient = same_group_student(int(recipient_id))
        except (TypeError, ValueError):
            recipient = None
        if recipient:
            recipients.add(recipient.id)
    mentions = {m.lower() for m in MENTION_RE.findall(text)}
    if mentions:
        matched = db.session.scalars(db.select(User).where(User.group_name == current_user.group_name, func.lower(User.login).in_(mentions))).all()
        recipients.update(user.id for user in matched)
    recipients.discard(current_user.id)
    for user_id in recipients:
        db.session.add(Notification(user_id=user_id, actor_id=current_user.id, comment_id=comment.id, student_id=student_id, date=cell_date, text=f"{current_user.full_name}: {text[:180]}"))
    db.session.commit()
    return jsonify(id=comment.id, author=current_user.full_name, text=text, created_at=comment.created_at.isoformat()), 201


@bp.delete("/comments/<int:comment_id>")
@login_required
def delete_comment(comment_id):
    comment = db.session.get(Comment, comment_id)
    if not comment:
        return json_error("Комментарий не найден", 404)
    if not (current_user.is_admin or comment.author_id == current_user.id):
        return json_error("Недостаточно прав", 403)
    db.session.delete(comment)
    db.session.commit()
    return "", 204


@bp.get("/schedule/<date_value>")
@login_required
def schedule(date_value):
    try:
        target = parse_date(date_value)
    except ValueError:
        return json_error("Некорректная дата")
    items = db.session.scalars(db.select(ScheduleItem).where(ScheduleItem.date == target, db.or_(ScheduleItem.group_name == current_user.group_name, ScheduleItem.group_name.is_(None))).order_by(ScheduleItem.start_time)).all()
    return jsonify(date=target.isoformat(), schedule=[serialize_schedule(x) for x in items])


@bp.get("/day/<date_value>")
@login_required
def day_details(date_value):
    try:
        target = parse_date(date_value)
    except ValueError:
        return json_error("Некорректная дата")
    events = db.session.scalars(db.select(Event).where(Event.date == target, db.or_(Event.group_name == current_user.group_name, Event.group_name.is_(None))).order_by(Event.start_time)).all()
    items = db.session.scalars(db.select(ScheduleItem).where(ScheduleItem.date == target, db.or_(ScheduleItem.group_name == current_user.group_name, ScheduleItem.group_name.is_(None))).order_by(ScheduleItem.start_time)).all()
    return jsonify(date=target.isoformat(), is_admin=current_user.is_admin, group_name=current_user.group_name, events=[serialize_event(x) for x in events], schedule=[serialize_schedule(x) for x in items])


@bp.get("/notifications")
@login_required
def notifications():
    items = db.session.scalars(db.select(Notification).where(Notification.user_id == current_user.id).order_by(Notification.created_at.desc()).limit(20)).all()
    unread = db.session.scalar(db.select(func.count(Notification.id)).where(Notification.user_id == current_user.id, Notification.is_read.is_(False))) or 0
    return jsonify(unread=unread, notifications=[{"id": x.id, "text": x.text, "date": iso_date(x.date), "student_id": x.student_id, "is_read": x.is_read, "created_at": x.created_at.isoformat()} for x in items])


@bp.post("/notifications/<int:notification_id>/read")
@login_required
def read_notification(notification_id):
    item = db.session.get(Notification, notification_id)
    if not item or item.user_id != current_user.id:
        return json_error("Уведомление не найдено", 404)
    item.is_read = True
    db.session.commit()
    return jsonify(ok=True, student_id=item.student_id, date=iso_date(item.date))


@bp.post("/notifications/read-all")
@login_required
def read_all_notifications():
    db.session.execute(db.update(Notification).where(Notification.user_id == current_user.id).values(is_read=True))
    db.session.commit()
    return jsonify(ok=True)


def _admin_event_from_payload(event, data):
    title = str(data.get("title", "")).strip()
    if not title or len(title) > 160:
        raise ValueError("Укажите название события")
    event.title = title
    event.date = parse_date(str(data.get("date", "")))
    event.start_time = parse_time(data.get("start_time"))
    event.end_time = parse_time(data.get("end_time"))
    event.type = str(data.get("type", "Другое"))[:40]
    event.color = valid_color(data.get("color"), "#ef4444")
    event.location = str(data.get("location", ""))[:120]
    event.group_name = str(data.get("group_name", "")).strip()[:80] or None
    event.description = str(data.get("description", ""))


@bp.post("/admin/events")
@login_required
@admin_required
def api_create_event():
    data = request.get_json(silent=True) or {}
    event = Event(created_by_id=current_user.id)
    try:
        _admin_event_from_payload(event, data)
    except (ValueError, TypeError):
        return json_error("Некорректные данные события")
    db.session.add(event)
    db.session.commit()
    return jsonify(serialize_event(event)), 201


@bp.put("/admin/events/<int:event_id>")
@login_required
@admin_required
def api_update_event(event_id):
    event = db.session.get(Event, event_id)
    if not event:
        return json_error("Событие не найдено", 404)
    try:
        _admin_event_from_payload(event, request.get_json(silent=True) or {})
    except (ValueError, TypeError):
        return json_error("Некорректные данные события")
    db.session.commit()
    return jsonify(serialize_event(event))


@bp.delete("/admin/events/<int:event_id>")
@login_required
@admin_required
def api_delete_event(event_id):
    event = db.session.get(Event, event_id)
    if not event:
        return json_error("Событие не найдено", 404)
    db.session.delete(event)
    db.session.commit()
    return "", 204
