import pytest

from app.extensions import db
from app.models import Material, Subject
from tests.conftest import login


def test_open_material_from_notification(client, app):
    login(client, "Ivanov", "ИВ-23")
    client.post("/materials/subjects", data={"name": "Сети"})
    with app.app_context():
        subject_id = db.session.scalar(db.select(Subject.id))
    for title in ["Первая лекция", "Вторая лекция"]:
        assert client.post(f"/materials/subjects/{subject_id}/items", data={
            "title": title, "link_url": "https://example.com/lecture",
        }).status_code == 302
    with app.app_context():
        material_ids = list(db.session.scalars(db.select(Material.id).order_by(Material.id)))
    client.post("/logout")
    login(client, "admin", "change-me")
    notifications = client.get("/api/notifications?status=active").get_json()["notifications"]
    notification = next(item for item in notifications
                        if item["kind"] == "material_created" and "Вторая лекция" in item["text"])
    opened = client.post(f'/api/notifications/{notification["id"]}/read')
    assert opened.status_code == 200
    response = client.get(opened.get_json()["target_url"])
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert f'class="collapse show" id="comments-{material_ids[1]}"' in html
    assert f'class="collapse " id="comments-{material_ids[0]}"' in html


@pytest.mark.parametrize("query", ["", "?material=", "?material=invalid", "?material=999999"])
def test_material_page_without_valid_target_keeps_comments_closed(client, app, query):
    with app.app_context():
        subject = Subject(name="Сети", group_name="ИВ-23")
        db.session.add(subject)
        db.session.flush()
        material = Material(subject_id=subject.id, title="Лекция")
        db.session.add(material)
        db.session.commit()
        material_id = material.id
    login(client, "Ivanov", "ИВ-23")
    response = client.get("/materials" + query)
    assert response.status_code == 200
    assert f'class="collapse " id="comments-{material_id}"' in response.get_data(as_text=True)
