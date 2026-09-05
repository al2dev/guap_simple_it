FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/instance /app/uploads/avatars /app/uploads/materials && chown -R app:app /app
USER app

EXPOSE 5000
CMD ["sh", "-c", "flask --app wsgi:app db upgrade && flask --app wsgi:app init-data && exec gunicorn --bind 0.0.0.0:5000 --workers 1 --threads 100 --access-logfile - wsgi:app"]
