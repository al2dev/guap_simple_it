# Student Dashboard

Рабочий MVP пространства одной учебной группы: интерактивный календарь студентов, метки, события, расписание, комментарии, уведомления, профиль и административная панель.

## Возможности

- авторизация через Flask-Login, хеширование паролей Werkzeug;
- календарь на неделю, две недели или месяц со sticky-колонкой студентов;
- offcanvas без перезагрузки страницы: метки, события, пары и комментарии;
- личные и стандартные метки с произвольным цветом;
- упоминания вида `@login` и уведомления со ссылкой на ячейку;
- профиль, безопасная смена пароля и проверяемая загрузка аватара до 3 МБ;
- административный CRUD студентов, событий, расписания и стандартных меток;
- автоматический импорт расписания ГУАП из `URL_GROUP_SCHEDULE` при запуске;
- серверная проверка группы и прав на каждое изменение;
- светлая/тёмная тема в `localStorage`, адаптивный интерфейс;
- SQLite для быстрого локального запуска и PostgreSQL в Docker Compose;
- Alembic/Flask-Migrate и автоматические тесты ключевых сценариев.

## Самый быстрый запуск: Docker + PostgreSQL

1. Проверьте настройки в `.env`. Обязательно смените `SECRET_KEY` и `ADMIN_PASSWORD` перед публичным размещением.
2. Запустите:

```bash
docker compose up --build
```

3. Откройте <http://localhost:5000>.

Контейнер `web` дождётся PostgreSQL, применит миграции, создаст администратора и, если `SEED_DEMO=true`, демонстрационные данные. Данные PostgreSQL и аватары хранятся в Docker volumes.

Остановка:

```bash
docker compose down
```

Удаление контейнеров вместе с локальными данными выполняется только явно:

```bash
docker compose down -v
```

## Локальный запуск с SQLite

Требуется Python 3.12 или новее.

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

По умолчанию база появится в `instance/app.db`, а аватары — в `uploads/avatars/`. Приложение доступно по адресу <http://127.0.0.1:5000>.

### Переменные `.env`

| Переменная | Назначение |
|---|---|
| `SECRET_KEY` | Подпись сессий и CSRF-токенов. В production задайте случайное длинное значение. |
| `ADMIN_LOGIN` | Логин автоматически создаваемого администратора. |
| `ADMIN_PASSWORD` | Его начальный пароль. Применяется только при создании аккаунта. |
| `DEFAULT_GROUP` | Группа администратора и demo-студентов. |
| `SEED_DEMO` | `true` создаёт Иванова, Петрова, Сидорова, Смирнову, метки и несколько записей. |
| `DATABASE_URL` | URL SQLite или PostgreSQL. Если отсутствует, используется SQLite. |
| `AUTO_CREATE_DB` | Удобное создание таблиц для локальной разработки. В Docker миграции используются явно. |
| `URL_GROUP_SCHEDULE` | Ссылка на расширенное расписание группы ГУАП. Если не задана или недоступна, запуск продолжается без импорта. |
| `SCHEDULE_FETCH_TIMEOUT` | Таймаут загрузки расписания в секундах, по умолчанию `10`. |

Осеннее расписание разворачивается на даты с 1 сентября по 31 декабря, весеннее — с 10 января по 31 мая. Повторный запуск обновляет импорт без дубликатов. Удаление импортированной пары администратором создаёт устойчивое исключение для конкретной даты, поэтому она не вернётся после перезапуска.

Demo-студенты входят с логинами `Ivanov`, `Petrov`, `Sidorov`, `Smirnov`; их пароль совпадает с `DEFAULT_GROUP`.

## Миграции и инициализация

Для нового окружения без `AUTO_CREATE_DB`:

```bash
flask --app wsgi:app db upgrade
flask --app wsgi:app init-data
```

После изменения моделей:

```bash
flask --app wsgi:app db migrate -m "описание изменения"
flask --app wsgi:app db upgrade
```

Администратор создаётся при первом запуске. Изменение `ADMIN_PASSWORD` позднее не перезаписывает пароль существующего аккаунта — его можно сменить в профиле.

## PostgreSQL без Docker для приложения

Создайте базу и задайте, например:

```dotenv
DATABASE_URL=postgresql+psycopg://student:student@localhost:5432/student_dashboard
AUTO_CREATE_DB=false
```

Затем примените миграции и выполните `init-data`, как описано выше.

## Аватары

Разрешены JPG, PNG и WebP. Сервер проверяет содержимое через Pillow, очищает имя файла, генерирует случайное имя и ограничивает запрос 3 МБ. Для production каталог `uploads/avatars` должен быть постоянным volume или внешним object storage.

## Основные страницы

- `/login` — вход;
- `/` — календарь группы;
- `/profile` — профиль и пароль;
- `/notifications` — все уведомления;
- `/admin` — обзор администратора;
- `/admin/students`, `/admin/events`, `/admin/schedule`, `/admin/tags` — управление данными.

## Основные API endpoints

- `GET /api/calendar?start=YYYY-MM-DD&days=14`
- `GET /api/cell/<student_id>/<YYYY-MM-DD>`
- `POST /api/cell/<student_id>/<date>/tag`
- `DELETE /api/cell/<student_id>/<date>/tag/<cell_tag_id>`
- `POST /api/cell/<student_id>/<date>/comment`
- `DELETE /api/comments/<comment_id>`
- `GET /api/schedule/<date>`
- `GET /api/notifications`
- `POST /api/notifications/<id>/read`
- `POST /api/notifications/read-all`
- `POST /api/admin/events`
- `PUT /api/admin/events/<id>`
- `DELETE /api/admin/events/<id>`
- `POST /api/admin/schedule`
- `DELETE /api/admin/schedule/<id>`

API требует активную сессию и CSRF-токен. Admin endpoints дополнительно проверяют роль. Студент не может изменить чужую ячейку; данные другой группы не выдаются.

## Тесты

```bash
pip install -r requirements-dev.txt
pytest -q
```

## Структура

```text
app/
├── __init__.py          # application factory
├── models.py            # SQLAlchemy-модели и связи
├── auth.py              # вход и выход
├── main.py              # календарь, профиль, уведомления
├── api.py               # JSON API и проверки прав
├── admin.py             # административный CRUD
├── forms.py             # WTForms
├── services.py          # seed, parsing, служебная логика
├── schedule_import.py   # загрузка и импорт расписания ГУАП
├── templates/           # Jinja2-шаблоны
└── static/              # CSS и JavaScript
migrations/              # Alembic-миграции
tests/                   # интеграционные тесты
compose.yaml             # Flask + PostgreSQL
Dockerfile
config.py
run.py
wsgi.py
```

## Идеи для следующей версии

- импорт iCal;
- несколько групп с отдельными администраторами;
- файлы к комментариям и object storage;
- realtime-уведомления через WebSocket/SSE;
- поиск, фильтры и экспорт посещаемости;
- аудит административных изменений и резервное копирование.
# guap_simple_it
