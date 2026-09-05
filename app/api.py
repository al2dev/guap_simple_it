from datetime import date, timedelta

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import case, func

from .decorators import admin_required
from .extensions import db
from .models import CellTag, Comment, Event, Notification, ScheduleItem, Tag, User, iso_date, iso_time, utcnow
from .notifications import create_notifications, mark_read, mentioned_user_ids, notify_group, serialize_notification
from .realtime import queue_socket_event, user_room
from .services import parse_date, parse_time, unique_login, valid_color
from .schedule_import import cancel_or_delete_schedule


bp = Blueprint("api", __name__, url_prefix="/api")


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
    return {"id": item.id, "date": iso_date(item.date), "start_time": iso_time(item.start_time), "end_time": iso_time(item.end_time), "subject": item.subject, "teacher": item.teacher, "room": item.room, "address": item.address, "type": item.type, "description": item.description}


@bp.get("/calendar")
@login_required
def calendar():
    try:
        start = parse_date(request.args.get("start", date.today().isoformat()))
        days = min(max(int(request.args.get("days", 180)), 1), 366)
    except (ValueError, TypeError):
        return json_error("Некорректный диапазон дат")
    end = start + timedelta(days=days - 1)
    students = db.session.scalars(
        db.select(User)
        .where(User.group_name == current_user.group_name)
        .order_by(case((User.id == current_user.id, 0), else_=1), User.last_name, User.first_name)
    ).all()
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
    recipients.update(mentioned_user_ids(text, current_user.group_name, exclude_id=current_user.id))
    recipients.discard(current_user.id)
    create_notifications(
        recipients, actor=current_user, kind="calendar_mention",
        text=f"{current_user.full_name}: {text[:180]}",
        target_url=f"/?start={cell_date.isoformat()}&open_student={student_id}&open_date={cell_date.isoformat()}",
        comment_id=comment.id, student_id=student_id, date=cell_date,
    )
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
    db.session.execute(db.update(Notification).where(Notification.comment_id == comment.id).values(comment_id=None))
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
    status = request.args.get("status", "active")
    condition = Notification.is_read.is_(True) if status == "history" else Notification.is_read.is_(False)
    order = Notification.read_at.desc() if status == "history" else Notification.created_at.desc()
    items = db.session.scalars(db.select(Notification).where(Notification.user_id == current_user.id, condition).order_by(order, Notification.created_at.desc()).limit(100)).all()
    unread = db.session.scalar(db.select(func.count(Notification.id)).where(Notification.user_id == current_user.id, Notification.is_read.is_(False))) or 0
    response = jsonify(unread=unread, notifications=[serialize_notification(item) for item in items])
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.post("/notifications/<int:notification_id>/read")
@login_required
def read_notification(notification_id):
    item = db.session.get(Notification, notification_id)
    if not item or item.user_id != current_user.id:
        return json_error("Уведомление не найдено", 404)
    mark_read(item)
    queue_socket_event("notification:read", serialize_notification(item), user_room(current_user.id))
    db.session.commit()
    return jsonify(ok=True, target_url=item.resolved_target_url)


@bp.post("/notifications/read-all")
@login_required
def read_all_notifications():
    unread_ids = db.session.scalars(
        db.select(Notification.id).where(
            Notification.user_id == current_user.id, Notification.is_read.is_(False)
        )
    ).all()
    db.session.execute(db.update(Notification).where(Notification.user_id == current_user.id, Notification.is_read.is_(False)).values(is_read=True, read_at=utcnow()))
    queue_socket_event("notification:read_all", {"ids": unread_ids}, user_room(current_user.id))
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


def _admin_schedule_from_payload(item, data):
    subject = str(data.get("subject", "")).strip()
    if not subject or len(subject) > 160:
        raise ValueError("Укажите название предмета")
    item.date = parse_date(str(data.get("date", "")))
    item.start_time = parse_time(data.get("start_time"))
    if not item.start_time:
        raise ValueError("Укажите время начала")
    item.end_time = parse_time(data.get("end_time"))
    item.subject = subject
    item.teacher = str(data.get("teacher", "")).strip()[:160]
    item.room = str(data.get("room", "")).strip()[:80]
    item.address = str(data.get("address", "")).strip()[:160]
    item.type = str(data.get("type", "Занятие")).strip()[:40] or "Занятие"
    item.group_name = str(data.get("group_name", "")).strip()[:80] or None
    item.description = str(data.get("description", "")).strip()


def _import_text(row, key, label, max_length=80):
    value = str(row.get(key, "")).strip()
    if not value:
        raise ValueError(f"Не заполнено поле {label}")
    if len(value) > max_length:
        raise ValueError(f"Поле {label} длиннее {max_length} символов")
    return value


@bp.post("/admin/students/import")
@login_required
@admin_required
def api_import_students():
    """Create users from a JSON array while reporting errors per source row."""
    payload = request.get_json(silent=True)
    rows = payload.get("students") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return json_error("Ожидается JSON-массив студентов")
    if not rows:
        return json_error("Массив студентов пуст")
    if len(rows) > 500:
        return json_error("За один запрос можно импортировать не более 500 студентов")

    created, skipped, errors = [], [], []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append({"index": index, "error": "Запись должна быть JSON-объектом"})
            continue
        try:
            first_name = _import_text(row, "name", "name")
            last_name = _import_text(row, "surname", "surname")
            group_name = _import_text(row, "group", "group")
            password = str(row.get("pass", "")).strip()
            if len(password) < 5 or len(password) > 128:
                raise ValueError("Пароль должен содержать от 5 до 128 символов")
            role = str(row.get("role", "student")).strip().upper()
            if role not in {"STUDENT", "ADMIN"}:
                raise ValueError("role должен быть student или admin")

            existing = db.session.scalar(
                db.select(User).where(
                    func.lower(User.first_name) == first_name.lower(),
                    func.lower(User.last_name) == last_name.lower(),
                    func.lower(User.group_name) == group_name.lower(),
                )
            )
            if existing:
                skipped.append({"index": index, "id": existing.id, "login": existing.login, "reason": "Студент уже существует"})
                continue

            requested_login = str(row.get("login", "")).strip()
            if requested_login:
                if len(requested_login) > 80:
                    raise ValueError("login длиннее 80 символов")
                if db.session.scalar(db.select(User).where(func.lower(User.login) == requested_login.lower())):
                    raise ValueError(f"Логин {requested_login} уже занят")
                login = requested_login
            else:
                login = unique_login(last_name)

            user = User(login=login, first_name=first_name, last_name=last_name, group_name=group_name, role=role)
            user.set_password(password)
            db.session.add(user)
            db.session.flush()
            created.append({
                "index": index, "id": user.id, "login": user.login, "name": user.first_name,
                "surname": user.last_name, "group": user.group_name, "role": user.role.lower(),
            })
        except (TypeError, ValueError) as error:
            errors.append({"index": index, "error": str(error)})

    db.session.commit()
    return jsonify(created=created, skipped=skipped, errors=errors, totals={
        "received": len(rows), "created": len(created), "skipped": len(skipped), "errors": len(errors),
    })


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
    db.session.flush()
    notify_group(actor=current_user, group_name=event.group_name or current_user.group_name, kind="event_created", text=f"Добавлено событие «{event.title}»", target_url=f"/?focus={event.date.isoformat()}&open_day={event.date.isoformat()}")
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
    notify_group(actor=current_user, group_name=event.group_name or current_user.group_name, kind="event_updated", text=f"Обновлено событие «{event.title}»", target_url=f"/?focus={event.date.isoformat()}&open_day={event.date.isoformat()}")
    db.session.commit()
    return jsonify(serialize_event(event))


@bp.delete("/admin/events/<int:event_id>")
@login_required
@admin_required
def api_delete_event(event_id):
    event = db.session.get(Event, event_id)
    if not event:
        return json_error("Событие не найдено", 404)
    title, target_date, group_name = event.title, event.date, event.group_name or current_user.group_name
    db.session.delete(event)
    notify_group(actor=current_user, group_name=group_name, kind="event_deleted", text=f"Удалено событие «{title}»", target_url=f"/?focus={target_date.isoformat()}&open_day={target_date.isoformat()}")
    db.session.commit()
    return "", 204


@bp.post("/admin/schedule")
@login_required
@admin_required
def api_create_schedule():
    item = ScheduleItem()
    try:
        _admin_schedule_from_payload(item, request.get_json(silent=True) or {})
    except (ValueError, TypeError) as error:
        return json_error(str(error) or "Некорректные данные занятия")
    db.session.add(item)
    db.session.flush()
    notify_group(actor=current_user, group_name=item.group_name or current_user.group_name, kind="schedule_created", text=f"Добавлено занятие «{item.subject}»", target_url=f"/?focus={item.date.isoformat()}&open_day={item.date.isoformat()}")
    db.session.commit()
    return jsonify(serialize_schedule(item)), 201


@bp.delete("/admin/schedule/<int:item_id>")
@login_required
@admin_required
def api_delete_schedule(item_id):
    item = db.session.get(ScheduleItem, item_id)
    if not item:
        return json_error("Занятие не найдено", 404)
    subject, target_date, group_name = item.subject, item.date, item.group_name or current_user.group_name
    cancel_or_delete_schedule(item)
    notify_group(actor=current_user, group_name=group_name, kind="schedule_deleted", text=f"Удалено занятие «{subject}»", target_url=f"/?focus={target_date.isoformat()}&open_day={target_date.isoformat()}")
    db.session.commit()
    return "", 204
