from datetime import date, datetime, time, timezone

from flask_login import UserMixin
from sqlalchemy import CheckConstraint, UniqueConstraint
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class User(UserMixin, TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    login = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    group_name = db.Column(db.String(80), nullable=False, index=True)
    avatar = db.Column(db.String(255))
    role = db.Column(db.String(20), nullable=False, default="STUDENT")

    __table_args__ = (CheckConstraint("role IN ('ADMIN', 'STUDENT')", name="ck_user_role"),)

    @property
    def is_admin(self):
        return self.role == "ADMIN"

    @property
    def can_view_metrics(self):
        return self.is_admin and self.login == "admin"

    @property
    def full_name(self):
        return f"{self.last_name} {self.first_name}".strip()

    @property
    def initials(self):
        return f"{self.first_name[:1]}{self.last_name[:1]}".upper()

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class PageView(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    endpoint = db.Column(db.String(80), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    user = db.relationship("User", backref=db.backref("page_views", cascade="all, delete-orphan"))
    __table_args__ = (db.Index("ix_page_view_user_created", "user_id", "created_at"),)


class Tag(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    color = db.Column(db.String(20), nullable=False, default="#6366f1")
    description = db.Column(db.String(255), default="")
    is_standard = db.Column(db.Boolean, nullable=False, default=False, index=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"))
    owner = db.relationship("User", backref=db.backref("tags", lazy=True, cascade="all, delete-orphan"))


class CellTag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    tag_id = db.Column(db.Integer, db.ForeignKey("tag.id", ondelete="CASCADE"), nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    student = db.relationship("User", foreign_keys=[student_id], backref=db.backref("cell_tags", lazy=True, cascade="all, delete-orphan"))
    created_by = db.relationship("User", foreign_keys=[created_by_id])
    tag = db.relationship("Tag")
    __table_args__ = (UniqueConstraint("student_id", "date", "tag_id", name="uq_cell_tag"),)


class Event(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, default="")
    date = db.Column(db.Date, nullable=False, index=True)
    start_time = db.Column(db.Time)
    end_time = db.Column(db.Time)
    type = db.Column(db.String(40), nullable=False, default="Другое")
    color = db.Column(db.String(20), nullable=False, default="#ef4444")
    location = db.Column(db.String(120), default="")
    group_name = db.Column(db.String(80), index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"))
    created_by = db.relationship("User")


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    student = db.relationship("User", foreign_keys=[student_id])
    author = db.relationship("User", foreign_keys=[author_id], backref=db.backref("comments", lazy=True, cascade="all, delete-orphan"))


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"))
    comment_id = db.Column(db.Integer, db.ForeignKey("comment.id", ondelete="CASCADE"))
    student_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"))
    date = db.Column(db.Date)
    text = db.Column(db.String(255), nullable=False)
    kind = db.Column(db.String(40), nullable=False, default="mention", index=True)
    target_url = db.Column(db.String(1000), default="")
    is_read = db.Column(db.Boolean, nullable=False, default=False, index=True)
    read_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    user = db.relationship("User", foreign_keys=[user_id], backref=db.backref("notifications", lazy=True, cascade="all, delete-orphan"))
    actor = db.relationship("User", foreign_keys=[actor_id])
    comment = db.relationship("Comment")
    student = db.relationship("User", foreign_keys=[student_id])

    @property
    def resolved_target_url(self):
        if self.target_url:
            return self.target_url
        if self.student_id and self.date:
            value = self.date.isoformat()
            return f"/?start={value}&open_student={self.student_id}&open_date={value}"
        return "/"


class ChatMessage(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_name = db.Column(db.String(80), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    text = db.Column(db.Text, nullable=False)

    author = db.relationship("User")
    replies = db.relationship("ChatReply", back_populates="message", cascade="all, delete-orphan", order_by="ChatReply.created_at")


class ChatReply(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey("chat_message.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    text = db.Column(db.Text, nullable=False)

    message = db.relationship("ChatMessage", back_populates="replies")
    author = db.relationship("User")


class ScheduleItem(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, index=True)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time)
    subject = db.Column(db.String(160), nullable=False)
    teacher = db.Column(db.String(160), default="")
    room = db.Column(db.String(80), default="")
    address = db.Column(db.String(160), default="")
    type = db.Column(db.String(40), nullable=False, default="Лекция")
    description = db.Column(db.Text, default="")
    group_name = db.Column(db.String(80), index=True)


class ScheduleImport(TimestampMixin, db.Model):
    """Links an imported occurrence to its row and remembers admin cancellations."""

    id = db.Column(db.Integer, primary_key=True)
    source_url = db.Column(db.String(1000), nullable=False)
    source_key = db.Column(db.String(64), nullable=False, unique=True, index=True)
    group_name = db.Column(db.String(80), nullable=False, index=True)
    period_start = db.Column(db.Date, nullable=False, index=True)
    period_end = db.Column(db.Date, nullable=False)
    schedule_item_id = db.Column(db.Integer, db.ForeignKey("schedule_item.id", ondelete="SET NULL"), unique=True)
    is_cancelled = db.Column(db.Boolean, nullable=False, default=False)
    schedule_item = db.relationship("ScheduleItem")


class Subject(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, default="")
    group_name = db.Column(db.String(80), nullable=False, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"))
    created_by = db.relationship("User")
    materials = db.relationship("Material", back_populates="subject", cascade="all, delete-orphan", order_by="Material.created_at.desc()")


class Material(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subject.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text, default="")
    link_url = db.Column(db.String(1000), default="")
    stored_filename = db.Column(db.String(255))
    original_filename = db.Column(db.String(255))
    file_size = db.Column(db.Integer)
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"))

    subject = db.relationship("Subject", back_populates="materials")
    created_by = db.relationship("User")
    comments = db.relationship("MaterialComment", back_populates="material", cascade="all, delete-orphan", order_by="MaterialComment.created_at")


class MaterialComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    material_id = db.Column(db.Integer, db.ForeignKey("material.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    material = db.relationship("Material", back_populates="comments")
    author = db.relationship("User")


def iso_date(value: date | None):
    return value.isoformat() if value else None


def iso_time(value: time | None):
    return value.strftime("%H:%M") if value else None
