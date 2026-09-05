from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .decorators import admin_required
from .extensions import db
from .forms import EventForm, ScheduleForm, StudentForm, TagForm
from .models import Event, Notification, ScheduleItem, Tag, User
from .notifications import notify_group
from .services import unique_login, valid_color
from .schedule_import import cancel_or_delete_schedule
from .metrics import metrics


bp = Blueprint("admin", __name__, url_prefix="/admin")
bp.add_url_rule("/metrics", view_func=metrics)


@bp.get("")
@login_required
@admin_required
def dashboard():
    stats = {
        "students": db.session.scalar(db.select(db.func.count(User.id)).where(User.role == "STUDENT")) or 0,
        "events": db.session.scalar(db.select(db.func.count(Event.id))) or 0,
        "exams": db.session.scalar(db.select(db.func.count(Event.id)).where(Event.type == "Экзамен", Event.date >= date.today())) or 0,
        "unread": db.session.scalar(db.select(db.func.count(Notification.id)).where(Notification.is_read.is_(False))) or 0,
    }
    upcoming = db.session.scalars(db.select(Event).where(Event.date >= date.today()).order_by(Event.date, Event.start_time).limit(5)).all()
    return render_template("admin/dashboard.html", stats=stats, upcoming=upcoming)


@bp.route("/students", methods=["GET", "POST"])
@login_required
@admin_required
def students():
    form = StudentForm()
    if form.validate_on_submit():
        password = form.password.data or form.group_name.data
        user = User(login=unique_login(form.last_name.data), first_name=form.first_name.data.strip(), last_name=form.last_name.data.strip(), group_name=form.group_name.data.strip(), role=form.role.data)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash(f"Пользователь {user.full_name} добавлен. Логин: {user.login}", "success")
        return redirect(url_for("admin.students"))
    users = db.session.scalars(db.select(User).order_by(User.last_name, User.first_name)).all()
    return render_template("admin/students.html", users=users, form=form)


@bp.route("/students/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_student(user_id):
    user = db.get_or_404(User, user_id)
    form = StudentForm(obj=user)
    if form.validate_on_submit():
        user.first_name = form.first_name.data.strip()
        user.last_name = form.last_name.data.strip()
        user.group_name = form.group_name.data.strip()
        user.role = form.role.data
        if form.password.data:
            user.set_password(form.password.data)
        db.session.commit()
        flash("Пользователь обновлён. Логин остался прежним.", "success")
        return redirect(url_for("admin.students"))
    return render_template("admin/edit.html", title="Редактировать пользователя", form=form, item=user)


@bp.post("/students/<int:user_id>/delete")
@login_required
@admin_required
def delete_student(user_id):
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        flash("Нельзя удалить свой аккаунт", "danger")
    else:
        db.session.delete(user)
        db.session.commit()
        flash("Пользователь удалён", "success")
    return redirect(url_for("admin.students"))


@bp.post("/students/<int:user_id>/reset-password")
@login_required
@admin_required
def reset_password(user_id):
    user = db.get_or_404(User, user_id)
    user.set_password(user.group_name)
    db.session.commit()
    flash(f"Пароль {user.login} сброшен до названия группы: {user.group_name}", "success")
    return redirect(url_for("admin.students"))


@bp.route("/events", methods=["GET", "POST"])
@login_required
@admin_required
def events():
    form = EventForm()
    form.color.data = form.color.data or "#ef4444"
    if form.validate_on_submit():
        item = Event(created_by_id=current_user.id)
        _fill_event(item, form)
        db.session.add(item)
        db.session.flush()
        notify_group(actor=current_user, group_name=item.group_name or current_user.group_name, kind="event_created", text=f"Добавлено событие «{item.title}»", target_url=f"/?focus={item.date.isoformat()}&open_day={item.date.isoformat()}")
        db.session.commit()
        flash("Событие добавлено", "success")
        return redirect(url_for("admin.events"))
    items = db.session.scalars(db.select(Event).order_by(Event.date.desc(), Event.start_time)).all()
    return render_template("admin/events.html", items=items, form=form)


def _fill_event(item, form):
    item.title = form.title.data.strip()
    item.date = form.date.data
    item.start_time = form.start_time.data
    item.end_time = form.end_time.data
    item.type = form.type.data
    item.color = valid_color(form.color.data, "#ef4444")
    item.location = (form.location.data or "").strip()
    item.group_name = (form.group_name.data or "").strip() or None
    item.description = (form.description.data or "").strip()


@bp.route("/events/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_event(item_id):
    item = db.get_or_404(Event, item_id)
    form = EventForm(obj=item)
    if form.validate_on_submit():
        _fill_event(item, form)
        notify_group(actor=current_user, group_name=item.group_name or current_user.group_name, kind="event_updated", text=f"Обновлено событие «{item.title}»", target_url=f"/?focus={item.date.isoformat()}&open_day={item.date.isoformat()}")
        db.session.commit()
        flash("Событие обновлено", "success")
        return redirect(url_for("admin.events"))
    return render_template("admin/edit.html", title="Редактировать событие", form=form, item=item)


@bp.post("/events/<int:item_id>/delete")
@login_required
@admin_required
def delete_event(item_id):
    item = db.get_or_404(Event, item_id)
    title, target_date, group_name = item.title, item.date, item.group_name or current_user.group_name
    db.session.delete(item)
    notify_group(actor=current_user, group_name=group_name, kind="event_deleted", text=f"Удалено событие «{title}»", target_url=f"/?focus={target_date.isoformat()}&open_day={target_date.isoformat()}")
    db.session.commit()
    flash("Событие удалено", "success")
    return redirect(url_for("admin.events"))


@bp.route("/schedule", methods=["GET", "POST"])
@login_required
@admin_required
def schedule():
    form = ScheduleForm()
    if form.validate_on_submit():
        item = ScheduleItem()
        _fill_schedule(item, form)
        item.group_name = current_user.group_name
        db.session.add(item)
        db.session.flush()
        notify_group(actor=current_user, group_name=item.group_name or current_user.group_name, kind="schedule_created", text=f"Добавлено занятие «{item.subject}»", target_url=f"/?focus={item.date.isoformat()}&open_day={item.date.isoformat()}")
        db.session.commit()
        flash("Занятие добавлено", "success")
        return redirect(url_for("admin.schedule"))
    elif request.method == "GET":
        form.group_name.data = current_user.group_name
    items = db.session.scalars(db.select(ScheduleItem).where(db.or_(ScheduleItem.group_name == current_user.group_name, ScheduleItem.group_name.is_(None))).order_by(ScheduleItem.date.desc(), ScheduleItem.start_time)).all()
    return render_template("admin/schedule.html", items=items, form=form)


def _fill_schedule(item, form):
    item.date = form.date.data
    item.start_time = form.start_time.data
    item.end_time = form.end_time.data
    item.subject = form.subject.data.strip()
    item.teacher = (form.teacher.data or "").strip()
    item.room = (form.room.data or "").strip()
    item.address = (form.address.data or "").strip()
    item.type = form.type.data
    item.group_name = (form.group_name.data or "").strip() or None
    item.description = (form.description.data or "").strip()


@bp.route("/schedule/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_schedule(item_id):
    item = db.get_or_404(ScheduleItem, item_id)
    form = ScheduleForm(obj=item)
    if form.validate_on_submit():
        _fill_schedule(item, form)
        notify_group(actor=current_user, group_name=item.group_name or current_user.group_name, kind="schedule_updated", text=f"Обновлено занятие «{item.subject}»", target_url=f"/?focus={item.date.isoformat()}&open_day={item.date.isoformat()}")
        db.session.commit()
        flash("Занятие обновлено", "success")
        return redirect(url_for("admin.schedule"))
    return render_template("admin/edit.html", title="Редактировать занятие", form=form, item=item)


@bp.post("/schedule/<int:item_id>/delete")
@login_required
@admin_required
def delete_schedule(item_id):
    item = db.get_or_404(ScheduleItem, item_id)
    subject, target_date, group_name = item.subject, item.date, item.group_name or current_user.group_name
    cancel_or_delete_schedule(item)
    notify_group(actor=current_user, group_name=group_name, kind="schedule_deleted", text=f"Удалено занятие «{subject}»", target_url=f"/?focus={target_date.isoformat()}&open_day={target_date.isoformat()}")
    db.session.commit()
    flash("Занятие удалено", "success")
    return redirect(url_for("admin.schedule"))


@bp.route("/tags", methods=["GET", "POST"])
@login_required
@admin_required
def tags():
    form = TagForm()
    form.color.data = form.color.data or "#6366f1"
    if form.validate_on_submit():
        db.session.add(Tag(name=form.name.data.strip(), color=valid_color(form.color.data), description=(form.description.data or "").strip(), is_standard=True, owner_id=current_user.id))
        db.session.commit()
        flash("Стандартная метка добавлена", "success")
        return redirect(url_for("admin.tags"))
    items = db.session.scalars(db.select(Tag).where(Tag.is_standard.is_(True)).order_by(Tag.name)).all()
    return render_template("admin/tags.html", items=items, form=form)


@bp.route("/tags/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_tag(item_id):
    item = db.get_or_404(Tag, item_id)
    form = TagForm(obj=item)
    if form.validate_on_submit():
        item.name = form.name.data.strip()
        item.color = valid_color(form.color.data)
        item.description = (form.description.data or "").strip()
        db.session.commit()
        flash("Метка обновлена", "success")
        return redirect(url_for("admin.tags"))
    return render_template("admin/edit.html", title="Редактировать метку", form=form, item=item)


@bp.post("/tags/<int:item_id>/delete")
@login_required
@admin_required
def delete_tag(item_id):
    item = db.get_or_404(Tag, item_id)
    if not item.is_standard:
        flash("Это не стандартная метка", "danger")
    else:
        db.session.delete(item)
        db.session.commit()
        flash("Метка удалена", "success")
    return redirect(url_for("admin.tags"))
