#!/usr/bin/env python3
"""Import students through the service's authenticated HTTP API."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from http.cookiejar import CookieJar
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener


class CsrfTokenParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.form_token: str | None = None
        self.meta_token: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "input" and values.get("name") == "csrf_token":
            self.form_token = values.get("value")
        if tag == "meta" and values.get("name") == "csrf-token":
            self.meta_token = values.get("content")


def _tokens(html: str) -> CsrfTokenParser:
    parser = CsrfTokenParser()
    parser.feed(html)
    return parser


def _read_response(response: Any) -> str:
    return response.read().decode(response.headers.get_content_charset() or "utf-8")


def import_students(
    students: list[dict[str, Any]],
    base_url: str,
    admin_login: str,
    admin_password: str,
    timeout: float = 30,
) -> dict[str, Any]:
    """Log in as an administrator and send a list to the bulk import endpoint."""
    if not isinstance(students, list):
        raise ValueError("students должен быть списком")

    base_url = base_url.rstrip("/") + "/"
    parsed_url = urlparse(base_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError("Адрес сервиса должен начинаться с http:// или https://")

    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    login_url = urljoin(base_url, "login")
    with opener.open(login_url, timeout=timeout) as response:
        login_page = _read_response(response)
    form_token = _tokens(login_page).form_token
    if not form_token:
        raise RuntimeError("Не удалось получить CSRF-токен формы входа")

    login_data = urlencode({
        "login": admin_login,
        "password": admin_password,
        "remember": "y",
        "csrf_token": form_token,
    }).encode("utf-8")
    request = Request(login_url, data=login_data, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    with opener.open(request, timeout=timeout) as response:
        page = _read_response(response)
        final_path = urlparse(response.geturl()).path
    if final_path.rstrip("/") == "/login":
        raise RuntimeError("Не удалось войти: проверьте логин и пароль администратора")

    api_token = _tokens(page).meta_token
    if not api_token:
        with opener.open(base_url, timeout=timeout) as response:
            api_token = _tokens(_read_response(response)).meta_token
    if not api_token:
        raise RuntimeError("Не удалось получить CSRF-токен API")

    body = json.dumps(students, ensure_ascii=False).encode("utf-8")
    request = Request(urljoin(base_url, "api/admin/students/import"), data=body, method="POST")
    request.add_header("Content-Type", "application/json; charset=utf-8")
    request.add_header("X-CSRFToken", api_token)
    try:
        with opener.open(request, timeout=timeout) as response:
            result = json.loads(_read_response(response))
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(details).get("error", details)
        except json.JSONDecodeError:
            message = details
        raise RuntimeError(f"API вернул HTTP {error.code}: {message}") from error
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Импорт студентов через API Student Dashboard")
    parser.add_argument("json_file", type=Path, help="JSON-файл с массивом студентов")
    parser.add_argument("--url", default=os.getenv("SERVICE_URL", "http://127.0.0.1:5000"), help="адрес сервиса")
    parser.add_argument("--admin-login", default=os.getenv("ADMIN_LOGIN", "admin"), help="логин администратора")
    parser.add_argument("--admin-password", default=os.getenv("ADMIN_PASSWORD"), help="пароль (безопаснее задать через ADMIN_PASSWORD)")
    parser.add_argument("--timeout", type=float, default=30, help="таймаут HTTP-запросов в секундах")
    args = parser.parse_args()

    try:
        students = json.loads(args.json_file.read_text(encoding="utf-8-sig"))
        if not isinstance(students, list):
            raise ValueError("Корневое значение JSON-файла должно быть массивом")
        password = args.admin_password or getpass.getpass("Пароль администратора: ")
        result = import_students(students, args.url, args.admin_login, password, args.timeout)
    except (OSError, ValueError, RuntimeError, HTTPError, URLError, json.JSONDecodeError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1

    totals = result.get("totals", {})
    print(f"Создано: {totals.get('created', 0)}; пропущено: {totals.get('skipped', 0)}; ошибок: {totals.get('errors', 0)}")
    for item in result.get("created", []):
        print(f"  + строка {item['index'] + 1}: {item['surname']} {item['name']} — логин {item['login']}")
    for item in result.get("skipped", []):
        print(f"  = строка {item['index'] + 1}: {item['reason']} (логин {item['login']})")
    for item in result.get("errors", []):
        print(f"  ! строка {item['index'] + 1}: {item['error']}", file=sys.stderr)
    return 2 if result.get("errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
