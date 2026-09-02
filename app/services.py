import re
from datetime import date, datetime, timedelta

from flask import current_app
from sqlalchemy import func

from .extensions import db
from .models import Event, ScheduleItem, Tag, User


HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
LOGIN_RE = re.compile(r"[^a-zA-Z0-9_.-]+")
CYRILLIC_MAP = str.maketrans({
    "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"e","ж":"zh","з":"z","и":"i","й":"y",
    "к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f",
    "х":"kh","ц":"ts","ч":"ch","ш":"sh","щ":"sch","ъ":"","ы":"y","ь":"","э":"e","ю":"yu","я":"ya",
})


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def parse_time(value: str | None):
    return datetime.strptime(value, "%H:%M").time() if value else None


def valid_color(value: str | None, fallback="#6366f1"):
    return value if value and HEX_COLOR.match(value) else fallback


def unique_login(last_name: str):
    source = last_name.strip().lower().translate(CYRILLIC_MAP).replace(" ", "")
    base = LOGIN_RE.sub("", source).capitalize() or "Student"
    candidate, suffix = base, 2
    while db.session.scalar(db.select(User).where(func.lower(User.login) == candidate.lower())):
        candidate = f"{base}{suffix}"
        suffix += 1
    return candidate


def ensure_initial_data():
    admin_login = current_app.config["ADMIN_LOGIN"]
    admin = db.session.scalar(db.select(User).where(func.lower(User.login) == admin_login.lower()))
    if not admin:
        admin = User(
            login=admin_login,
            first_name=current_app.config["ADMIN_FIRST_NAME"],
            last_name=current_app.config["ADMIN_LAST_NAME"],
            group_name=current_app.config["DEFAULT_GROUP"],
            role="ADMIN",
        )
        admin.set_password(current_app.config["ADMIN_PASSWORD"])
        db.session.add(admin)
        db.session.flush()

    if current_app.config["SEED_DEMO"]:
        seed_demo(admin)
    db.session.commit()


def seed_demo(admin):
    group = current_app.config["DEFAULT_GROUP"]
    students = [("Ivanov", "Иван", "Иванов"), ("Petrov", "Пётр", "Петров"), ("Sidorov", "Сергей", "Сидоров"), ("Smirnov", "Анна", "Смирнова")]
    for login, first, last in students:
        exists = db.session.scalar(db.select(User).where(func.lower(User.login) == login.lower()))
        if not exists:
            user = User(login=login, first_name=first, last_name=last, group_name=group)
            user.set_password(group)
            db.session.add(user)

    if not db.session.scalar(db.select(Tag).where(Tag.is_standard.is_(True))):
        for name, color in [("Был", "#22c55e"), ("Не был", "#ef4444"), ("Опоздал", "#f59e0b"), ("Важно", "#8b5cf6")]:
            db.session.add(Tag(name=name, color=color, is_standard=True, owner_id=admin.id))

    today = date.today()
    if not db.session.scalar(db.select(Event)):
        db.session.add_all([
            Event(title="Контрольная по математике", date=today + timedelta(days=2), start_time=parse_time("10:40"), type="Контрольная", color="#ef4444", location="302", group_name=group, created_by_id=admin.id),
            Event(title="Сдача лабораторной", date=today + timedelta(days=5), start_time=parse_time("12:20"), type="Лабораторная", color="#8b5cf6", location="214", group_name=group, created_by_id=admin.id),
        ])
    if not db.session.scalar(db.select(ScheduleItem)):
        db.session.add_all([
            ScheduleItem(date=today, start_time=parse_time("09:00"), end_time=parse_time("10:30"), subject="Математика", teacher="А. В. Орлов", room="302", group_name=group),
            ScheduleItem(date=today, start_time=parse_time("10:40"), end_time=parse_time("12:10"), subject="Программирование", teacher="М. И. Соколов", room="214", group_name=group),
        ])
