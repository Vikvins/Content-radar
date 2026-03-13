from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Iterable

from app.models import PostRecord

TOKEN_RE = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9]{3,}")
STOP_WORDS = {
    "это",
    "как",
    "для",
    "что",
    "или",
    "про",
    "при",
    "без",
    "под",
    "после",
    "the",
    "and",
    "with",
    "from",
    "this",
    "that",
    "you",
}

ENGAGEMENT_WEIGHTS = {
    "likes": 1.0,
    "comments": 2.0,
    "shares": 3.0,
    "views": 0.1,
}


@dataclass
class AnalysisResult:
    posts: list[dict]
    top_posts: list[dict]
    top_topics: list[dict]
    best_time: dict
    top_formats: list[dict]
    recommendations: list[str]
    engagement_formula: dict
    summary: dict


class InMemoryPostStore:
    """Потокобезопасное in-memory хранилище постов для MVP."""

    def __init__(self) -> None:
        self._posts: list[PostRecord] = []
        self._discovered_posts: list[PostRecord] = []
        self._last_analysis: AnalysisResult | None = None
        self._lock = Lock()

    def replace_posts(self, posts: list[PostRecord]) -> None:
        with self._lock:
            self._posts = posts
            self._last_analysis = None

    def get_posts(self) -> list[PostRecord]:
        with self._lock:
            return list(self._posts)

    def set_discovered_posts(self, posts: list[PostRecord]) -> None:
        with self._lock:
            self._discovered_posts = list(posts)

    def get_discovered_posts(self) -> list[PostRecord]:
        with self._lock:
            return list(self._discovered_posts)

    def select_discovered_posts(self, selected_ids: list[int]) -> list[PostRecord]:
        with self._lock:
            selected = [
                self._discovered_posts[idx]
                for idx in selected_ids
                if 0 <= idx < len(self._discovered_posts)
            ]
            self._posts = selected
            self._last_analysis = None
            return list(selected)

    def set_last_analysis(self, analysis: AnalysisResult) -> None:
        with self._lock:
            self._last_analysis = analysis

    def get_last_analysis(self) -> AnalysisResult | None:
        with self._lock:
            return self._last_analysis


def get_engagement_formula() -> dict:
    """Возвращает описание формулы вовлечённости для API/UI."""

    return {
        "title": "Формула вовлечённости",
        "description": "Вовлечённость = Лайки × 1 + Комментарии × 2 + Репосты × 3 + Просмотры × 0.1",
        "weights": ENGAGEMENT_WEIGHTS,
    }


def calculate_engagement_score(post: PostRecord) -> float:
    """Считает вовлечённость по заданным весам действий и просмотров."""

    score = (
        (post.likes * ENGAGEMENT_WEIGHTS["likes"])
        + (post.comments * ENGAGEMENT_WEIGHTS["comments"])
        + (post.shares * ENGAGEMENT_WEIGHTS["shares"])
        + (post.views * ENGAGEMENT_WEIGHTS["views"])
    )
    return round(score, 2)


def _tokenize(text: str) -> list[str]:
    tokens = [token.lower() for token in TOKEN_RE.findall(text)]
    return [token for token in tokens if token not in STOP_WORDS]


def _infer_topics(posts: Iterable[PostRecord], scores: dict[int, float]) -> list[dict]:
    posts_list = list(posts)
    if not posts_list:
        return []

    tokenized = [_tokenize(post.text) for post in posts_list]
    doc_count = len(tokenized)

    df_counter: Counter[str] = Counter()
    for terms in tokenized:
        df_counter.update(set(terms))

    topic_aggregate: dict[str, dict[str, float]] = defaultdict(lambda: {"count": 0, "engagement_sum": 0.0})

    for idx, terms in enumerate(tokenized):
        if not terms:
            continue

        tf_counter = Counter(terms)
        best_term = None
        best_tfidf = -1.0
        for term, tf in tf_counter.items():
            idf = math.log((doc_count + 1) / (df_counter[term] + 1)) + 1
            tfidf = tf * idf
            if tfidf > best_tfidf:
                best_tfidf = tfidf
                best_term = term

        if not best_term:
            continue

        topic_data = topic_aggregate[best_term]
        topic_data["count"] += 1
        topic_data["engagement_sum"] += scores[idx]

    topics = [
        {
            "topic": topic,
            "posts_count": int(values["count"]),
            "avg_engagement": round(values["engagement_sum"] / values["count"], 2),
        }
        for topic, values in topic_aggregate.items()
        if values["count"] > 0
    ]
    topics.sort(key=lambda item: (item["avg_engagement"], item["posts_count"]), reverse=True)
    return topics[:8]


def _best_time(posts: list[PostRecord], scores: dict[int, float]) -> dict:
    buckets = {
        "ночь": range(0, 6),
        "утро": range(6, 12),
        "день": range(12, 18),
        "вечер": range(18, 24),
    }

    bucket_stats: dict[str, list[float]] = {name: [] for name in buckets}
    hour_stats: dict[int, list[float]] = defaultdict(list)

    for idx, post in enumerate(posts):
        hour = post.date.hour
        hour_stats[hour].append(scores[idx])

        for bucket_name, bucket_range in buckets.items():
            if hour in bucket_range:
                bucket_stats[bucket_name].append(scores[idx])
                break

    avg_by_bucket = {
        name: round(sum(values) / len(values), 2)
        for name, values in bucket_stats.items()
        if values
    }
    avg_by_hour = {
        hour: round(sum(values) / len(values), 2)
        for hour, values in hour_stats.items()
        if values
    }

    best_bucket = max(avg_by_bucket.items(), key=lambda item: item[1])[0] if avg_by_bucket else None
    best_hour = max(avg_by_hour.items(), key=lambda item: item[1])[0] if avg_by_hour else None

    return {
        "best_bucket": best_bucket,
        "best_hour": best_hour,
        "avg_by_bucket": avg_by_bucket,
        "avg_by_hour": avg_by_hour,
    }


def _best_formats(posts: list[PostRecord], scores: dict[int, float]) -> list[dict]:
    format_values: dict[str, list[float]] = defaultdict(list)
    for idx, post in enumerate(posts):
        format_values[post.format].append(scores[idx])

    result = [
        {
            "format": content_format,
            "avg_engagement": round(sum(values) / len(values), 2),
            "posts_count": len(values),
        }
        for content_format, values in format_values.items()
        if values
    ]
    result.sort(key=lambda item: item["avg_engagement"], reverse=True)
    return result


def _generate_recommendations(
    top_topics: list[dict],
    best_time: dict,
    top_formats: list[dict],
    top_posts: list[dict],
    avg_engagement: float,
) -> list[str]:
    recommendations: list[str] = []

    if top_formats:
        best_format = top_formats[0]
        format_name = best_format["format"]
        avg_score = best_format["avg_engagement"]

        if format_name == "carousel":
            recommendations.append(
                "Сделайте карусели базовым форматом контент-плана: у них лучший средний отклик аудитории."
            )
        elif format_name == "video":
            recommendations.append(
                "Увеличьте долю видео в регулярных публикациях: этот формат приносит максимальную вовлечённость."
            )
        else:
            recommendations.append(
                f"Сделайте формат {format_name} базовым для регулярных публикаций, так как он показывает лучший средний отклик аудитории ({avg_score})."
            )

    if best_time.get("best_hour") is not None:
        best_hour = int(best_time["best_hour"])
        hour_label = f"{best_hour:02d}:00"
        if 6 <= best_hour < 12:
            recommendations.append(
                f"Ставьте приоритетные публикации на {hour_label}: в утренний слот аудитория реагирует активнее всего."
            )
        elif 12 <= best_hour < 18:
            recommendations.append(
                f"Планируйте ключевые посты на {hour_label}: дневной слот сейчас даёт самый высокий отклик."
            )
        elif 18 <= best_hour < 24:
            recommendations.append(
                f"Добавьте регулярные вечерние публикации около {hour_label}: это окно приносит лучший результат по вовлечённости."
            )
        else:
            recommendations.append(
                f"Протестируйте ночной контент около {hour_label}: в текущих данных этот период показывает хороший потенциал роста отклика."
            )
    elif best_time.get("best_bucket"):
        recommendations.append(
            f"Сфокусируйте ближайший контент-план на периоде «{best_time['best_bucket']}»: он показывает самый сильный средний результат."
        )

    if top_topics:
        prioritized_topics = [item["topic"] for item in top_topics[:2]]
        recommendations.append(
            f"Развивайте темы {', '.join(prioritized_topics)} в ближайших публикациях: именно они дают наиболее стабильный отклик аудитории."
        )

    if top_posts and avg_engagement > 0:
        top_post_score = top_posts[0]["engagement_score"]
        if top_post_score >= avg_engagement * 1.25:
            recommendations.append(
                "Возьмите топ-пост как референс для новой серии материалов: повторите его структуру, подачу и формат, чтобы масштабировать результат."
            )

    if not recommendations:
        recommendations.append("Недостаточно данных для рекомендаций. Добавьте больше постов для анализа.")

    return recommendations


def analyze_posts(posts: list[PostRecord], competitors: list[str] | None = None) -> AnalysisResult:
    """Выполняет полный анализ контента и возвращает структуру для API/UI."""

    filtered_posts = posts
    if competitors:
        normalized = {item.strip().lower() for item in competitors if item.strip()}
        filtered_posts = [
            post
            for post in posts
            if post.competitor and post.competitor.strip().lower() in normalized
        ]

    score_map: dict[int, float] = {
        idx: calculate_engagement_score(post) for idx, post in enumerate(filtered_posts)
    }

    enriched_posts = [
        {
            "id": idx,
            "text": post.text,
            "likes": post.likes,
            "comments": post.comments,
            "shares": post.shares,
            "views": post.views,
            "date": post.date.isoformat(),
            "format": post.format,
            "competitor": post.competitor,
            "engagement_score": score_map[idx],
        }
        for idx, post in enumerate(filtered_posts)
    ]

    top_posts = sorted(
        enriched_posts,
        key=lambda item: item["engagement_score"],
        reverse=True,
    )[:3]

    top_topics = _infer_topics(filtered_posts, score_map)
    best_time = _best_time(filtered_posts, score_map)
    top_formats = _best_formats(filtered_posts, score_map)

    avg_engagement = (
        round(sum(score_map.values()) / len(score_map), 2)
        if score_map
        else 0
    )

    recommendations = _generate_recommendations(
        top_topics=top_topics,
        best_time=best_time,
        top_formats=top_formats,
        top_posts=top_posts,
        avg_engagement=avg_engagement,
    )

    summary = {
        "total_posts": len(filtered_posts),
        "avg_engagement": avg_engagement,
        "competitors_in_scope": sorted(
            list({post.competitor for post in filtered_posts if post.competitor})
        ),
        "analyzed_at": datetime.utcnow().isoformat() + "Z",
    }

    return AnalysisResult(
        posts=enriched_posts,
        top_posts=top_posts,
        top_topics=top_topics,
        best_time=best_time,
        top_formats=top_formats,
        recommendations=recommendations,
        engagement_formula=get_engagement_formula(),
        summary=summary,
    )


def build_insights(analysis: AnalysisResult) -> dict:
    """Формирует человекочитаемые инсайты для маркетолога."""

    return {
        "recommendations": analysis.recommendations,
        "summary": analysis.summary,
        "engagement_formula": analysis.engagement_formula,
    }
