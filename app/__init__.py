from pathlib import Path

from flask import Flask, flash, jsonify, redirect, request, url_for
from flask_login import current_user

from config import Config

from .extensions import csrf, db, login_manager, migrate, socketio


def create_app(config_object=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["MATERIAL_UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    socketio.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Войдите, чтобы продолжить."
    login_manager.login_message_category = "warning"

    from .admin import bp as admin_bp
    from .api import bp as api_bp
    from .auth import bp as auth_bp
    from .main import bp as main_bp
    from .models import Notification, User
    from .metrics import record_page_view

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(admin_bp)
    app.after_request(record_page_view)

    from .realtime import register_handlers
    register_handlers()

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    @app.context_processor
    def globals_for_templates():
        unread = 0
        if current_user.is_authenticated:
            unread = db.session.scalar(db.select(db.func.count(Notification.id)).where(Notification.user_id == current_user.id, Notification.is_read.is_(False))) or 0
        return {"unread_notifications": unread}

    @app.errorhandler(403)
    def forbidden(_error):
        if request.path.startswith("/api/"):
            return jsonify(error="Недостаточно прав"), 403
        return "Недостаточно прав", 403

    @app.errorhandler(404)
    def not_found(_error):
        if request.path.startswith("/api/"):
            return jsonify(error="Не найдено"), 404
        return "Страница не найдена", 404

    @app.errorhandler(413)
    def request_too_large(_error):
        limit_mb = app.config["MAX_MATERIAL_SIZE"] // (1024 * 1024)
        if request.path.startswith("/api/"):
            return jsonify(error=f"Файл превышает допустимый размер {limit_mb} МБ"), 413
        flash(f"Файл превышает допустимый размер {limit_mb} МБ", "danger")
        return redirect(url_for("main.materials")), 303

    if app.config["AUTO_CREATE_DB"]:
        with app.app_context():
            db.create_all()
            from .services import ensure_initial_data
            ensure_initial_data()

    if app.config.get("URL_GROUP_SCHEDULE"):
        with app.app_context():
            from .schedule_import import import_configured_schedule
            import_configured_schedule(app)

    @app.cli.command("init-data")
    def init_data_command():
        """Create the configured admin and optional demo records."""
        from .services import ensure_initial_data
        ensure_initial_data()
        print("Initial data is ready.")

    return app
