from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import BooleanField, DateField, PasswordField, SelectField, StringField, SubmitField, TextAreaField, TimeField
from wtforms.validators import DataRequired, EqualTo, Length, Optional


class LoginForm(FlaskForm):
    login = StringField("Логин", validators=[DataRequired(), Length(max=80)])
    password = PasswordField("Пароль", validators=[DataRequired()])
    remember = BooleanField("Запомнить меня")
    submit = SubmitField("Войти")


class ProfileForm(FlaskForm):
    first_name = StringField("Имя", validators=[DataRequired(), Length(max=80)])
    last_name = StringField("Фамилия", validators=[DataRequired(), Length(max=80)])
    avatar = FileField("Аватар", validators=[Optional(), FileAllowed(["jpg", "jpeg", "png", "webp"], "Только JPG, PNG или WebP")])
    submit = SubmitField("Сохранить профиль")


class PasswordForm(FlaskForm):
    current_password = PasswordField("Текущий пароль", validators=[DataRequired()])
    new_password = PasswordField("Новый пароль", validators=[DataRequired(), Length(min=6, max=128)])
    confirm_password = PasswordField("Повторите пароль", validators=[DataRequired(), EqualTo("new_password")])
    submit_password = SubmitField("Изменить пароль")


class StudentForm(FlaskForm):
    first_name = StringField("Имя", validators=[DataRequired(), Length(max=80)])
    last_name = StringField("Фамилия", validators=[DataRequired(), Length(max=80)])
    group_name = StringField("Группа", validators=[DataRequired(), Length(max=80)])
    password = PasswordField("Пароль", validators=[Optional(), Length(min=5, max=128)])
    role = SelectField("Роль", choices=[("STUDENT", "Студент"), ("ADMIN", "Администратор")])
    submit = SubmitField("Сохранить")


class EventForm(FlaskForm):
    title = StringField("Название", validators=[DataRequired(), Length(max=160)])
    date = DateField("Дата", validators=[DataRequired()])
    start_time = TimeField("Начало", validators=[Optional()])
    end_time = TimeField("Окончание", validators=[Optional()])
    type = SelectField("Тип", choices=[("Экзамен", "Экзамен"), ("Зачёт", "Зачёт"), ("Контрольная", "Контрольная"), ("Лабораторная", "Лабораторная"), ("Встреча", "Встреча"), ("Другое", "Другое")])
    color = StringField("Цвет", validators=[DataRequired(), Length(max=20)])
    location = StringField("Место", validators=[Optional(), Length(max=120)])
    group_name = StringField("Группа", validators=[Optional(), Length(max=80)])
    description = TextAreaField("Описание", validators=[Optional()])
    submit = SubmitField("Сохранить")


class ScheduleForm(FlaskForm):
    date = DateField("Дата", validators=[DataRequired()])
    start_time = TimeField("Начало", validators=[DataRequired()])
    end_time = TimeField("Окончание", validators=[Optional()])
    subject = StringField("Предмет", validators=[DataRequired(), Length(max=160)])
    teacher = StringField("Преподаватель", validators=[Optional(), Length(max=160)])
    room = StringField("Аудитория", validators=[Optional(), Length(max=80)])
    type = SelectField("Тип", choices=[("Лекция", "Лекция"), ("Практика", "Практика"), ("Лабораторная", "Лабораторная"), ("Экзамен", "Экзамен")])
    group_name = StringField("Группа", validators=[Optional(), Length(max=80)])
    description = TextAreaField("Описание", validators=[Optional()])
    submit = SubmitField("Сохранить")


class TagForm(FlaskForm):
    name = StringField("Название", validators=[DataRequired(), Length(max=80)])
    color = StringField("Цвет", validators=[DataRequired(), Length(max=20)])
    description = StringField("Описание", validators=[Optional(), Length(max=255)])
    submit = SubmitField("Сохранить")
