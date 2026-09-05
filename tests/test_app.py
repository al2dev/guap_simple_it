from datetime import date, time
from io import BytesIO
from pathlib import Path

from PIL import Image

from app.extensions import db
from app.extensions import socketio
from app.models import ChatMessage, ChatReply, Event, Material, MaterialComment, Notification, ScheduleImport, ScheduleItem, Subject, Tag, User
from app.schedule_import import parse_schedule_page, sync_schedule
from tests.conftest import login
from app.services import ensure_initial_data, unique_login


def test_login_logout_and_dashboard(client):
    response = login(client, "Ivanov", "ИВ-23")
    assert response.status_code == 302
    assert client.get("/").status_code == 200
    assert client.post("/logout").status_code == 302
    assert client.get("/").status_code == 302


def test_student_can_tag_own_cell_but_not_another(client, app):
    login(client, "Ivanov", "ИВ-23")
    with app.app_context():
        own = db.session.scalar(db.select(User).where(User.login == "Ivanov"))
        other = db.session.scalar(db.select(User).where(User.login == "Other"))
        tag_id = db.session.scalar(db.select(Tag.id).order_by(Tag.id))
    today = date.today().isoformat()
    assert client.post(f"/api/cell/{own.id}/{today}/tag", json={"tag_id": tag_id}).status_code == 201
    assert client.post(f"/api/cell/{other.id}/{today}/tag", json={"tag_id": tag_id}).status_code in (403, 404)


def test_comments_create_mentions_and_notifications(client, app):
    login(client, "Ivanov", "ИВ-23")
    with app.app_context():
        user = db.session.scalar(db.select(User).where(User.login == "Ivanov"))
        admin = db.session.scalar(db.select(User).where(User.role == "ADMIN"))
    response = client.post(f"/api/cell/{user.id}/{date.today().isoformat()}/comment", json={"text": f"@{admin.login} проверьте работу"})
    assert response.status_code == 201
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(Notification.id))) == 1


def test_admin_routes_and_event_api(client, app):
    login(client, "admin", "change-me")
    assert client.get("/admin").status_code == 200
    payload = {"title": "Экзамен", "date": date.today().isoformat(), "type": "Экзамен", "color": "#ef4444"}
    response = client.post("/api/admin/events", json=payload)
    assert response.status_code == 201
    event_id = response.get_json()["id"]
    payload["title"] = "Экзамен обновлён"
    assert client.put(f"/api/admin/events/{event_id}", json=payload).status_code == 200
    assert client.delete(f"/api/admin/events/{event_id}").status_code == 204


def test_student_cannot_access_admin(client):
    login(client, "Ivanov", "ИВ-23")
    assert client.get("/admin").status_code == 403


def test_profile_password_change(client):
    login(client, "Ivanov", "ИВ-23")
    response = client.post("/profile", data={"password-current_password": "ИВ-23", "password-new_password": "new-password", "password-confirm_password": "new-password", "password-submit_password": "Изменить пароль"}, follow_redirects=True)
    assert response.status_code == 200
    client.post("/logout")
    assert login(client, "Ivanov", "new-password").status_code == 302


def test_cyrillic_surname_is_transliterated_for_login(app):
    with app.app_context():
        assert unique_login("Смирнова") == "Smirnova"


def test_admin_html_crud_for_all_sections(client, app):
    login(client, "admin", "change-me")
    response = client.post("/admin/students", data={"first_name":"Мария","last_name":"Смирнова","group_name":"ИВ-23","password":"secret1","role":"STUDENT","submit":"Сохранить"})
    assert response.status_code == 302
    with app.app_context():
        student = db.session.scalar(db.select(User).where(User.login == "Smirnova"))
        student_id = student.id
    response = client.post(f"/admin/students/{student_id}/edit", data={"first_name":"Марина","last_name":"Смирнова","group_name":"ИВ-24","role":"STUDENT","submit":"Сохранить"})
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(User, student_id).login == "Smirnova"

    event_data={"title":"Зачёт","date":date.today().isoformat(),"type":"Зачёт","color":"#123456","submit":"Сохранить"}
    assert client.post("/admin/events", data=event_data).status_code == 302
    schedule_data={"date":date.today().isoformat(),"start_time":"09:00","subject":"Физика","type":"Лекция","submit":"Сохранить"}
    assert client.post("/admin/schedule", data=schedule_data).status_code == 302
    assert client.get(f"/api/day/{date.today().isoformat()}").get_json()["schedule"][0]["subject"] == "Физика"
    assert client.post("/admin/tags", data={"name":"Готово","color":"#22c55e","description":"Сдано","submit":"Сохранить"}).status_code == 302
    for path in ["/admin/students","/admin/events","/admin/schedule","/admin/tags"]:
        assert client.get(path).status_code == 200
    assert client.post(f"/admin/students/{student_id}/delete").status_code == 302


def test_avatar_upload_is_validated_and_saved(client, app):
    login(client, "Ivanov", "ИВ-23")
    image = Image.new("RGB", (32, 32), "#6366f1")
    content = BytesIO()
    image.save(content, format="PNG")
    content.seek(0)
    response = client.post("/profile", data={"profile-first_name":"Иван","profile-last_name":"Иванов","profile-avatar":(content,"avatar.png"),"profile-submit":"Сохранить профиль"}, content_type="multipart/form-data")
    assert response.status_code == 302
    with app.app_context():
        user = db.session.scalar(db.select(User).where(User.login == "Ivanov"))
        assert user.avatar and user.avatar.endswith(".png")


def test_calendar_is_continuous_and_schedule_highlights_every_row(client, app):
    with app.app_context():
        db.session.add(ScheduleItem(date=date.today(), start_time=time.min, subject="Алгебра", group_name="ИВ-23"))
        db.session.commit()
    login(client, "Ivanov", "ИВ-23")
    response = client.get("/")
    assert response.status_code == 200
    assert response.data.count(b'data-schedule-date=') == 180
    assert response.data.count(b'calendar-cell own-cell has-schedule') >= 1
    assert b'data-scroll-today' in response.data


def test_admin_can_create_and_delete_group_event_from_day_api(client, app):
    login(client, "admin", "change-me")
    payload = {"title":"Экзамен по физике","date":date.today().isoformat(),"type":"Экзамен","color":"#ef4444","group_name":"ИВ-23"}
    created = client.post("/api/admin/events", json=payload)
    assert created.status_code == 201
    event_id = created.get_json()["id"]
    day = client.get(f"/api/day/{date.today().isoformat()}")
    assert day.status_code == 200
    assert day.get_json()["events"][0]["title"] == "Экзамен по физике"
    assert client.delete(f"/api/admin/events/{event_id}").status_code == 204
    assert client.get(f"/api/day/{date.today().isoformat()}").get_json()["events"] == []


def test_guap_saved_page_is_parsed_and_expanded_without_duplicates(app):
    page = (Path(__file__).parent / "fixtures" / "guap_schedule.html").read_text(encoding="utf-8")
    templates = parse_schedule_page(page)
    assert templates
    assert any(item.subject == "Информатика" and item.week_parity == 1 for item in templates)
    assert any(item.subject == "Информатика" and item.week_parity is None for item in templates)
    informatics = next(item for item in templates if item.subject == "Информатика" and item.room == "22-09")
    assert informatics.lesson_type == "Лекция"
    assert informatics.address == "Ленсовета 14"
    assert informatics.teacher == "Турнецкая Е.Л."
    laboratory = next(item for item in templates if item.lesson_type == "Лабораторное занятие")
    assert laboratory.room == "24-03"
    assert laboratory.address == "Гастелло 15"
    assert laboratory.teacher == "Турнецкая Е.Л."
    with app.app_context():
        first = sync_schedule(page, "https://guap.ru/rasp?gr=7923", "ИВ-23", date(2026, 9, 3))
        count = db.session.scalar(db.select(db.func.count(ScheduleItem.id)))
        second = sync_schedule(page, "https://guap.ru/rasp?gr=7923", "ИВ-23", date(2026, 9, 3))
        assert first["created"] == count
        assert second["created"] == 0
        assert db.session.scalar(db.select(db.func.count(ScheduleItem.id))) == count
        assert db.session.scalar(db.select(db.func.count(ScheduleImport.id))) == count
        assert all(item.date.weekday() in {0, 5} for item in db.session.scalars(db.select(ScheduleItem)).all())


def test_real_schedule_configuration_removes_moving_demo_lessons(app):
    with app.app_context():
        app.config["URL_GROUP_SCHEDULE"] = "https://guap.ru/rasp?gr=7923"
        db.session.add_all([
            ScheduleItem(date=date.today(), start_time=time(9, 0), subject="Математика", teacher="А. В. Орлов", room="302", group_name="ИВ-23"),
            ScheduleItem(date=date.today(), start_time=time(10, 40), subject="Программирование", teacher="М. И. Соколов", room="214", group_name="ИВ-23"),
        ])
        db.session.commit()
        ensure_initial_data()
        assert db.session.scalar(db.select(db.func.count(ScheduleItem.id))) == 0


def test_admin_can_add_and_cancel_imported_schedule_from_day(client, app):
    login(client, "admin", "change-me")
    target = date(2026, 9, 5)
    payload = {"subject":"Дополнительная практика","date":target.isoformat(),"start_time":"15:10","end_time":"16:40","type":"Практическое занятие","room":"14-15","address":"Ленсовета 14","teacher":"Иванов И.И.","group_name":"ИВ-23"}
    created = client.post("/api/admin/schedule", json=payload)
    assert created.status_code == 201
    assert created.get_json()["address"] == "Ленсовета 14"
    assert client.delete(f"/api/admin/schedule/{created.get_json()['id']}").status_code == 204

    page = (Path(__file__).parent / "fixtures" / "guap_schedule.html").read_text(encoding="utf-8")
    with app.app_context():
        sync_schedule(page, "https://guap.ru/rasp?gr=7923", "ИВ-23", date(2026, 9, 3))
        imported = db.session.scalar(db.select(ScheduleImport).where(ScheduleImport.schedule_item_id.is_not(None)))
        imported_id = imported.schedule_item_id
    assert client.delete(f"/api/admin/schedule/{imported_id}").status_code == 204
    with app.app_context():
        marker = db.session.scalar(db.select(ScheduleImport).where(ScheduleImport.is_cancelled.is_(True)))
        assert marker and marker.schedule_item_id is None
        sync_schedule(page, "https://guap.ru/rasp?gr=7923", "ИВ-23", date(2026, 9, 3))
        assert db.session.get(ScheduleItem, imported_id) is None


def test_materials_subject_file_link_and_comments(client, app):
    login(client, "Ivanov", "ИВ-23")
    assert client.post("/materials/subjects", data={"name":"Программирование","description":"Лекции и практики"}).status_code == 302
    with app.app_context():
        subject = db.session.scalar(db.select(Subject).where(Subject.name == "Программирование"))
        subject_id = subject.id
    created = client.post(f"/materials/subjects/{subject_id}/items", data={"title":"Лекция 1","description":"Основы Python","link_url":"https://docs.python.org/3/","file":(BytesIO(b"lecture notes"),"notes.txt")}, content_type="multipart/form-data")
    assert created.status_code == 302
    with app.app_context():
        material = db.session.scalar(db.select(Material).where(Material.subject_id == subject_id))
        material_id, filename = material.id, material.stored_filename
    assert client.get(f"/materials?subject={subject_id}").status_code == 200
    download = client.get(f"/materials/files/{filename}")
    assert download.status_code == 200
    assert download.data == b"lecture notes"
    download.close()
    assert client.post(f"/materials/items/{material_id}/comments", data={"text":"Спасибо за материал"}).status_code == 302
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(MaterialComment.id))) == 1
    assert client.post(f"/materials/items/{material_id}/delete").status_code == 302


def test_material_upload_accepts_cyrillic_pdf_filename(client, app):
    login(client, "Ivanov", "ИВ-23")
    client.post("/materials/subjects", data={"name":"Документы"})
    with app.app_context():
        subject_id = db.session.scalar(db.select(Subject.id).where(Subject.name == "Документы"))
    response = client.post(
        f"/materials/subjects/{subject_id}/items",
        data={"title":"Методичка", "file":(BytesIO(b"%PDF-1.4\n%%EOF"), "Лекция №1.pdf")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    with app.app_context():
        material = db.session.scalar(db.select(Material).where(Material.subject_id == subject_id))
        assert material.original_filename == "Лекция №1.pdf"
        assert material.stored_filename.endswith(".pdf")


def test_material_upload_rejects_file_over_configured_limit(client, app):
    login(client, "Ivanov", "ИВ-23")
    client.post("/materials/subjects", data={"name":"Лимиты"})
    with app.app_context():
        subject_id = db.session.scalar(db.select(Subject.id).where(Subject.name == "Лимиты"))
        app.config["MAX_MATERIAL_SIZE"] = 10
    response = client.post(
        f"/materials/subjects/{subject_id}/items",
        data={"title":"Большой файл", "file":(BytesIO(b"%PDF-" + b"x" * 20), "Большой.pdf")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(Material.id)).where(Material.subject_id == subject_id)) == 0


def test_general_chat_keeps_replies_inside_message_and_mentions_all(client, app):
    login(client, "Ivanov", "ИВ-23")
    created = client.post("/chat/messages", data={"text": "@all Завтра встречаемся в 10:00"})
    assert created.status_code == 302
    with app.app_context():
        message = db.session.scalar(db.select(ChatMessage))
        message_id = message.id
        notification = db.session.scalar(db.select(Notification).where(Notification.kind == "chat_mention"))
        assert notification and notification.target_url == f"/chat#message-{message_id}"
    reply = client.post(f"/chat/messages/{message_id}/replies", data={"text": "Буду"})
    assert reply.status_code == 302
    with app.app_context():
        stored = db.session.scalar(db.select(ChatReply))
        assert stored.message_id == message_id
    thread = client.get(f"/chat/messages/{message_id}/thread")
    assert thread.status_code == 200
    assert thread.get_json()["replies"][0]["text"] == "Буду"
    page = client.get("/chat")
    assert page.status_code == 200
    assert b'id="message-' + str(message_id).encode() + b'"' in page.data
    assert b'data-open-thread=' in page.data
    assert b'>\xd0\x9a\xd0\xb0\xd0\xbb\xd0\xb5\xd0\xbd\xd0\xb4\xd0\xb0\xd1\x80\xd1\x8c<' in page.data


def test_chat_messages_are_rendered_oldest_first(client, app):
    login(client, "Ivanov", "ИВ-23")
    client.post("/chat/messages", data={"text": "Первое сообщение"})
    client.post("/chat/messages", data={"text": "Второе сообщение"})
    page = client.get("/chat")
    assert page.data.index("Первое сообщение".encode()) < page.data.index("Второе сообщение".encode())


def test_chat_message_can_be_sent_without_page_reload(client, app):
    login(client, "Ivanov", "ИВ-23")
    created = client.post(
        "/chat/messages", data={"text": "Сообщение в реальном времени"},
        headers={"Accept": "application/json"},
    )
    assert created.status_code == 201
    message = created.get_json()["message"]
    assert message["text"] == "Сообщение в реальном времени"
    assert message["mine"] is True


def test_websocket_pushes_chat_replies_counts_and_notifications(app):
    recipient_http = app.test_client()
    login(recipient_http, "admin", "change-me")
    recipient_socket = socketio.test_client(app, flask_test_client=recipient_http)
    assert recipient_socket.is_connected()
    recipient_socket.get_received()

    author_http = app.test_client()
    login(author_http, "Ivanov", "ИВ-23")
    created = author_http.post(
        "/chat/messages", data={"text": "@all WebSocket сообщение"},
        headers={"Accept": "application/json"},
    )
    assert created.status_code == 201
    message_id = created.get_json()["message"]["id"]
    received = recipient_socket.get_received()
    assert any(item["name"] == "chat:message_created" and item["args"][0]["id"] == message_id for item in received)
    assert any(item["name"] == "notification:new" and item["args"][0]["kind"] == "chat_mention" for item in received)

    reply = author_http.post(
        f"/chat/messages/{message_id}/replies", data={"text": "Ответ через WebSocket"},
        headers={"Accept": "application/json"},
    )
    assert reply.status_code == 201
    received = recipient_socket.get_received()
    event = next(item for item in received if item["name"] == "chat:reply_created")
    assert event["args"][0]["message_id"] == message_id
    assert event["args"][0]["reply_count"] == 1

    snapshot = recipient_socket.emit(
        "chat:sync", {"after_id": 0, "message_ids": [message_id]}, callback=True
    )
    assert snapshot["reply_counts"][str(message_id)] == 1
    recipient_socket.disconnect()


def test_websocket_rejects_anonymous_connection(app):
    anonymous_socket = socketio.test_client(app)
    assert not anonymous_socket.is_connected()


def test_notification_panel_moves_seen_item_to_history(client, app):
    login(client, "Ivanov", "ИВ-23")
    client.post("/chat/messages", data={"text": "@all Важное сообщение"})
    client.post("/logout")
    login(client, "admin", "change-me")
    active_response = client.get("/api/notifications?status=active")
    assert active_response.headers["Cache-Control"] == "no-store"
    active = active_response.get_json()
    assert active["unread"] == 1
    assert active["notifications"][0]["kind"] == "chat_mention"
    notification_id = active["notifications"][0]["id"]
    opened = client.post(f"/api/notifications/{notification_id}/read").get_json()
    assert opened["target_url"].startswith("/chat#message-")
    assert client.get("/api/notifications?status=active").get_json()["notifications"] == []
    history = client.get("/api/notifications?status=history").get_json()["notifications"]
    assert history[0]["id"] == notification_id
    assert history[0]["read_at"] is not None


def test_material_and_calendar_changes_create_linked_notifications(client, app):
    login(client, "Ivanov", "ИВ-23")
    client.post("/materials/subjects", data={"name": "Сети"})
    with app.app_context():
        subject = db.session.scalar(db.select(Subject).where(Subject.name == "Сети"))
        assert db.session.scalar(db.select(Notification).where(Notification.kind == "subject_created")).target_url == f"/materials?subject={subject.id}"
    client.post("/logout")
    login(client, "admin", "change-me")
    payload = {"title": "Собрание", "date": date.today().isoformat(), "type": "Встреча", "group_name": "ИВ-23"}
    client.post("/api/admin/events", json=payload)
    with app.app_context():
        notification = db.session.scalar(db.select(Notification).where(Notification.kind == "event_created"))
        assert f"open_day={date.today().isoformat()}" in notification.target_url
