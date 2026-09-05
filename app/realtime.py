from flask import request
from flask_login import current_user
from flask_socketio import join_room
from sqlalchemy import event
from sqlalchemy.orm import Session

from .extensions import socketio


def group_room(group_name):
    return f"group:{group_name}"


def user_room(user_id):
    return f"user:{user_id}"


def queue_socket_event(event_name, payload, room):
    """Publish only after the surrounding database transaction succeeds."""
    from .extensions import db
    db.session.info.setdefault("socket_events", []).append((event_name, payload, room))


@event.listens_for(Session, "after_commit")
def publish_committed_events(session):
    for event_name, payload, room in session.info.pop("socket_events", []):
        socketio.emit(event_name, payload, to=room)


@event.listens_for(Session, "after_rollback")
def discard_rolled_back_events(session):
    session.info.pop("socket_events", None)


def connect():
    if not current_user.is_authenticated:
        return False
    join_room(group_room(current_user.group_name))
    join_room(user_room(current_user.id))
    return True


def sync_notifications(data=None):
    if not current_user.is_authenticated:
        return {"error": "unauthorized"}
    from .extensions import db
    from .models import Notification
    from .notifications import serialize_notification

    status = (data or {}).get("status", "active")
    condition = Notification.is_read.is_(True) if status == "history" else Notification.is_read.is_(False)
    order = Notification.read_at.desc() if status == "history" else Notification.created_at.desc()
    items = db.session.scalars(
        db.select(Notification)
        .where(Notification.user_id == current_user.id, condition)
        .order_by(order, Notification.created_at.desc())
        .limit(100)
    ).all()
    unread = db.session.scalar(
        db.select(db.func.count(Notification.id)).where(
            Notification.user_id == current_user.id, Notification.is_read.is_(False)
        )
    ) or 0
    return {"unread": unread, "notifications": [serialize_notification(item) for item in items]}


def sync_chat(data=None):
    if not current_user.is_authenticated:
        return {"error": "unauthorized"}
    from .extensions import db
    from .models import ChatMessage

    try:
        after_id = max(int((data or {}).get("after_id", 0)), 0)
    except (TypeError, ValueError):
        after_id = 0
    visible_ids = []
    for value in (data or {}).get("message_ids", [])[:100]:
        try:
            message_id = int(value)
        except (TypeError, ValueError):
            continue
        if message_id > 0:
            visible_ids.append(message_id)
    messages = db.session.scalars(
        db.select(ChatMessage)
        .where(ChatMessage.group_name == current_user.group_name, ChatMessage.id > after_id)
        .order_by(ChatMessage.id)
        .limit(100)
    ).all()
    reply_counts = {}
    if visible_ids:
        from .models import ChatReply
        reply_counts = dict(db.session.execute(
            db.select(ChatMessage.id, db.func.count(ChatReply.id))
            .outerjoin(ChatReply, ChatReply.message_id == ChatMessage.id)
            .where(ChatMessage.group_name == current_user.group_name, ChatMessage.id.in_(set(visible_ids)))
            .group_by(ChatMessage.id)
        ).all())
    return {
        "messages": [_chat_message_payload(message) for message in messages],
        "reply_counts": reply_counts,
    }


def sync_thread(data=None):
    if not current_user.is_authenticated:
        return {"error": "unauthorized"}
    from .extensions import db
    from .models import ChatMessage

    try:
        message_id = int((data or {}).get("message_id"))
    except (TypeError, ValueError):
        return {"error": "invalid_message"}
    message = db.session.get(ChatMessage, message_id)
    if not message or message.group_name != current_user.group_name:
        return {"error": "not_found"}
    return {
        "message": {
            "id": message.id, "author": message.author.full_name,
            "initials": message.author.initials, "text": message.text,
            "created_at": message.created_at.isoformat(),
        },
        "replies": [_chat_reply_payload(reply) for reply in message.replies],
    }


def _chat_message_payload(message):
    return {
        "id": message.id, "author_id": message.author_id,
        "author": message.author.full_name,
        "initials": message.author.initials, "text": message.text,
        "created_at": message.created_at.isoformat(),
        "mine": message.author_id == current_user.id,
        "can_delete": current_user.is_admin or message.author_id == current_user.id,
        "reply_count": len(message.replies),
    }


def _chat_reply_payload(reply):
    return {
        "id": reply.id, "author_id": reply.author_id,
        "author": reply.author.full_name,
        "initials": reply.author.initials, "text": reply.text,
        "created_at": reply.created_at.isoformat(),
        "can_delete": current_user.is_admin or reply.author_id == current_user.id,
    }


def register_handlers():
    """Register handlers on the Socket.IO server created for this app factory call."""
    socketio.on_event("connect", connect)
    socketio.on_event("notifications:sync", sync_notifications)
    socketio.on_event("chat:sync", sync_chat)
    socketio.on_event("chat:thread", sync_thread)
