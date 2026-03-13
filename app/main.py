from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.models import (
    AnalyzeRequest,
    DiscoverPostItem,
    DiscoverPostsRequest,
    DiscoverPostsResponse,
    InsightResponse,
    SelectPostsRequest,
    UploadResponse,
)
from app.services.analyzer import InMemoryPostStore, analyze_posts, build_insights
from app.services.discovery import DiscoveryError, discover_posts
from app.services.parsers import ParseError, parse_posts_file

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
DEMO_FILE = DATA_DIR / "demo_posts.json"

app = FastAPI(
    title="Content Radar MVP",
    description="MVP инструмент для анализа контента конкурентов",
    version="1.2.0",
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
store = InMemoryPostStore()


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    """Главная страница MVP."""

    return templates.TemplateResponse("index.html", {"request": request})


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


@app.post("/load_demo", response_model=UploadResponse)
def load_demo() -> UploadResponse:
    """Загружает демонстрационные данные из data/demo_posts.json."""

    if not DEMO_FILE.exists():
        raise HTTPException(status_code=404, detail="Демо-файл не найден.")

    content = DEMO_FILE.read_bytes()
    try:
        posts = parse_posts_file(filename=DEMO_FILE.name, content=content)
    except ParseError as exc:
        raise HTTPException(status_code=500, detail=f"Ошибка демоданных: {exc}") from exc

    store.replace_posts(posts)
    return UploadResponse(message="Демоданные успешно загружены", posts_count=len(posts))
