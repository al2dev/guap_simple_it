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
    def full_name(self):
        return f"{self.last_name} {self.first_name}".strip()

    @property
    def initials(self):
        return f"{self.first_name[:1]}{self.last_name[:1]}".upper()

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


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
    student_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    text = db.Column(db.String(255), nullable=False)
    is_read = db.Column(db.Boolean, nullable=False, default=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    user = db.relationship("User", foreign_keys=[user_id], backref=db.backref("notifications", lazy=True, cascade="all, delete-orphan"))
    actor = db.relationship("User", foreign_keys=[actor_id])
    comment = db.relationship("Comment")
    student = db.relationship("User", foreign_keys=[student_id])


class ScheduleItem(TimestampMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, index=True)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time)
    subject = db.Column(db.String(160), nullable=False)
    teacher = db.Column(db.String(160), default="")
    room = db.Column(db.String(80), default="")
    type = db.Column(db.String(40), nullable=False, default="Лекция")
    description = db.Column(db.Text, default="")
    group_name = db.Column(db.String(80), index=True)


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
