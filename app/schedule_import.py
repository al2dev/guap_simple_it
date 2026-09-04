import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from html.parser import HTMLParser
from urllib.request import Request, urlopen

from .extensions import db
from .models import ScheduleImport, ScheduleItem


LOGGER = logging.getLogger(__name__)
WEEKDAYS = {
    "Понедельник": 0,
    "Вторник": 1,
    "Среда": 2,
    "Четверг": 3,
    "Пятница": 4,
    "Суббота": 5,
    "Воскресенье": 6,
}
TIME_RANGE_RE = re.compile(r"(\d{1,2}:\d{2})\s*[—–-]\s*(\d{1,2}:\d{2})")


class _Node:
    def __init__(self, tag="root", attrs=None, parent=None):
        self.tag = tag
        self.attrs = dict(attrs or [])
        self.parent = parent
        self.children = []
        self.content = []

    @property
    def classes(self):
        return set(self.attrs.get("class", "").split())

    def text(self):
        values = [item.text() if isinstance(item, _Node) else item for item in self.content]
        return " ".join(" ".join(values).split())

    def descendants(self, tag=None):
        for child in self.children:
            if tag is None or child.tag == tag:
                yield child
            yield from child.descendants(tag)


class _ScheduleHTMLParser(HTMLParser):
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node()
        self.current = self.root

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs, self.current)
        self.current.children.append(node)
        self.current.content.append(node)
        if tag not in self.VOID_TAGS:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        node = _Node(tag, attrs, self.current)
        self.current.children.append(node)
        self.current.content.append(node)

    def handle_endtag(self, tag):
        node = self.current
        while node is not self.root:
            if node.tag == tag:
                self.current = node.parent
                return
            node = node.parent

    def handle_data(self, data):
        if data.strip():
            self.current.content.append(data)


@dataclass(frozen=True)
class LessonTemplate:
    weekday: int
    week_parity: int | None
    start_time: time
    end_time: time
    subject: str
    teacher: str
    room: str
    address: str
    lesson_type: str
    source_teacher: str
    source_room: str


def _first_descendant(node, predicate):
    return next((child for child in node.descendants() if predicate(child)), None)


def parse_schedule_page(html: str) -> list[LessonTemplate]:
    """Parse the expanded GUAP schedule page into weekly lesson templates."""
    parser = _ScheduleHTMLParser()
    parser.feed(html)
    lessons = []
    for heading in parser.root.descendants("h4"):
        heading_text = heading.text()
        if heading_text not in WEEKDAYS or not heading.parent:
            continue
        siblings = heading.parent.children
        index = siblings.index(heading) + 1
        time_range = None
        while index < len(siblings) and siblings[index].tag != "h4":
            node = siblings[index]
            index += 1
            match = TIME_RANGE_RE.search(node.text()) if node.tag == "div" else None
            if match and "text-danger" in node.classes:
                time_range = (match.group(1), match.group(2))
                continue
            if not time_range or node.tag != "div" or not {"mb-3", "d-flex"}.issubset(node.classes):
                continue
            direct_divs = [child for child in node.children if child.tag == "div"]
            if len(direct_divs) < 2:
                continue
            marker, content = direct_divs[0], direct_divs[1]
            type_node = _first_descendant(content, lambda child: child.tag == "div" and "fs-6" in child.classes)
            subject_node = _first_descendant(content, lambda child: child.tag == "div" and "lead" in child.classes)
            details_node = _first_descendant(content, lambda child: child.tag == "div" and "opacity-75" in child.classes)
            if not type_node or not subject_node:
                continue
            room_node = _first_descendant(details_node or content, lambda child: child.tag == "a" and re.search(r"[?&]ad=", child.attrs.get("href", "")))
            teacher_node = _first_descendant(details_node or content, lambda child: child.tag == "a" and re.search(r"[?&]pr=", child.attrs.get("href", "")))
            details_text = (details_node or content).text()
            room_fallback = re.search(r"ауд\.\s*(.*?)\s+[—–-]\s+", details_text, re.IGNORECASE)
            teacher_fallback = re.search(r"преп:\s*(.*?)(?:\s+гр:|$)", details_text, re.IGNORECASE)
            source_room = room_node.text() if room_node else (room_fallback.group(1).strip() if room_fallback else "")
            room_match = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", source_room)
            room = room_match.group(1).strip() if room_match else source_room
            address = room_match.group(2).strip() if room_match else ""
            source_teacher = teacher_node.text() if teacher_node else (teacher_fallback.group(1).strip(" .") if teacher_fallback else "")
            teacher = source_teacher.split(",", 1)[0].strip()
            parity = 1 if "week1" in marker.classes else 2 if "week2" in marker.classes else None
            lessons.append(LessonTemplate(
                weekday=WEEKDAYS[heading_text],
                week_parity=parity,
                start_time=datetime.strptime(time_range[0], "%H:%M").time(),
                end_time=datetime.strptime(time_range[1], "%H:%M").time(),
                subject=subject_node.text(),
                teacher=teacher,
                room=room,
                address=address,
                lesson_type=type_node.text().strip(),
                source_teacher=source_teacher,
                source_room=source_room,
            ))
    if not lessons:
        raise ValueError("На странице не найдено расписание по дням недели")
    return lessons


def semester_period(today: date) -> tuple[date, date]:
    if (today.month, today.day) > (8, 1):
        return date(today.year, 9, 1), date(today.year, 12, 31)
    return date(today.year, 1, 10), date(today.year, 5, 31)


def expand_schedule(templates: list[LessonTemplate], start: date, end: date):
    week_anchor = start - timedelta(days=start.weekday())
    current = start
    while current <= end:
        week_parity = ((current - week_anchor).days // 7) % 2 + 1
        for lesson in templates:
            if lesson.weekday == current.weekday() and (lesson.week_parity is None or lesson.week_parity == week_parity):
                yield current, lesson
        current += timedelta(days=1)


def _source_key(group_name: str, occurrence_date: date, lesson: LessonTemplate) -> str:
    # Raw values keep keys compatible with imports made before room/address splitting.
    value = "|".join((group_name, occurrence_date.isoformat(), lesson.start_time.isoformat(), lesson.end_time.isoformat(), lesson.subject, lesson.source_teacher, lesson.source_room, lesson.lesson_type))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sync_schedule(html: str, source_url: str, group_name: str, today: date | None = None) -> dict:
    templates = parse_schedule_page(html)
    period_start, period_end = semester_period(today or date.today())
    expected_keys = set()
    created = updated = cancelled = 0
    existing = {
        row.source_key: row
        for row in db.session.scalars(db.select(ScheduleImport).where(
            ScheduleImport.group_name == group_name,
            ScheduleImport.period_start == period_start,
            ScheduleImport.period_end == period_end,
        )).all()
    }
    for occurrence_date, lesson in expand_schedule(templates, period_start, period_end):
        key = _source_key(group_name, occurrence_date, lesson)
        if key in expected_keys:
            continue
        expected_keys.add(key)
        imported = existing.get(key)
        if imported and imported.is_cancelled:
            cancelled += 1
            continue
        if not imported:
            imported = ScheduleImport(source_url=source_url, source_key=key, group_name=group_name, period_start=period_start, period_end=period_end)
            db.session.add(imported)
        item = imported.schedule_item
        if not item:
            item = ScheduleItem()
            db.session.add(item)
            imported.schedule_item = item
            created += 1
        else:
            updated += 1
        item.date = occurrence_date
        item.start_time = lesson.start_time
        item.end_time = lesson.end_time
        item.subject = lesson.subject[:160]
        item.teacher = lesson.teacher[:160]
        item.room = lesson.room[:80]
        item.address = lesson.address[:160]
        item.type = lesson.lesson_type[:40] or "Занятие"
        item.group_name = group_name
        imported.source_url = source_url

    removed = 0
    for key, imported in existing.items():
        if key not in expected_keys:
            if imported.schedule_item:
                db.session.delete(imported.schedule_item)
            db.session.delete(imported)
            removed += 1
    db.session.commit()
    return {"templates": len(templates), "created": created, "updated": updated, "cancelled": cancelled, "removed": removed}


def download_schedule(url: str, timeout: float = 10) -> str:
    request = Request(url, headers={"User-Agent": "StudentDashboardSchedule/1.0"})
    with urlopen(request, timeout=timeout) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
    try:
        return raw.decode(charset)
    except (LookupError, UnicodeDecodeError):
        return raw.decode("utf-8", errors="replace")


def import_configured_schedule(app):
    url = app.config.get("URL_GROUP_SCHEDULE", "")
    if not url:
        return None
    try:
        html = download_schedule(url, app.config.get("SCHEDULE_FETCH_TIMEOUT", 10))
        result = sync_schedule(html, url, app.config["DEFAULT_GROUP"])
        app.logger.info("Schedule import completed: %s", result)
        return result
    except Exception:
        db.session.rollback()
        app.logger.warning("Schedule import from %s failed; application startup continues", url, exc_info=True)
        return None


def cancel_or_delete_schedule(item: ScheduleItem):
    imported = db.session.scalar(db.select(ScheduleImport).where(ScheduleImport.schedule_item_id == item.id))
    if imported:
        imported.is_cancelled = True
        imported.schedule_item = None
    db.session.delete(item)
