from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


ContentFormat = Literal["post", "video", "carousel"]
DiscoveryMode = Literal["public", "demo"]


class PostRecord(BaseModel):
    """Единая структура поста для загрузки и анализа."""

    text: str = Field(..., min_length=1)
    likes: int = Field(..., ge=0)
    comments: int = Field(..., ge=0)
    shares: int = Field(..., ge=0)
    views: int = Field(..., ge=0)
    date: datetime
    format: ContentFormat
    competitor: str | None = None


class AnalyzeRequest(BaseModel):
    """Параметры запуска анализа контента."""

    competitors: list[str] = Field(default_factory=list)


class UploadResponse(BaseModel):
    """Ответ после загрузки или сохранения постов."""

    message: str
    posts_count: int


class InsightResponse(BaseModel):
    """Ответ для итоговых инсайтов и рекомендаций."""

    recommendations: list[str]
    engagement_formula: dict
    summary: dict


class DiscoverPostsRequest(BaseModel):
    """Параметры MVP-поиска постов по ссылке конкурента."""

    # Поддерживаем обычный пользовательский ввод: ссылка с/без схемы.
    source_url: str = Field(..., min_length=3, max_length=500)
    competitor: str | None = Field(default=None, min_length=1, max_length=100)
    limit: int = Field(default=12, ge=3, le=50)


class DiscoverPostItem(BaseModel):
    """Пост, доступный для выбора пользователем в сценарии без файла."""

    discovered_id: int
    text: str
    format: ContentFormat
    date: datetime
    competitor: str | None = None
    likes: int
    comments: int
    shares: int
    views: int


class DiscoverPostsResponse(BaseModel):
    """Ответ с найденными/сгенерированными постами и режимом источника."""

    message: str
    source_url: str
    source_mode: DiscoveryMode
    source_details: str
    warning: str | None = None
    posts_count: int
    posts: list[DiscoverPostItem]


class DemoLoadResponse(UploadResponse):
    """Ответ загрузки демоданных с постами для моментального обновления UI-таблицы."""

    posts: list[DiscoverPostItem]


class SelectPostsRequest(BaseModel):
    """Запрос на выбор постов для дальнейшего анализа."""

    selected_ids: list[int] = Field(default_factory=list)


class ChannelInput(BaseModel):
    """Канал для конкурентного сравнения."""

    name: str = Field(..., min_length=1, max_length=120)
    url: str = Field(..., min_length=3, max_length=500)


class CompareChannelsRequest(BaseModel):
    """Запрос на сравнение своего канала с конкурентами."""

    my_channel_name: str = Field(..., min_length=1, max_length=120)
    my_channel_url: str = Field(..., min_length=3, max_length=500)
    competitors: list[ChannelInput] = Field(..., min_length=1, max_length=10)
    posts_limit: int = Field(default=12, ge=3, le=50)


class WinnerInfo(BaseModel):
    """Информация о лидере сравнения."""

    name: str
    avg_engagement: float
    reason: str


class RankingItem(BaseModel):
    """Одна строка рейтинга каналов."""

    rank: int
    name: str
    avg_engagement: float
    gap_vs_leader_pct: float
    strong_side: str
    weak_side: str


class ChannelComparisonDetails(BaseModel):
    """Сводка аналитики по отдельному каналу."""

    name: str
    source_url: str
    source_mode: DiscoveryMode
    warning: str | None = None
    posts_count: int
    avg_engagement: float
    top_topics: list[str]
    top_formats: list[str]
    best_time: str


class EngagementTimelinePoint(BaseModel):
    """Одна точка динамики вовлечённости по времени."""

    date: str
    engagement: float


class ChannelTimeline(BaseModel):
    """Линия динамики вовлечённости для канала."""

    name: str
    points: list[EngagementTimelinePoint]


class CompareChannelsResponse(BaseModel):
    """Итоговый ответ конкурентного сравнения для фронтенда."""

    message: str
    analyzed_at: str
    posts_limit: int
    my_channel_name: str
    winner: WinnerInfo
    ranking: list[RankingItem]
    channel_details: list[ChannelComparisonDetails]
    timelines: list[ChannelTimeline]
    insights: list[str]
    actions: list[str]
    warnings: list[str]
    is_demo_mode: bool
    engagement_formula: dict
