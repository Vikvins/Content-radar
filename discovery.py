from __future__ import annotations

import ipaddress
import json
import math
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

LEADER_TOPIC_TEMPLATES = [
    "Кейс роста ROMI для {brand}: что дало максимум продаж",
    "Разбор воронки лидера ниши {brand} по шагам",
    "3 сценария прогрева аудитории от {brand}",
    "Контент-спринт {brand}: как поднять вовлечённость за 7 дней",
    "Сильный оффер недели у {brand}: почему он конвертит",
    "Видео-разбор рекламной связки {brand} с цифрами",
    "Антикризисный план публикаций {brand} на месяц",
    "Ошибки конкурентов и как {brand} забирает внимание аудитории",
]

MY_TOPIC_TEMPLATES = [
    "Базовый контент-план для {brand}: где теряется охват",
    "Как {brand} оформляет экспертный пост для Telegram",
    "Разбор комментариев аудитории {brand}: ключевые вопросы",
    "Что протестировать в рубриках {brand} на этой неделе",
    "Шаблон сторителлинга для постов {brand}",
    "Как {brand} усилить CTA в публикациях",
    "Контент без перегруза: формат коротких советов для {brand}",
    "Пошаговый план улучшения ER канала {brand}",
]

CHALLENGER_TOPIC_TEMPLATES = [
    "Быстрые акции и промо-форматы в стиле {brand}",
    "Контент с лид-магнитом для {brand}: что заходит лучше",
    "Как {brand} тестирует карусели против обычных постов",
    "Разбор UGC-механики у {brand}",
    "Экспресс-гайд: рост охвата у {brand} через коллаборации",
    "Что публиковать в середине недели: подход {brand}",
    "Реактивация аудитории {brand} без скидочного демпинга",
    "Формула сильного промо-поста у {brand}",
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


@dataclass
class DemoProfile:
    name: str
    score_multiplier: float
    trend_strength: float
    views_multiplier: float
    format_cycle: list[str]
    preferred_hours: list[int]
    topic_templates: list[str]
    likes_range: tuple[int, int]
    comments_range: tuple[int, int]
    shares_range: tuple[int, int]
    views_range: tuple[int, int]


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


def _resolve_demo_profile(source_url: str, brand: str) -> DemoProfile:
    """Формирует профиль демосценария: лидер, свой канал, сильный конкурент или базовый."""

    normalized = f"{source_url} {brand}".lower()

    if any(marker in normalized for marker in ["leader", "лидер", "top", "best", "a_leader", "limecontent"]):
        return DemoProfile(
            name="leader",
            score_multiplier=1.75,
            trend_strength=1.3,
            views_multiplier=1.35,
            format_cycle=["video", "carousel", "video", "post", "video", "carousel"],
            preferred_hours=[11, 13, 18, 20, 21],
            topic_templates=LEADER_TOPIC_TEMPLATES,
            likes_range=(260, 620),
            comments_range=(35, 140),
            shares_range=(24, 120),
            views_range=(6400, 16500),
        )

    if any(
        marker in normalized
        for marker in [
            "my_brand",
            "my brand",
            "мой",
            "ваш",
            "my_channel",
            "marketpulse",
            "маркетпульс",
            "brand",
        ]
    ):
        return DemoProfile(
            name="my",
            score_multiplier=0.92,
            trend_strength=0.95,
            views_multiplier=0.9,
            format_cycle=["post", "post", "video", "post", "carousel"],
            preferred_hours=[9, 10, 12, 17],
            topic_templates=MY_TOPIC_TEMPLATES,
            likes_range=(110, 310),
            comments_range=(9, 45),
            shares_range=(6, 38),
            views_range=(2100, 7600),
        )

    if any(
        marker in normalized
        for marker in ["competitor-b", "competitor_b", "конкурент b", "challenger", "trafficlab", "трафиклаб"]
    ):
        return DemoProfile(
            name="challenger",
            score_multiplier=1.22,
            trend_strength=1.08,
            views_multiplier=1.08,
            format_cycle=["carousel", "post", "carousel", "video", "post"],
            preferred_hours=[12, 14, 16, 19],
            topic_templates=CHALLENGER_TOPIC_TEMPLATES,
            likes_range=(170, 430),
            comments_range=(14, 68),
            shares_range=(12, 66),
            views_range=(3800, 11200),
        )

    return DemoProfile(
        name="base",
        score_multiplier=1.0,
        trend_strength=1.0,
        views_multiplier=1.0,
        format_cycle=FORMAT_SEQUENCE,
        preferred_hours=[10, 13, 18],
        topic_templates=TOPIC_TEMPLATES,
        likes_range=(130, 360),
        comments_range=(10, 50),
        shares_range=(8, 45),
        views_range=(2600, 8900),
    )


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

        if oldest_post_id is None:
            break

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


def _build_volatility_profile(profile_name: str) -> tuple[list[float], float]:
    """Возвращает детерминированный паттерн волн для реалистичной динамики постов."""

    if profile_name == "leader":
        return [1.08, 0.94, 1.16, 0.83, 1.05, 0.9, 1.18, 0.88], 0.25
    if profile_name == "my":
        return [0.96, 1.12, 0.84, 1.18, 0.91, 1.04, 0.8, 1.1], 1.1
    if profile_name == "challenger":
        return [1.03, 0.86, 1.15, 0.92, 1.09, 0.78, 1.2, 0.89], 0.55
    return [1.0, 0.9, 1.08, 0.87, 1.05, 0.95, 1.12, 0.91], 0.7


def _generate_demo_posts(source_url: str, competitor: str | None, limit: int) -> list[PostRecord]:
    brand = _infer_brand(source_url, competitor)
    profile = _resolve_demo_profile(source_url=source_url, brand=brand)

    seed = sum(ord(ch) for ch in f"{source_url}:{brand}:{limit}:{profile.name}")
    rng = Random(seed)

    base_time = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    posts: list[PostRecord] = []

    volatility_pattern, phase_shift = _build_volatility_profile(profile.name)

    for idx in range(limit):
        cycle = profile.format_cycle if profile.format_cycle else FORMAT_SEQUENCE
        content_format = cycle[idx % len(cycle)]

        template_pool = profile.topic_templates if profile.topic_templates else TOPIC_TEMPLATES
        template = template_pool[idx % len(template_pool)]

        if profile.name == "leader":
            text = f"{template.format(brand=brand)} · Практика лидера #{idx + 1}"
        elif profile.name == "my":
            text = f"{template.format(brand=brand)} · Тест гипотез #{idx + 1}"
        elif profile.name == "challenger":
            text = f"{template.format(brand=brand)} · Быстрый эксперимент #{idx + 1}"
        else:
            text = template.format(brand=brand)

        progress = idx / max(limit - 1, 1)

        baseline_trend = 0.88 + (progress * 0.34 * profile.trend_strength)
        wave = 1 + (0.22 * math.sin((idx + 1) * 1.15 + phase_shift))
        random_noise = rng.uniform(0.82, 1.18)
        patterned_volatility = volatility_pattern[idx % len(volatility_pattern)]

        combined_factor = baseline_trend * wave * random_noise * patterned_volatility

        # Вставляем контролируемые просадки/всплески, чтобы линии не были ровными и
        # даже лидер имел отдельные слабые публикации.
        if profile.name == "leader" and idx % 5 == 2:
            combined_factor *= 0.72
        if profile.name == "my":
            if idx % 4 == 1:
                combined_factor *= 1.12
            elif idx % 4 == 3:
                combined_factor *= 0.79
        if profile.name == "challenger":
            if idx % 6 == 2:
                combined_factor *= 1.16
            elif idx % 6 == 5:
                combined_factor *= 0.74

        # Детеминированные микро-события добавляют «живой» вид графику.
        if rng.random() < 0.17:
            combined_factor *= rng.uniform(0.76, 0.9)
        elif rng.random() < 0.17:
            combined_factor *= rng.uniform(1.08, 1.24)

        combined_factor = max(combined_factor, 0.42)

        likes_base = rng.randint(*profile.likes_range)
        comments_base = rng.randint(*profile.comments_range)
        shares_base = rng.randint(*profile.shares_range)
        views_base = rng.randint(*profile.views_range)

        if profile.name == "leader":
            comments_boost = 1.06 + (0.12 if content_format == "video" else 0.0)
            shares_boost = 1.04 + (0.1 if content_format == "carousel" else 0.0)
        elif profile.name == "my":
            comments_boost = 0.9 + (0.08 if content_format == "post" else 0.0)
            shares_boost = 0.83 + (0.18 if content_format == "carousel" else 0.0)
        elif profile.name == "challenger":
            comments_boost = 0.96 + (0.14 if content_format == "carousel" else 0.0)
            shares_boost = 1.0 + (0.08 if content_format == "video" else 0.0)
        else:
            comments_boost = 1.0
            shares_boost = 1.0

        likes = int(round(likes_base * profile.score_multiplier * combined_factor))
        comments = int(round(comments_base * profile.score_multiplier * combined_factor * comments_boost))
        shares = int(round(shares_base * profile.score_multiplier * combined_factor * shares_boost))
        views = int(round(views_base * profile.score_multiplier * profile.views_multiplier * combined_factor))

        post_date = base_time - timedelta(hours=(limit - idx - 1) * 6)
        preferred_hour = profile.preferred_hours[idx % len(profile.preferred_hours)]
        hour_jitter = rng.choice([-1, 0, 0, 1])
        adjusted_hour = min(23, max(0, preferred_hour + hour_jitter))
        post_date = post_date.replace(hour=adjusted_hour)

        posts.append(
            PostRecord(
                text=text,
                likes=max(likes, 0),
                comments=max(comments, 0),
                shares=max(shares, 0),
                views=max(views, 0),
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
