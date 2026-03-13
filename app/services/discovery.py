from __future__ import annotations

import ipaddress
import json
import re
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta
from random import Random
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from app.models import PostRecord

FORMAT_SEQUENCE = ["post", "video", "carousel"]
TOPIC_TEMPLATES = [
    "Чеклист по контент-плану для {brand}",
    "Разбор рекламного кейса {brand}: что сработало",
    "Тренды публикаций в нише {brand}",
    "Как {brand} повышает вовлечённость в соцсетях",
    "Идеи для Reels и коротких видео в стиле {brand}",
    "Сравнение форматов постов для аудитории {brand}",
    "Лучшие рубрики контента у {brand}",
    "Гипотезы роста охвата для профиля {brand}",
]


class DiscoveryError(ValueError):
    """Ошибка обработки источника постов по ссылке."""


@dataclass
class NormalizedSource:
    source_url: str
    platform: str


@dataclass
class DiscoveryMeta:
    source_mode: str
    warning: str | None
    details: str
    source_url: str


def _normalize_source_url(raw_source_url: str) -> NormalizedSource:
    """Нормализует пользовательскую ссылку и определяет платформу."""

    source_url = (raw_source_url or "").strip()
    if not source_url:
        raise DiscoveryError("Введите корректную ссылку источника.")

    if "://" not in source_url:
        source_url = f"https://{source_url}"

    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"}:
        raise DiscoveryError("Поддерживаются только ссылки http/https.")
    if not parsed.hostname:
        raise DiscoveryError("Не удалось распознать домен в ссылке источника.")

    hostname = parsed.hostname.lower()
    path_parts = [part for part in parsed.path.split("/") if part]

    if hostname in {"instagram.com", "www.instagram.com"}:
        if not path_parts:
            raise DiscoveryError(
                "Для Instagram укажите ссылку на профиль или публикацию, например instagram.com/username."
            )
        normalized_path = "/" + "/".join(path_parts)
        return NormalizedSource(
            source_url=f"https://www.instagram.com{normalized_path}",
            platform="instagram",
        )

    if hostname in {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}:
        if not path_parts:
            raise DiscoveryError(
                "Для Telegram укажите ссылку на публичный канал, например t.me/channel_name."
            )

        if path_parts[0] == "s":
            if len(path_parts) < 2:
                raise DiscoveryError(
                    "Для Telegram используйте ссылку вида t.me/s/channel_name или t.me/channel_name."
                )
            channel_slug = path_parts[1]
        else:
            channel_slug = path_parts[0]

        if channel_slug in {"joinchat", "+"} or channel_slug.startswith("+"):
            raise DiscoveryError(
                "Приватные инвайт-ссылки Telegram не поддерживаются. Используйте публичный канал."
            )

        return NormalizedSource(
            source_url=f"https://t.me/s/{channel_slug}",
            platform="telegram",
        )

    normalized_path = parsed.path or "/"
    normalized_url = f"{parsed.scheme}://{hostname}{normalized_path}"
    return NormalizedSource(source_url=normalized_url, platform="generic")


def _infer_brand(source_url: str, competitor: str | None) -> str:
    if competitor and competitor.strip():
        return competitor.strip()

    parsed = urlparse(source_url)
    hostname = parsed.hostname or "demo-source"

    path_parts = [part for part in parsed.path.split("/") if part]
    if hostname.endswith("t.me") and path_parts:
        channel_name = path_parts[-1].replace("_", " ").replace("-", " ").strip()
        if channel_name:
            return channel_name.title()

    root = hostname.split(".")[0]
    normalized = root.replace("-", " ").replace("_", " ").strip()
    return normalized.title() if normalized else "Demo Brand"


def _is_unsafe_ip(ip_addr: ipaddress._BaseAddress) -> bool:
    return bool(
        ip_addr.is_private
        or ip_addr.is_loopback
        or ip_addr.is_link_local
        or ip_addr.is_multicast
        or ip_addr.is_reserved
        or ip_addr.is_unspecified
    )


def _assert_safe_public_url(source_url: str) -> None:
    """Блокирует SSRF-риски: локальные/приватные адреса и неподдерживаемые схемы."""

    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"}:
        raise DiscoveryError("Поддерживаются только ссылки http/https.")

    if not parsed.hostname:
        raise DiscoveryError("Некорректный URL источника.")

    hostname = parsed.hostname.lower()
    if hostname in {"localhost", "127.0.0.1", "::1"}:
        raise DiscoveryError("Локальные адреса не разрешены по соображениям безопасности.")

    try:
        direct_ip = ipaddress.ip_address(hostname)
    except ValueError:
        direct_ip = None

    if direct_ip is not None:
        if _is_unsafe_ip(direct_ip):
            raise DiscoveryError("Источник указывает на небезопасный IP-адрес и заблокирован.")
        return

    try:
        addr_info = socket.getaddrinfo(hostname, parsed.port or 443)
    except socket.gaierror:
        # В офлайн/ограниченных окружениях DNS может быть недоступен.
        # Не блокируем MVP-поток: дальше сработает demo fallback.
        return

    for _, _, _, _, sockaddr in addr_info:
        raw_ip = sockaddr[0]
        try:
            ip_addr = ipaddress.ip_address(raw_ip)
        except ValueError:
            continue

        if _is_unsafe_ip(ip_addr):
            raise DiscoveryError(
                "Источник указывает на небезопасный сетевой адрес и заблокирован."
            )


def _fetch_page_html(source_url: str) -> str:
    request = Request(
        url=source_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            )
        },
    )

    with urlopen(request, timeout=10) as response:  # nosec B310 - URL already validated
        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type and "application/json" not in content_type:
            raise DiscoveryError("Источник не вернул HTML/JSON страницу с открытыми данными.")
        return response.read().decode("utf-8", errors="ignore")


def _extract_json_candidate(html: str) -> dict | None:
    """Пытается достать JSON с постами из публичной страницы."""

    match = re.search(r"window\._sharedData\s*=\s*(\{.*?\});", html, flags=re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

    ld_json_matches = re.findall(
        r"<script[^>]*type=\"application/ld\+json\"[^>]*>(.*?)</script>",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    for raw_json in ld_json_matches:
        cleaned = raw_json.strip()
        if not cleaned:
            continue
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    return None


def _safe_int(value: object) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _parse_compact_number(raw: str) -> int:
    cleaned = (raw or "").strip().replace(" ", "")
    if not cleaned:
        return 0

    cleaned = cleaned.replace(",", ".")
    multiplier = 1
    if cleaned.endswith(("K", "k")):
        multiplier = 1_000
        cleaned = cleaned[:-1]
    elif cleaned.endswith(("M", "m")):
        multiplier = 1_000_000
        cleaned = cleaned[:-1]

    try:
        return max(int(float(cleaned) * multiplier), 0)
    except ValueError:
        digits = re.sub(r"\D", "", raw)
        return int(digits) if digits else 0


def _strip_html_tags(raw_html: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", raw_html)
    compact_spaces = re.sub(r"\s+", " ", without_tags)
    return compact_spaces.strip()


def _extract_instagram_like_posts(
    parsed_json: dict,
    brand: str,
    limit: int,
) -> list[PostRecord]:
    """Пытается извлечь список постов из структур, похожих на Instagram public JSON."""

    edges = []

    try:
        edges = (
            parsed_json["entry_data"]["ProfilePage"][0]["graphql"]["user"][
                "edge_owner_to_timeline_media"
            ]["edges"]
        )
    except (KeyError, IndexError, TypeError):
        edges = []

    if not edges and "mainEntity" in parsed_json:
        main_entity = parsed_json.get("mainEntity")
        if isinstance(main_entity, list):
            edges = [{"node": item} for item in main_entity if isinstance(item, dict)]
        elif isinstance(main_entity, dict):
            edges = [{"node": main_entity}]

    posts: list[PostRecord] = []
    for edge in edges[:limit]:
        node = edge.get("node", {}) if isinstance(edge, dict) else {}
        if not isinstance(node, dict):
            continue

        caption = ""
        edge_media_to_caption = node.get("edge_media_to_caption")
        if isinstance(edge_media_to_caption, dict):
            caption_edges = edge_media_to_caption.get("edges", [])
            if caption_edges and isinstance(caption_edges[0], dict):
                caption_node = caption_edges[0].get("node", {})
                if isinstance(caption_node, dict):
                    caption = str(caption_node.get("text", "")).strip()

        if not caption:
            caption = str(node.get("description") or node.get("name") or "").strip()
        if not caption:
            continue

        edge_liked_by = node.get("edge_liked_by")
        interaction_stat = node.get("interactionStatistic")
        edge_comments = node.get("edge_media_to_comment")

        likes = _safe_int(edge_liked_by.get("count") if isinstance(edge_liked_by, dict) else 0)
        if likes == 0 and isinstance(interaction_stat, dict):
            likes = _safe_int(interaction_stat.get("userInteractionCount"))

        comments = _safe_int(edge_comments.get("count") if isinstance(edge_comments, dict) else 0)
        shares = 0
        views = _safe_int(node.get("video_view_count") or node.get("commentCount") or 0)

        timestamp = node.get("taken_at_timestamp")
        if isinstance(timestamp, (int, float)):
            date = datetime.utcfromtimestamp(timestamp)
        else:
            date_raw = node.get("datePublished")
            try:
                date = datetime.fromisoformat(str(date_raw).replace("Z", "+00:00"))
            except ValueError:
                date = datetime.utcnow()

        is_video = bool(node.get("is_video"))
        format_name = "video" if is_video else "post"

        posts.append(
            PostRecord(
                text=caption,
                likes=likes,
                comments=comments,
                shares=shares,
                views=views,
                date=date,
                format=format_name,
                competitor=brand,
            )
        )

    return posts


def _build_url_with_before(source_url: str, before_id: int) -> str:
    parsed = urlparse(source_url)
    query_items = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key != "before"
    ]
    query_items.append(("before", str(before_id)))
    next_query = urlencode(query_items)

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            next_query,
            parsed.fragment,
        )
    )


def _extract_telegram_message_blocks(html: str) -> list[str]:
    chunks = html.split('<div class="tgme_widget_message_wrap')
    if len(chunks) <= 1:
        return []

    return [f'<div class="tgme_widget_message_wrap{chunk}' for chunk in chunks[1:]]


def _extract_telegram_post_id(block: str) -> int | None:
    post_id_match = re.search(r'data-post="[^"]+/(?P<post_id>\d+)"', block)
    if not post_id_match:
        return None
    return _safe_int(post_id_match.group("post_id")) or None


def _extract_telegram_text(block: str) -> str:
    text_match = re.search(
        r'<div class="tgme_widget_message_text[^"]*"[^>]*>(?P<text>.*?)</div>',
        block,
        flags=re.DOTALL,
    )
    if text_match:
        text = _strip_html_tags(text_match.group("text"))
        if text:
            return text

    # Часто встречаются медиа-посты без текстовой подписи.
    # Для MVP их тоже нужно учитывать, иначе искажается лимит и аналитика.
    return "[Пост без текста]"


def _extract_telegram_reactions_total(block: str) -> int:
    """Суммирует любые публично отображаемые реакции Telegram как likes для MVP."""

    container_match = re.search(
        r'<div class="[^"]*tgme_widget_message_reactions[^"]*"[^>]*>(?P<body>.*?)</div>',
        block,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not container_match:
        return 0

    container_html = container_match.group("body")
    reaction_spans = re.findall(
        r'<span class="[^"]*tgme_reaction[^"]*"[^>]*>.*?</span>',
        container_html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not reaction_spans:
        return 0

    total = 0
    for reaction_span in reaction_spans:
        reaction_text = _strip_html_tags(reaction_span)
        total += _parse_compact_number(reaction_text)

    return total


def _extract_telegram_comments_count(block: str) -> int:
    """Пытается получить счётчик комментариев/ответов из публичного блока поста."""

    replies_anchors = re.findall(
        r'<a[^>]*class="[^"]*(?:tgme_widget_message_repl|comment)[^"]*"[^>]*>.*?</a>',
        block,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not replies_anchors:
        return 0

    counts: list[int] = []
    for anchor in replies_anchors:
        data_count_match = re.search(r'data-count="(?P<count>\d+)"', anchor)
        if data_count_match:
            counts.append(_safe_int(data_count_match.group("count")))
            continue

        text_content = _strip_html_tags(anchor)
        count_match = re.search(r"(?P<count>\d[\d\s.,KkMm]*)", text_content)
        if count_match:
            counts.append(_parse_compact_number(count_match.group("count")))

    return max(counts) if counts else 0


def _extract_telegram_posts_from_html(
    html: str,
    brand: str,
    limit: int,
    seen_post_ids: set[int],
) -> tuple[list[PostRecord], int | None]:
    """Извлекает посты из HTML одной страницы Telegram и возвращает минимальный post_id."""

    blocks = _extract_telegram_message_blocks(html)
    if not blocks:
        return [], None

    posts: list[PostRecord] = []
    oldest_post_id: int | None = None

    for block in blocks:
        post_id = _extract_telegram_post_id(block)
        if post_id is not None:
            if oldest_post_id is None or post_id < oldest_post_id:
                oldest_post_id = post_id
            if post_id in seen_post_ids:
                continue

        date_match = re.search(
            r'<time[^>]*datetime="(?P<date>[^"]+)"[^>]*>.*?</time>',
            block,
            flags=re.DOTALL,
        )
        if not date_match:
            continue

        text = _extract_telegram_text(block)

        views_match = re.search(
            r'<span class="tgme_widget_message_views"[^>]*>(?P<views>[^<]*)</span>',
            block,
            flags=re.DOTALL,
        )
        views = _parse_compact_number(views_match.group("views") if views_match else "")

        reactions_total = _extract_telegram_reactions_total(block)
        comments_count = _extract_telegram_comments_count(block)

        date_raw = date_match.group("date")
        try:
            date = datetime.fromisoformat(date_raw.replace("Z", "+00:00"))
        except ValueError:
            date = datetime.utcnow()

        if "tgme_widget_message_grouped" in block:
            format_name = "carousel"
        elif "tgme_widget_message_video" in block or "tgme_widget_message_roundvideo" in block:
            format_name = "video"
        else:
            format_name = "post"

        posts.append(
            PostRecord(
                text=text,
                likes=reactions_total,
                comments=comments_count,
                shares=0,
                views=views,
                date=date,
                format=format_name,
                competitor=brand,
            )
        )

        if post_id is not None:
            seen_post_ids.add(post_id)

        if len(posts) >= limit:
            break

    return posts, oldest_post_id


def _fetch_telegram_posts_paginated(source_url: str, brand: str, limit: int) -> list[PostRecord]:
    """Собирает посты Telegram со страницы и из последующих страниц через ?before=<post_id>."""

    collected_posts: list[PostRecord] = []
    seen_post_ids: set[int] = set()

    next_url = source_url
    previous_oldest_post_id: int | None = None
    max_pages = 20

    for _ in range(max_pages):
        if len(collected_posts) >= limit:
            break

        html = _fetch_page_html(next_url)
        page_limit = limit - len(collected_posts)
        page_posts, oldest_post_id = _extract_telegram_posts_from_html(
            html=html,
            brand=brand,
            limit=page_limit,
            seen_post_ids=seen_post_ids,
        )

        if page_posts:
            collected_posts.extend(page_posts)

        if len(collected_posts) >= limit:
            break

        # Если не нашли идентификатор для следующей страницы, значит углубиться нельзя.
        if oldest_post_id is None:
            break

        # Защита от циклов/повторов при пагинации.
        if previous_oldest_post_id is not None and oldest_post_id >= previous_oldest_post_id:
            break

        previous_oldest_post_id = oldest_post_id
        next_url = _build_url_with_before(source_url, oldest_post_id)

    return collected_posts


def _build_telegram_public_details(posts: list[PostRecord]) -> tuple[str, str | None]:
    likes_nonzero = any(post.likes > 0 for post in posts)
    comments_nonzero = any(post.comments > 0 for post in posts)

    details = (
        "Посты извлечены из публичного канала Telegram. "
        "Лайки = сумма всех реакций поста. "
        "Комментарии = количество ответов, если счётчик доступен на публичной странице."
    )

    warning_parts: list[str] = []
    if not likes_nonzero:
        warning_parts.append(
            "На публичной странице канала не обнаружены счётчики реакций: Telegram может скрывать реакции, "
            "поэтому в поле «Лайки» возвращается 0."
        )
    if not comments_nonzero:
        warning_parts.append(
            "Счётчик комментариев/ответов недоступен в публичной HTML-разметке канала, "
            "поэтому в поле «Комментарии» возвращается 0."
        )

    warning = " ".join(warning_parts) if warning_parts else None
    return details, warning


def _generate_demo_posts(source_url: str, competitor: str | None, limit: int) -> list[PostRecord]:
    brand = _infer_brand(source_url, competitor)
    seed = sum(ord(ch) for ch in f"{source_url}:{brand}:{limit}")
    rng = Random(seed)

    base_time = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    posts: list[PostRecord] = []

    for idx in range(limit):
        content_format = FORMAT_SEQUENCE[idx % len(FORMAT_SEQUENCE)]
        template = TOPIC_TEMPLATES[idx % len(TOPIC_TEMPLATES)]
        text = template.format(brand=brand)

        likes = rng.randint(120, 920)
        comments = rng.randint(10, 140)
        shares = rng.randint(8, 110)
        views = rng.randint(1500, 14000)
        post_date = base_time - timedelta(hours=idx * 6)

        posts.append(
            PostRecord(
                text=text,
                likes=likes,
                comments=comments,
                shares=shares,
                views=views,
                date=post_date,
                format=content_format,
                competitor=brand,
            )
        )

    return posts


def _build_fallback_meta(source: NormalizedSource, details: str, warning: str) -> DiscoveryMeta:
    return DiscoveryMeta(
        source_mode="demo",
        warning=warning,
        details=details,
        source_url=source.source_url,
    )


def discover_posts(
    source_url: str,
    competitor: str | None = None,
    limit: int = 12,
) -> tuple[list[PostRecord], DiscoveryMeta]:
    """Пытается получить реальные открытые посты, иначе возвращает demo-набор с прозрачным предупреждением."""

    normalized_source = _normalize_source_url(source_url)
    _assert_safe_public_url(normalized_source.source_url)

    brand = _infer_brand(normalized_source.source_url, competitor)

    try:
        if normalized_source.platform == "telegram":
            posts = _fetch_telegram_posts_paginated(
                source_url=normalized_source.source_url,
                brand=brand,
                limit=limit,
            )
            if posts:
                details, warning = _build_telegram_public_details(posts)
                return posts, DiscoveryMeta(
                    source_mode="public",
                    warning=warning,
                    details=details,
                    source_url=normalized_source.source_url,
                )

        html = _fetch_page_html(normalized_source.source_url)

        parsed_json = _extract_json_candidate(html)
        if parsed_json is not None:
            posts = _extract_instagram_like_posts(parsed_json, brand=brand, limit=limit)
            if posts:
                return posts, DiscoveryMeta(
                    source_mode="public",
                    warning=None,
                    details="Посты извлечены из открытых данных страницы.",
                    source_url=normalized_source.source_url,
                )

        fallback_posts = _generate_demo_posts(normalized_source.source_url, competitor, limit)

        if normalized_source.platform == "instagram":
            warning = (
                "Instagram часто ограничивает выдачу метрик без авторизации/API. "
                "Показаны демонстрационные посты для MVP-режима."
            )
            details = "Открытые данные Instagram по ссылке не содержат полный список постов."
        elif normalized_source.platform == "telegram":
            warning = (
                "Не удалось извлечь посты из публичного канала Telegram по этой ссылке. "
                "Показаны демонстрационные посты для MVP-режима."
            )
            details = "Публичная страница не содержит ожидаемой HTML-структуры постов."
        else:
            warning = (
                "Открытые посты по ссылке недоступны (ограничение платформы/авторизации). "
                "Показаны демонстрационные посты для MVP-режима."
            )
            details = "Использован fallback-режим с демонстрационными данными."

        return fallback_posts, _build_fallback_meta(
            source=normalized_source,
            details=details,
            warning=warning,
        )
    except DiscoveryError:
        raise
    except Exception:
        fallback_posts = _generate_demo_posts(normalized_source.source_url, competitor, limit)
        return fallback_posts, _build_fallback_meta(
            source=normalized_source,
            details="Сетевой запрос или парсинг завершился ошибкой; включён demo fallback.",
            warning=(
                "Не удалось получить открытые посты по ссылке в текущем окружении. "
                "Показаны демонстрационные посты для MVP-режима."
            ),
        )
