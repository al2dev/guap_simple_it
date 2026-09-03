import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'instance' / 'app.db'}")
    return url.replace("postgres://", "postgresql+psycopg://", 1) if url.startswith("postgres://") else url


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024
    MAX_AVATAR_SIZE = 3 * 1024 * 1024
    MAX_MATERIAL_SIZE = 20 * 1024 * 1024
    UPLOAD_FOLDER = str(BASE_DIR / "uploads" / "avatars")
    MATERIAL_UPLOAD_FOLDER = str(BASE_DIR / "uploads" / "materials")
    ADMIN_LOGIN = os.getenv("ADMIN_LOGIN", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change-me")
    ADMIN_FIRST_NAME = os.getenv("ADMIN_FIRST_NAME", "Администратор")
    ADMIN_LAST_NAME = os.getenv("ADMIN_LAST_NAME", "Системы")
    DEFAULT_GROUP = os.getenv("DEFAULT_GROUP", "ИВ-23")
    URL_GROUP_SCHEDULE = os.getenv("URL_GROUP_SCHEDULE", "").strip()
    SCHEDULE_FETCH_TIMEOUT = float(os.getenv("SCHEDULE_FETCH_TIMEOUT", "10"))
    SEED_DEMO = os.getenv("SEED_DEMO", "false").lower() in {"1", "true", "yes"}
    AUTO_CREATE_DB = os.getenv("AUTO_CREATE_DB", "true").lower() in {"1", "true", "yes"}
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"


class TestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    AUTO_CREATE_DB = True
    SEED_DEMO = False
    ADMIN_LOGIN = "admin"
    ADMIN_PASSWORD = "change-me"
    ADMIN_FIRST_NAME = "Test"
    ADMIN_LAST_NAME = "Admin"
    DEFAULT_GROUP = "ИВ-23"
    URL_GROUP_SCHEDULE = ""
