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
