import re

from sqlalchemy import func

from .extensions import db
from .models import Notification, User, utcnow
from .realtime import queue_socket_event, user_room


MENTION_RE = re.compile(r"@([A-Za-zА-Яа-яЁё0-9_.-]+)")


def group_user_ids(group_name, *, exclude_id=None):
    ids = set(db.session.scalars(db.select(User.id).where(User.group_name == group_name)).all())
    ids.discard(exclude_id)
    return ids


def mentioned_user_ids(text, group_name, *, exclude_id=None):
    mentions = {value.lower() for value in MENTION_RE.findall(text or "")}
    if "all" in mentions:
        return group_user_ids(group_name, exclude_id=exclude_id)
    if not mentions:
        return set()
    ids = set(db.session.scalars(db.select(User.id).where(
        User.group_name == group_name,
        func.lower(User.login).in_(mentions),
    )).all())
    ids.discard(exclude_id)
    return ids


def create_notifications(user_ids, *, actor, kind, text, target_url, comment_id=None, student_id=None, date=None):
    created = []
    for user_id in set(user_ids) - {actor.id}:
        notification = Notification(
            user_id=user_id,
            actor_id=actor.id,
            comment_id=comment_id,
            student_id=student_id,
            date=date,
            kind=kind,
            text=text[:255],
            target_url=target_url[:1000],
        )
        db.session.add(notification)
        created.append(notification)
    if created:
        db.session.flush()
        for notification in created:
            queue_socket_event("notification:new", serialize_notification(notification), user_room(notification.user_id))
    return created


def notify_group(*, actor, group_name, kind, text, target_url):
    create_notifications(
        group_user_ids(group_name, exclude_id=actor.id), actor=actor,
        kind=kind, text=text, target_url=target_url,
    )


def mark_read(notification):
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = utcnow()


def serialize_notification(notification):
    return {
        "id": notification.id,
        "text": notification.text,
        "kind": notification.kind,
        "target_url": notification.resolved_target_url,
        "actor": notification.actor.full_name if notification.actor else "Система",
        "is_read": notification.is_read,
        "created_at": notification.created_at.isoformat(),
        "read_at": notification.read_at.isoformat() if notification.read_at else None,
    }
