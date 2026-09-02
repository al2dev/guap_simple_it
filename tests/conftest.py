import pytest

from app import create_app
from app.extensions import db
from app.models import Tag, User
from config import TestConfig


@pytest.fixture()
def app(tmp_path):
    app = create_app(TestConfig)
    app.config["UPLOAD_FOLDER"] = str(tmp_path / "avatars")
    app.config["MATERIAL_UPLOAD_FOLDER"] = str(tmp_path / "materials")
    (tmp_path / "avatars").mkdir()
    (tmp_path / "materials").mkdir()
    with app.app_context():
        student = User(login="Ivanov", first_name="Иван", last_name="Иванов", group_name="ИВ-23")
        student.set_password("ИВ-23")
        stranger = User(login="Other", first_name="Олег", last_name="Чужой", group_name="ДРУГАЯ")
        stranger.set_password("password")
        admin = db.session.scalar(db.select(User).where(User.role == "ADMIN"))
        db.session.add_all([student, stranger])
        db.session.flush()
        db.session.add(Tag(name="Был", color="#22c55e", is_standard=True, owner_id=admin.id))
        db.session.commit()
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, login, password):
    return client.post("/login", data={"login": login, "password": password}, follow_redirects=False)
