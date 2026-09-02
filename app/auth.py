from urllib.parse import urlsplit

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy import func

from .extensions import db
from .forms import LoginForm
from .models import User


bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.scalar(db.select(User).where(func.lower(User.login) == form.login.data.strip().lower()))
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            next_url = request.args.get("next")
            if not next_url or urlsplit(next_url).netloc:
                next_url = url_for("main.dashboard")
            return redirect(next_url)
        flash("Неверный логин или пароль", "danger")
    return render_template("login.html", form=form)


@bp.post("/logout")
def logout():
    logout_user()
    flash("Вы вышли из аккаунта", "success")
    return redirect(url_for("auth.login"))
