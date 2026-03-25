from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.models import (
    AnalyzeRequest,
    ChannelComparisonDetails,
    ChannelTimeline,
    CompareChannelsRequest,
    CompareChannelsResponse,
    DemoLoadResponse,
    DiscoverPostItem,
    DiscoverPostsRequest,
    DiscoverPostsResponse,
    EngagementTimelinePoint,
    InsightResponse,
    RankingItem,
    SelectPostsRequest,
    UploadResponse,
    WinnerInfo,
)
from app.services.analyzer import InMemoryPostStore, analyze_posts, build_insights, get_engagement_formula
from app.services.discovery import DiscoveryError, discover_posts
from app.services.parsers import ParseError, parse_posts_file

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
DEMO_FILE = DATA_DIR / "demo_posts.json"
STATIC_APP_JS = BASE_DIR / "static" / "app.js"
STATIC_STYLES_CSS = BASE_DIR / "static" / "styles.css"

FORMAT_LABELS_RU = {
    "post": "«Пост»",
    "video": "«Видео»",
    "carousel": "«Карусель»",
}


def _resolve_asset_version(file_path: Path) -> str:
    """Возвращает версию ассета по времени изменения для cache-busting."""

    try:
        return str(int(file_path.stat().st_mtime))
    except OSError:
        return "1"


JS_VERSION = _resolve_asset_version(STATIC_APP_JS)
CSS_VERSION = _resolve_asset_version(STATIC_STYLES_CSS)

app = FastAPI(
    title="Content Radar MVP",
    description="MVP инструмент для анализа контента конкурентов",
    version="1.3.1",
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
store = InMemoryPostStore()


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    """Главная страница MVP."""

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "js_version": JS_VERSION,
            "css_version": CSS_VERSION,
        },
    )


@app.get("/health")
def health() -> dict:
    """Проверка доступности сервиса."""

    return {"status": "ok"}


@app.post("/upload_posts", response_model=UploadResponse)
async def upload_posts(
    file: UploadFile = File(...),
    competitor: str | None = Form(default=None),
) -> UploadResponse:
    """Загружает JSON/CSV файл постов и сохраняет в in-memory хранилище."""

    if not file.filename:
        raise HTTPException(status_code=400, detail="Имя файла не передано.")

    content = await file.read()
    try:
        parsed_posts = parse_posts_file(
            filename=file.filename,
            content=content,
            default_competitor=competitor.strip() if competitor else None,
        )
    except ParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    store.replace_posts(parsed_posts)
    return UploadResponse(message="Файл успешно загружен", posts_count=len(parsed_posts))


@app.post("/discover_posts", response_model=DiscoverPostsResponse)
def discover_posts_endpoint(payload: DiscoverPostsRequest) -> DiscoverPostsResponse:
    """Получает посты из открытых данных страницы или включает честный demo fallback."""

    try:
        discovered_posts, discovery_meta = discover_posts(
            source_url=payload.source_url,
            competitor=payload.competitor,
            limit=payload.limit,
        )
    except DiscoveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    store.set_discovered_posts(discovered_posts)

    return DiscoverPostsResponse(
        message="Доступные посты получены. Выберите нужные, сохраните и запустите анализ.",
        source_url=discovery_meta.source_url,
        source_mode=discovery_meta.source_mode,
        source_details=discovery_meta.details,
        warning=discovery_meta.warning,
        posts_count=len(discovered_posts),
        posts=[
            DiscoverPostItem(
                discovered_id=idx,
                text=post.text,
                format=post.format,
                date=post.date,
                competitor=post.competitor,
                likes=post.likes,
                comments=post.comments,
                shares=post.shares,
                views=post.views,
            )
            for idx, post in enumerate(discovered_posts)
        ],
    )


@app.post("/select_posts", response_model=UploadResponse)
def select_posts(payload: SelectPostsRequest) -> UploadResponse:
    """Сохраняет выбранные пользователем посты как текущий набор для анализа."""

    if not payload.selected_ids:
        raise HTTPException(status_code=400, detail="Выберите хотя бы один пост для анализа.")

    selected_posts = store.select_discovered_posts(payload.selected_ids)
    if not selected_posts:
        raise HTTPException(status_code=400, detail="Не удалось выбрать посты. Проверьте идентификаторы.")

    return UploadResponse(
        message="Сохранено постов для анализа",
        posts_count=len(selected_posts),
    )


@app.post("/analyze_content")
def analyze_content(payload: AnalyzeRequest) -> dict:
    """Выполняет анализ загруженных постов по указанным конкурентам."""

    posts = store.get_posts()
    if not posts:
        raise HTTPException(
            status_code=400,
            detail=(
                "Нет данных. Загрузите файл или используйте режим получения постов по ссылке."
            ),
        )

    analysis = analyze_posts(posts=posts, competitors=payload.competitors)
    store.set_last_analysis(analysis)

    return {
        "summary": analysis.summary,
        "posts": analysis.posts,
        "top_posts": analysis.top_posts,
        "top_topics": analysis.top_topics,
        "best_time": analysis.best_time,
        "top_formats": analysis.top_formats,
        "recommendations": analysis.recommendations,
        "engagement_formula": analysis.engagement_formula,
    }


def _normalize_channel_name(name: str) -> str:
    cleaned = (name or "").strip()
    return cleaned if cleaned else "Без названия"


def _build_best_time_label(best_time: dict) -> str:
    best_hour = best_time.get("best_hour")
    if best_hour is not None:
        return f"{int(best_hour):02d}:00"

    best_bucket = best_time.get("best_bucket")
    if best_bucket:
        return str(best_bucket)

    return "—"


def _format_label_ru(format_name: str) -> str:
    return FORMAT_LABELS_RU.get(format_name, f"«{format_name}»")


def _strong_side_label(top_formats: list[str], top_topics: list[str], best_time_label: str) -> str:
    lead_format = _format_label_ru(top_formats[0]) if top_formats else None
    lead_topic = top_topics[0] if top_topics else None

    if lead_format and lead_topic and best_time_label != "—":
        return f"Связка: {lead_format} + тема «{lead_topic}» + слот {best_time_label}"
    if lead_format and lead_topic:
        return f"Связка: {lead_format} + тема «{lead_topic}»"
    if lead_format and best_time_label != "—":
        return f"Сильный формат и тайминг: {lead_format} в {best_time_label}"
    if lead_topic and best_time_label != "—":
        return f"Сильная тема «{lead_topic}» в слоте {best_time_label}"
    if lead_format:
        return f"Сильный формат: {lead_format}"
    if lead_topic:
        return f"Сильная тема: «{lead_topic}»"
    if best_time_label != "—":
        return f"Стабильный отклик в слоте {best_time_label}"
    return "Ровная базовая активность"


def _build_weak_side_label(item: dict, leader: dict) -> str:
    if item["name"] == leader["name"]:
        return "—"

    weaknesses: list[str] = []

    leader_score = float(leader["avg_engagement"])
    item_score = float(item["avg_engagement"])
    if leader_score > 0:
        lag_pct = round(max(0.0, ((leader_score - item_score) / leader_score) * 100), 1)
        if lag_pct >= 25:
            weaknesses.append(f"Существенное отставание по средней вовлечённости: −{lag_pct}%")
        elif lag_pct > 0:
            weaknesses.append(f"Уступает лидеру по средней вовлечённости: −{lag_pct}%")

    leader_format = leader["top_formats"][0] if leader["top_formats"] else None
    item_format = item["top_formats"][0] if item["top_formats"] else None
    if leader_format and item_format and leader_format != item_format:
        weaknesses.append(
            f"Главный формат { _format_label_ru(item_format) } даёт слабее отклик, чем лидерский { _format_label_ru(leader_format) }"
        )
    elif leader_format and not item_format:
        weaknesses.append("Нет выраженного формата-лидера в контенте")

    leader_time = leader.get("best_time")
    item_time = item.get("best_time")
    if leader_time and item_time and leader_time != "—" and item_time != "—" and leader_time != item_time:
        weaknesses.append(f"Публикации уходят из самого результативного слота ({leader_time})")
    elif leader_time and leader_time != "—" and (not item_time or item_time == "—"):
        weaknesses.append("Нет устойчивого лучшего времени публикации")

    leader_topic = leader["top_topics"][0] if leader["top_topics"] else None
    item_topic = item["top_topics"][0] if item["top_topics"] else None
    if leader_topic and not item_topic:
        weaknesses.append("Темы канала размыты: нет выраженной темы-драйвера вовлечённости")
    elif leader_topic and item_topic and leader_topic != item_topic:
        weaknesses.append(
            f"Тема-лидер канала «{item_topic}» пока уступает по отклику теме лидера «{leader_topic}»"
        )

    if not weaknesses:
        return "Точки роста минимальны: нужен точечный A/B-тест формата и времени"

    return "; ".join(weaknesses[:2])


def _lead_value(values: list[str], fallback: str = "—") -> str:
    return values[0] if values else fallback


@app.post("/compare_channels", response_model=CompareChannelsResponse)
def compare_channels(payload: CompareChannelsRequest) -> CompareChannelsResponse:
    """Сравнивает ваш канал с конкурентами и возвращает приоритетные действия."""

    my_channel_name = _normalize_channel_name(payload.my_channel_name)
    my_channel_url = payload.my_channel_url.strip()
    if not my_channel_url:
        raise HTTPException(status_code=400, detail="Укажите ссылку вашего канала.")

    channels = [
        {
            "name": my_channel_name,
            "url": my_channel_url,
            "is_my_channel": True,
        }
    ]

    for competitor in payload.competitors:
        competitor_name = _normalize_channel_name(competitor.name)
        competitor_url = competitor.url.strip()
        if not competitor_url:
            raise HTTPException(
                status_code=400,
                detail=f"У конкурента «{competitor_name}» не заполнена ссылка.",
            )

        channels.append(
            {
                "name": competitor_name,
                "url": competitor_url,
                "is_my_channel": False,
            }
        )

    channel_results: list[dict] = []
    warnings: list[str] = []

    for channel in channels:
        try:
            posts, discovery_meta = discover_posts(
                source_url=channel["url"],
                competitor=channel["name"],
                limit=payload.posts_limit,
            )
        except DiscoveryError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Ошибка канала «{channel['name']}»: {exc}",
            ) from exc

        analysis = analyze_posts(posts=posts)

        best_time_label = _build_best_time_label(analysis.best_time)
        top_topics = [item["topic"] for item in analysis.top_topics[:3]]
        top_formats = [item["format"] for item in analysis.top_formats[:2]]

        avg_engagement = float(analysis.summary.get("avg_engagement", 0.0))
        timeline_points = [
            {
                "date": item["date"],
                "engagement": float(item["engagement_score"]),
            }
            for item in analysis.posts
        ]
        timeline_points.sort(key=lambda point: point["date"])

        channel_results.append(
            {
                "name": channel["name"],
                "is_my_channel": channel["is_my_channel"],
                "avg_engagement": avg_engagement,
                "top_topics": top_topics,
                "top_formats": top_formats,
                "best_time": best_time_label,
                "source_url": discovery_meta.source_url,
                "source_mode": discovery_meta.source_mode,
                "warning": discovery_meta.warning,
                "posts_count": int(analysis.summary.get("total_posts", len(posts))),
                "timeline_points": timeline_points,
                "strong_side": _strong_side_label(top_formats, top_topics, best_time_label),
            }
        )

        if discovery_meta.warning:
            warnings.append(f"{channel['name']}: {discovery_meta.warning}")

    ranking_source = sorted(channel_results, key=lambda item: item["avg_engagement"], reverse=True)
    if not ranking_source:
        raise HTTPException(status_code=400, detail="Не удалось получить данные для сравнения каналов.")

    leader = ranking_source[0]
    leader_score = leader["avg_engagement"]

    ranking: list[RankingItem] = []
    for index, item in enumerate(ranking_source, start=1):
        if leader_score <= 0:
            gap_pct = 0.0
        else:
            gap_pct = round(((item["avg_engagement"] - leader_score) / leader_score) * 100, 1)

        ranking.append(
            RankingItem(
                rank=index,
                name=item["name"],
                avg_engagement=round(item["avg_engagement"], 2),
                gap_vs_leader_pct=gap_pct,
                strong_side=item["strong_side"],
                weak_side=_build_weak_side_label(item=item, leader=leader),
            )
        )

    leader_topic = _lead_value(leader["top_topics"], "чёткая тематика")
    leader_format_raw = _lead_value(leader["top_formats"], "post")
    leader_format = _format_label_ru(leader_format_raw)
    winner_reason = (
        f"Лидер усиливает формат {leader_format} и стабильно публикует в слот «{leader['best_time']}», "
        f"где лучше всего работает тема «{leader_topic}»."
    )

    winner = WinnerInfo(
        name=leader["name"],
        avg_engagement=round(leader_score, 2),
        reason=winner_reason,
    )

    my_channel = next((item for item in ranking_source if item["is_my_channel"]), None)
    if my_channel is None:
        raise HTTPException(status_code=500, detail="Не найден ваш канал в итогах сравнения.")

    my_gap_pct = 0.0
    if leader_score > 0:
        my_gap_pct = round(((my_channel["avg_engagement"] - leader_score) / leader_score) * 100, 1)

    my_lag_abs = abs(my_gap_pct) if my_gap_pct < 0 else 0.0
    my_topic = _lead_value(my_channel["top_topics"])
    my_format_raw = _lead_value(my_channel["top_formats"], "post")
    my_format = _format_label_ru(my_format_raw)

    insights: list[str] = [
        f"Лидер рейтинга — «{leader['name']}» со средней вовлечённостью {round(leader_score, 2)}.",
        (
            f"Ваш канал «{my_channel['name']}» отстаёт от лидера на {my_lag_abs}%: "
            f"лучший формат у вас {my_format}, у лидера — {leader_format}."
            if my_gap_pct < 0
            else f"Ваш канал «{my_channel['name']}» удерживает лидерство с отрывом {my_gap_pct}%."
        ),
        (
            f"Ключевая тема лидера — «{leader_topic}», а в вашем канале сильнее тема «{my_topic}»."
            if my_topic != leader_topic
            else f"Вы и лидер совпадаете по теме «{leader_topic}», значит резерв роста в подаче и формате контента."
        ),
    ]

    if my_channel["best_time"] != leader["best_time"] and leader["best_time"] != "—":
        insights.append(
            f"Лучший слот лидера — {leader['best_time']}, у вашего канала — {my_channel['best_time']}. "
            "Разница во времени публикации влияет на отставание."
        )

    actions: list[str] = []
    if my_gap_pct < 0:
        actions.append(
            f"Цель на 14 дней: сократить отставание от лидера с {my_lag_abs}% до {max(my_lag_abs - 10, 0):.1f}% "
            "через точечный тест новых форматов и времени публикаций."
        )

    if my_format_raw != leader_format_raw:
        actions.append(
            f"Добавьте 4 публикации в формате {leader_format} в ближайшие 2 недели и сравните среднюю вовлечённость "
            f"с текущим форматом {my_format}."
        )

    if my_topic != leader_topic and leader_topic != "—":
        actions.append(
            f"Запустите мини-серию из 3 постов по теме «{leader_topic}» с разной подачей (экспертный разбор, чеклист, кейс) "
            "и оставьте в плане только формат с максимальным откликом."
        )

    if my_channel["best_time"] != leader["best_time"] and leader["best_time"] != "—":
        actions.append(
            f"Сдвиньте 50% ключевых постов в слот «{leader['best_time']}» на 7 дней и замерьте прирост к текущему слоту "
            f"«{my_channel['best_time']}»."
        )

    if len(ranking_source) >= 3:
        mid_channel = ranking_source[1]
        mid_format = _format_label_ru(_lead_value(mid_channel["top_formats"], "post"))
        actions.append(
            f"Для позиционирования между лидером и «{mid_channel['name']}» используйте связку: "
            f"тема «{_lead_value(mid_channel['top_topics'])}» + формат {mid_format} "
            "в одном тестовом цикле публикаций."
        )

    if not actions:
        actions.append("Сохраните текущую стратегию и масштабируйте лучшие форматы на большее число публикаций.")

    channel_details = [
        ChannelComparisonDetails(
            name=item["name"],
            source_url=item["source_url"],
            source_mode=item["source_mode"],
            warning=item["warning"],
            posts_count=item["posts_count"],
            avg_engagement=round(item["avg_engagement"], 2),
            top_topics=item["top_topics"],
            top_formats=item["top_formats"],
            best_time=item["best_time"],
        )
        for item in ranking_source
    ]

    timelines = [
        ChannelTimeline(
            name=item["name"],
            points=[
                EngagementTimelinePoint(
                    date=point["date"],
                    engagement=round(point["engagement"], 2),
                )
                for point in item["timeline_points"]
            ],
        )
        for item in ranking_source
    ]

    is_demo_mode = all(item["source_mode"] == "demo" for item in channel_results)

    return CompareChannelsResponse(
        message="Сравнение каналов выполнено. Ниже победитель, рейтинг и действия для роста.",
        analyzed_at=datetime.utcnow().isoformat() + "Z",
        posts_limit=payload.posts_limit,
        my_channel_name=my_channel_name,
        winner=winner,
        ranking=ranking,
        channel_details=channel_details,
        timelines=timelines,
        insights=insights[:5],
        actions=actions[:6],
        warnings=warnings,
        is_demo_mode=is_demo_mode,
        engagement_formula=get_engagement_formula(),
    )


@app.get("/insights", response_model=InsightResponse)
def insights() -> InsightResponse:
    """Возвращает рекомендации маркетологу на основе последнего анализа."""

    analysis = store.get_last_analysis()
    if analysis is None:
        posts = store.get_posts()
        if not posts:
            raise HTTPException(
                status_code=400,
                detail="Нет данных для рекомендаций. Загрузите или выберите посты и выполните анализ.",
            )
        analysis = analyze_posts(posts=posts)
        store.set_last_analysis(analysis)

    insights_payload = build_insights(analysis)
    return InsightResponse(
        recommendations=insights_payload["recommendations"],
        engagement_formula=insights_payload["engagement_formula"],
        summary=insights_payload["summary"],
    )


@app.post("/load_demo", response_model=DemoLoadResponse)
def load_demo() -> DemoLoadResponse:
    """Загружает демоданные и синхронизирует их с таблицей доступных постов."""

    if not DEMO_FILE.exists():
        raise HTTPException(status_code=404, detail="Демо-файл не найден.")

    content = DEMO_FILE.read_bytes()
    try:
        posts = parse_posts_file(filename=DEMO_FILE.name, content=content)
    except ParseError as exc:
        raise HTTPException(status_code=500, detail=f"Ошибка демоданных: {exc}") from exc

    store.replace_posts(posts)
    store.set_discovered_posts(posts)

    return DemoLoadResponse(
        message="Демоданные успешно загружены",
        posts_count=len(posts),
        posts=[
            DiscoverPostItem(
                discovered_id=idx,
                text=post.text,
                format=post.format,
                date=post.date,
                competitor=post.competitor,
                likes=post.likes,
                comments=post.comments,
                shares=post.shares,
                views=post.views,
            )
            for idx, post in enumerate(posts)
        ],
    )
