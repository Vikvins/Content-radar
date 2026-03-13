from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import Path

from app.models import ContentFormat, PostRecord

ALLOWED_FORMATS: set[ContentFormat] = {"post", "video", "carousel"}
REQUIRED_FIELDS = {"text", "likes", "comments", "shares", "views", "date", "format"}
MAX_UPLOAD_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB


class ParseError(ValueError):
    """Ошибка валидации или формата входного файла."""


def _parse_int(value: object, field_name: str) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ParseError(f"Поле '{field_name}' должно быть целым числом.") from exc

    if parsed < 0:
        raise ParseError(f"Поле '{field_name}' не может быть отрицательным.")
    return parsed


def _parse_date(value: object) -> datetime:
    if not isinstance(value, str):
        raise ParseError("Поле 'date' должно быть строкой в ISO-формате.")

    normalized = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ParseError("Поле 'date' должно быть в ISO-формате (например, 2026-03-11T12:00:00).") from exc


def _parse_format(value: object) -> ContentFormat:
    if not isinstance(value, str):
        raise ParseError("Поле 'format' должно быть строкой.")

    normalized = value.strip().lower()
    if normalized not in ALLOWED_FORMATS:
        raise ParseError("Поле 'format' должно быть одним из: post, video, carousel.")
    return normalized  # type: ignore[return-value]


def _normalize_record(raw: dict, default_competitor: str | None = None) -> PostRecord:
    missing = [field for field in REQUIRED_FIELDS if field not in raw]
    if missing:
        raise ParseError(f"Отсутствуют обязательные поля: {', '.join(sorted(missing))}.")

    text = str(raw.get("text", "")).strip()
    if not text:
        raise ParseError("Поле 'text' не должно быть пустым.")

    competitor = raw.get("competitor")
    normalized_competitor = str(competitor).strip() if competitor is not None else None
    if not normalized_competitor and default_competitor:
        normalized_competitor = default_competitor

    return PostRecord(
        text=text,
        likes=_parse_int(raw.get("likes"), "likes"),
        comments=_parse_int(raw.get("comments"), "comments"),
        shares=_parse_int(raw.get("shares"), "shares"),
        views=_parse_int(raw.get("views"), "views"),
        date=_parse_date(raw.get("date")),
        format=_parse_format(raw.get("format")),
        competitor=normalized_competitor,
    )


def _parse_json(content: bytes, default_competitor: str | None = None) -> list[PostRecord]:
    try:
        raw_data = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ParseError("Некорректный JSON-файл.") from exc

    if not isinstance(raw_data, list):
        raise ParseError("JSON-файл должен содержать массив постов.")

    return [_normalize_record(item, default_competitor) for item in raw_data if isinstance(item, dict)]


def _parse_csv(content: bytes, default_competitor: str | None = None) -> list[PostRecord]:
    try:
        decoded = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParseError("CSV-файл должен быть в кодировке UTF-8.") from exc

    reader = csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames:
        raise ParseError("CSV-файл не содержит заголовков.")

    return [_normalize_record(dict(row), default_competitor) for row in reader]


def parse_posts_file(filename: str, content: bytes, default_competitor: str | None = None) -> list[PostRecord]:
    """Парсит JSON/CSV файл с постами и валидирует структуру."""

    if len(content) > MAX_UPLOAD_SIZE_BYTES:
        raise ParseError("Файл слишком большой. Максимальный размер — 5MB.")

    ext = Path(filename).suffix.lower()
    if ext == ".json":
        posts = _parse_json(content, default_competitor)
    elif ext == ".csv":
        posts = _parse_csv(content, default_competitor)
    else:
        raise ParseError("Поддерживаются только файлы .json и .csv.")

    if not posts:
        raise ParseError("Файл не содержит валидных постов для анализа.")

    return posts
