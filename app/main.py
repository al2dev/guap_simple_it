import secrets
from datetime import date, timedelta
from pathlib import Path

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, send_from_directory, url_for
from flask_login import current_user, login_required
from PIL import Image, UnidentifiedImageError
from sqlalchemy import case
from sqlalchemy.orm import selectinload
from werkzeug.utils import secure_filename

from .extensions import db
from .forms import PasswordForm, ProfileForm
from .models import ChatMessage, ChatReply, Event, Material, MaterialComment, Notification, ScheduleItem, Subject, User
from .notifications import create_notifications, mentioned_user_ids, notify_group
from .realtime import group_room, queue_socket_event


bp = Blueprint("main", __name__)


@bp.get("/")
@login_required
def dashboard():
    try:
        focus = date.fromisoformat(request.args.get("focus") or request.args.get("start", ""))
    except ValueError:
        focus = date.today()
    view = request.args.get("view", "14")
    if view not in {"7", "14", "30"}:
        view = "14"
    days_count = 180
    start = focus - timedelta(days=30)
    days = [start + timedelta(days=i) for i in range(days_count)]
    students = db.session.scalars(
        db.select(User)
        .where(User.group_name == current_user.group_name)
        .order_by(case((User.id == current_user.id, 0), else_=1), User.last_name, User.first_name)
    ).all()
    events = db.session.scalars(db.select(Event).where(Event.date.between(days[0], days[-1]), db.or_(Event.group_name == current_user.group_name, Event.group_name.is_(None)))).all()
    schedule = db.session.scalars(db.select(ScheduleItem).where(ScheduleItem.date.between(days[0], days[-1]), db.or_(ScheduleItem.group_name == current_user.group_name, ScheduleItem.group_name.is_(None)))).all()
    events_by_date = {}
    schedule_by_date = {}
    for item in events:
        events_by_date.setdefault(item.date, []).append(item)
    for item in schedule:
        schedule_by_date.setdefault(item.date, []).append(item)
    return render_template("dashboard.html", students=students, days=days, events_by_date=events_by_date, schedule_by_date=schedule_by_date, view=view, today=date.today(), focus=focus)


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    profile_form = ProfileForm(prefix="profile", obj=current_user)
    password_form = PasswordForm(prefix="password")
    if profile_form.submit.data and profile_form.validate_on_submit():
        current_user.first_name = profile_form.first_name.data.strip()
        current_user.last_name = profile_form.last_name.data.strip()
        if profile_form.avatar.data:
            try:
                profile_form.avatar.data.stream.seek(0, 2)
                if profile_form.avatar.data.stream.tell() > current_app.config["MAX_AVATAR_SIZE"]:
                    raise ValueError("Аватар должен быть не больше 3 МБ")
                profile_form.avatar.data.stream.seek(0)
                with Image.open(profile_form.avatar.data.stream) as image:
                    image.verify()
                profile_form.avatar.data.stream.seek(0)
                ext = secure_filename(profile_form.avatar.data.filename).rsplit(".", 1)[-1].lower()
                filename = f"{current_user.id}-{secrets.token_hex(8)}.{ext}"
                profile_form.avatar.data.save(Path(current_app.config["UPLOAD_FOLDER"]) / filename)
                current_user.avatar = filename
            except (UnidentifiedImageError, OSError, ValueError) as error:
                flash(str(error) if isinstance(error, ValueError) else "Файл не является корректным изображением", "danger")
                return render_template("profile.html", profile_form=profile_form, password_form=password_form)
        db.session.commit()
        flash("Профиль обновлён", "success")
        return redirect(url_for("main.profile"))
    if password_form.submit_password.data and password_form.validate_on_submit():
        if not current_user.check_password(password_form.current_password.data):
            flash("Текущий пароль указан неверно", "danger")
        else:
            current_user.set_password(password_form.new_password.data)
            db.session.commit()
            flash("Пароль изменён", "success")
            return redirect(url_for("main.profile"))
    return render_template("profile.html", profile_form=profile_form, password_form=password_form)


@bp.get("/notifications")
@login_required
def notifications():
    items = db.session.scalars(db.select(Notification).where(Notification.user_id == current_user.id).order_by(Notification.created_at.desc())).all()
    return render_template("notifications.html", notifications=items)


@bp.get("/chat")
@login_required
def chat():
    messages = list(reversed(db.session.scalars(
        db.select(ChatMessage)
        .where(ChatMessage.group_name == current_user.group_name)
        .options(
            selectinload(ChatMessage.author),
            selectinload(ChatMessage.replies).selectinload(ChatReply.author),
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(100)
    ).unique().all()))
    return render_template("chat.html", messages=messages)


def _serialize_chat_message(message):
    return {
        "id": message.id,
        "author_id": message.author_id,
        "author": message.author.full_name,
        "initials": message.author.initials,
        "text": message.text,
        "created_at": message.created_at.isoformat(),
        "mine": message.author_id == current_user.id,
        "can_delete": current_user.is_admin or message.author_id == current_user.id,
        "reply_count": len(message.replies),
    }


@bp.get("/chat/messages/<int:message_id>/thread")
@login_required
def chat_thread(message_id):
    message = db.session.get(ChatMessage, message_id)
    if not message or message.group_name != current_user.group_name:
        abort(404)
    return jsonify(
        message={
            "id": message.id, "author": message.author.full_name,
            "initials": message.author.initials, "text": message.text,
            "created_at": message.created_at.isoformat(),
        },
        replies=[{
            "id": reply.id, "author": reply.author.full_name,
            "initials": reply.author.initials, "text": reply.text,
            "created_at": reply.created_at.isoformat(),
            "can_delete": current_user.is_admin or reply.author_id == current_user.id,
        } for reply in message.replies],
    )


@bp.post("/chat/messages")
@login_required
def add_chat_message():
    text = request.form.get("text", "").strip()
    if not text or len(text) > 4000:
        if request.accept_mimetypes.best == "application/json":
            return jsonify(error="Сообщение должно содержать от 1 до 4000 символов"), 400
        flash("Сообщение должно содержать от 1 до 4000 символов", "danger")
        return redirect(url_for("main.chat"))
    message = ChatMessage(group_name=current_user.group_name, author_id=current_user.id, text=text)
    db.session.add(message)
    db.session.flush()
    queue_socket_event(
        "chat:message_created", _serialize_chat_message(message),
        group_room(current_user.group_name),
    )
    create_notifications(
        mentioned_user_ids(text, current_user.group_name, exclude_id=current_user.id),
        actor=current_user, kind="chat_mention",
        text=f"{current_user.full_name} упоминает вас в общем чате",
        target_url=f"/chat#message-{message.id}",
    )
    db.session.commit()
    if request.accept_mimetypes.best == "application/json":
        return jsonify(message=_serialize_chat_message(message)), 201
    return redirect(url_for("main.chat", _anchor=f"message-{message.id}"))


@bp.post("/chat/messages/<int:message_id>/replies")
@login_required
def add_chat_reply(message_id):
    message = db.session.get(ChatMessage, message_id)
    if not message or message.group_name != current_user.group_name:
        abort(404)
    text = request.form.get("text", "").strip()
    if not text or len(text) > 2000:
        if request.accept_mimetypes.best == "application/json":
            return jsonify(error="Комментарий должен содержать от 1 до 2000 символов"), 400
        flash("Комментарий должен содержать от 1 до 2000 символов", "danger")
        return redirect(url_for("main.chat", _anchor=f"message-{message.id}"))
    reply = ChatReply(message_id=message.id, author_id=current_user.id, text=text)
    db.session.add(reply)
    db.session.flush()
    recipients = mentioned_user_ids(text, current_user.group_name, exclude_id=current_user.id)
    recipients.add(message.author_id)
    create_notifications(
        recipients, actor=current_user, kind="chat_reply",
        text=f"{current_user.full_name} ответил(а) на сообщение в общем чате",
        target_url=f"/chat?thread={message.id}#message-{message.id}",
    )
    reply_count = db.session.scalar(
        db.select(db.func.count(ChatReply.id)).where(ChatReply.message_id == message.id)
    ) or 0
    reply_payload = {
        "id": reply.id, "author_id": reply.author_id,
        "author": current_user.full_name, "initials": current_user.initials,
        "text": reply.text, "created_at": reply.created_at.isoformat(),
        "can_delete": True,
    }
    queue_socket_event(
        "chat:reply_created",
        {"message_id": message.id, "reply": reply_payload, "reply_count": reply_count},
        group_room(current_user.group_name),
    )
    db.session.commit()
    if request.accept_mimetypes.best == "application/json":
        return jsonify(
            id=reply.id, author_id=current_user.id,
            author=current_user.full_name, initials=current_user.initials,
            text=reply.text, created_at=reply.created_at.isoformat(),
            can_delete=True, reply_count=reply_count,
        ), 201
    return redirect(url_for("main.chat", _anchor=f"message-{message.id}"))


@bp.post("/chat/messages/<int:message_id>/delete")
@login_required
def delete_chat_message(message_id):
    message = db.session.get(ChatMessage, message_id)
    if not message or message.group_name != current_user.group_name:
        abort(404)
    if not (current_user.is_admin or message.author_id == current_user.id):
        abort(403)
    message_group = message.group_name
    db.session.delete(message)
    queue_socket_event(
        "chat:message_deleted", {"message_id": message.id}, group_room(message_group)
    )
    db.session.commit()
    flash("Сообщение удалено", "success")
    return redirect(url_for("main.chat"))


@bp.post("/chat/replies/<int:reply_id>/delete")
@login_required
def delete_chat_reply(reply_id):
    reply = db.session.get(ChatReply, reply_id)
    if not reply or reply.message.group_name != current_user.group_name:
        abort(404)
    if not (current_user.is_admin or reply.author_id == current_user.id):
        abort(403)
    message_id = reply.message_id
    db.session.delete(reply)
    db.session.flush()
    reply_count = db.session.scalar(db.select(db.func.count(ChatReply.id)).where(ChatReply.message_id == message_id)) or 0
    queue_socket_event(
        "chat:reply_deleted",
        {"message_id": message_id, "reply_id": reply.id, "reply_count": reply_count},
        group_room(reply.message.group_name),
    )
    db.session.commit()
    if request.accept_mimetypes.best == "application/json":
        return jsonify(ok=True, message_id=message_id, reply_count=reply_count)
    return redirect(url_for("main.chat", _anchor=f"message-{message_id}"))


@bp.get("/uploads/avatars/<path:filename>")
def avatar(filename):
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename)


ALLOWED_MATERIAL_EXTENSIONS = {"pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "txt", "zip", "png", "jpg", "jpeg", "webp"}


def _uploaded_filename(filename):
    """Return a display-safe basename without dropping Unicode characters."""
    basename = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    return "".join(char for char in basename if ord(char) >= 32)[:255]


def _subject_for_group(subject_id):
    subject = db.session.get(Subject, subject_id)
    return subject if subject and subject.group_name == current_user.group_name else None


@bp.get("/materials")
@login_required
def materials():
    subjects = db.session.scalars(db.select(Subject).where(Subject.group_name == current_user.group_name).order_by(Subject.name)).unique().all()
    selected_id = request.args.get("subject", type=int)
    selected = next((item for item in subjects if item.id == selected_id), None) or (subjects[0] if subjects else None)
    return render_template("materials.html", subjects=subjects, selected=selected)


@bp.post("/materials/subjects")
@login_required
def add_subject():
    name = request.form.get("name", "").strip()
    if not name or len(name) > 160:
        flash("Укажите название предмета", "danger")
    else:
        subject = Subject(name=name, description=request.form.get("description", "").strip(), group_name=current_user.group_name, created_by_id=current_user.id)
        db.session.add(subject)
        db.session.flush()
        notify_group(actor=current_user, group_name=current_user.group_name, kind="subject_created", text=f"Добавлен предмет «{subject.name}»", target_url=f"/materials?subject={subject.id}")
        db.session.commit()
        flash("Предмет добавлен", "success")
    return redirect(url_for("main.materials"))


@bp.post("/materials/subjects/<int:subject_id>/delete")
@login_required
def delete_subject(subject_id):
    subject = _subject_for_group(subject_id)
    if not subject:
        abort(404)
    if not current_user.is_admin:
        abort(403)
    name = subject.name
    db.session.delete(subject)
    notify_group(actor=current_user, group_name=current_user.group_name, kind="subject_deleted", text=f"Удалён предмет «{name}»", target_url="/materials")
    db.session.commit()
    flash("Предмет и его материалы удалены", "success")
    return redirect(url_for("main.materials"))


@bp.post("/materials/subjects/<int:subject_id>/items")
@login_required
def add_material(subject_id):
    subject = _subject_for_group(subject_id)
    if not subject:
        abort(404)
    title = request.form.get("title", "").strip()
    link_url = request.form.get("link_url", "").strip()
    uploaded = request.files.get("file")
    if not title or len(title) > 180:
        flash("Укажите название материала", "danger")
        return redirect(url_for("main.materials", subject=subject.id))
    if link_url and not link_url.lower().startswith(("https://", "http://")):
        flash("Ссылка должна начинаться с http:// или https://", "danger")
        return redirect(url_for("main.materials", subject=subject.id))
    item = Material(subject_id=subject.id, title=title, description=request.form.get("description", "").strip(), link_url=link_url[:1000], created_by_id=current_user.id)
    if uploaded and uploaded.filename:
        original_name = _uploaded_filename(uploaded.filename)
        extension = original_name.rsplit(".", 1)[-1].strip().lower() if "." in original_name else ""
        uploaded.stream.seek(0, 2)
        size = uploaded.stream.tell()
        uploaded.stream.seek(0)
        if extension not in ALLOWED_MATERIAL_EXTENSIONS:
            flash("Недопустимый тип файла", "danger")
            return redirect(url_for("main.materials", subject=subject.id))
        if size > current_app.config["MAX_MATERIAL_SIZE"]:
            limit_mb = current_app.config["MAX_MATERIAL_SIZE"] // (1024 * 1024)
            flash(f"Файл должен быть не больше {limit_mb} МБ", "danger")
            return redirect(url_for("main.materials", subject=subject.id))
        stored = f"{current_user.id}-{secrets.token_hex(12)}.{extension}"
        uploaded.save(Path(current_app.config["MATERIAL_UPLOAD_FOLDER"]) / stored)
        item.stored_filename, item.original_filename, item.file_size = stored, original_name, size
    if not item.link_url and not item.stored_filename and not item.description:
        flash("Добавьте файл, ссылку или описание", "danger")
        return redirect(url_for("main.materials", subject=subject.id))
    db.session.add(item)
    db.session.flush()
    notify_group(actor=current_user, group_name=current_user.group_name, kind="material_created", text=f"Добавлен материал «{item.title}» по предмету «{subject.name}»", target_url=f"/materials?subject={subject.id}&material={item.id}#material-{item.id}")
    db.session.commit()
    flash("Материал опубликован", "success")
    return redirect(url_for("main.materials", subject=subject.id))


@bp.post("/materials/items/<int:item_id>/delete")
@login_required
def delete_material(item_id):
    item = db.session.get(Material, item_id)
    if not item or item.subject.group_name != current_user.group_name:
        abort(404)
    if not (current_user.is_admin or item.created_by_id == current_user.id):
        abort(403)
    stored, subject_id, title = item.stored_filename, item.subject_id, item.title
    db.session.delete(item)
    notify_group(actor=current_user, group_name=current_user.group_name, kind="material_deleted", text=f"Удалён материал «{title}»", target_url=f"/materials?subject={subject_id}")
    db.session.commit()
    if stored:
        (Path(current_app.config["MATERIAL_UPLOAD_FOLDER"]) / stored).unlink(missing_ok=True)
    flash("Материал удалён", "success")
    return redirect(url_for("main.materials", subject=subject_id))


@bp.post("/materials/items/<int:item_id>/comments")
@login_required
def add_material_comment(item_id):
    item = db.session.get(Material, item_id)
    if not item or item.subject.group_name != current_user.group_name:
        abort(404)
    text = request.form.get("text", "").strip()
    if not text or len(text) > 2000:
        flash("Комментарий должен содержать от 1 до 2000 символов", "danger")
    else:
        db.session.add(MaterialComment(material_id=item.id, author_id=current_user.id, text=text))
        create_notifications(
            mentioned_user_ids(text, current_user.group_name, exclude_id=current_user.id),
            actor=current_user, kind="material_mention",
            text=f"{current_user.full_name} упоминает вас в комментарии к «{item.title}»",
            target_url=f"/materials?subject={item.subject_id}&material={item.id}#material-{item.id}",
        )
        db.session.commit()
        flash("Комментарий добавлен", "success")
    return redirect(url_for("main.materials", subject=item.subject_id))


@bp.post("/materials/comments/<int:comment_id>/delete")
@login_required
def delete_material_comment(comment_id):
    comment = db.session.get(MaterialComment, comment_id)
    if not comment or comment.material.subject.group_name != current_user.group_name:
        abort(404)
    if not (current_user.is_admin or comment.author_id == current_user.id):
        abort(403)
    subject_id = comment.material.subject_id
    db.session.delete(comment)
    db.session.commit()
    flash("Комментарий удалён", "success")
    return redirect(url_for("main.materials", subject=subject_id))


@bp.get("/materials/files/<path:filename>")
@login_required
def material_file(filename):
    item = db.session.scalar(db.select(Material).join(Subject).where(Material.stored_filename == filename, Subject.group_name == current_user.group_name))
    if not item:
        abort(404)
    return send_from_directory(current_app.config["MATERIAL_UPLOAD_FOLDER"], filename, as_attachment=True, download_name=item.original_filename)
