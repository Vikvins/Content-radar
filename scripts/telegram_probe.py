from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.discovery import _fetch_page_html, discover_posts


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _snippet_samples(html: str, pattern: str, max_items: int = 8) -> list[str]:
    snippets: list[str] = []
    for match in re.finditer(pattern, html, flags=re.IGNORECASE | re.DOTALL):
        snippets.append(_compact(match.group(0))[:320])
        if len(snippets) >= max_items:
            break
    return snippets


def _inspect_message_blocks(html: str, max_items: int = 6) -> list[dict[str, object]]:
    chunks = html.split('<div class="tgme_widget_message_wrap')
    if len(chunks) <= 1:
        return []

    blocks = [f'<div class="tgme_widget_message_wrap{chunk}' for chunk in chunks[1:]]
    inspected: list[dict[str, object]] = []

    for block in blocks[:max_items]:
        post_id_match = re.search(r'data-post="[^"]+/(\d+)"', block)
        post_id = int(post_id_match.group(1)) if post_id_match else None

        reaction_count_matches = re.findall(
            r'tgme_widget_message_reaction(?:_count|_counter)[^"]*"[^>]*>([^<]+)<',
            block,
            flags=re.IGNORECASE,
        )
        reaction_related_classes = sorted(
            set(re.findall(r'class="([^"]*reaction[^"]*)"', block, flags=re.IGNORECASE))
        )

        replies_anchor = re.search(
            r'<a[^>]*class="[^"]*tgme_widget_message_repl[^"]*"[^>]*>.*?</a>',
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )

        reply_preview = re.search(
            r'<a[^>]*class="[^"]*tgme_widget_message_reply[^"]*"[^>]*>.*?</a>',
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )

        inspected.append(
            {
                "post_id": post_id,
                "reaction_related_classes": reaction_related_classes,
                "reaction_count_matches": reaction_count_matches,
                "has_replies_anchor": bool(replies_anchor),
                "replies_anchor_snippet": _compact(replies_anchor.group(0))[:320] if replies_anchor else "",
                "has_reply_preview": bool(reply_preview),
                "reply_preview_snippet": _compact(reply_preview.group(0))[:320] if reply_preview else "",
            }
        )

    return inspected


def run() -> dict:
    links = ["https://t.me/s/durov", "https://t.me/s/telegram"]
    result: dict[str, object] = {}

    for link in links:
        html = _fetch_page_html(link)
        posts, meta = discover_posts(source_url=link, limit=12)

        result[link] = {
            "source_mode": meta.source_mode,
            "source_url": meta.source_url,
            "posts_count": len(posts),
            "likes_nonzero": sum(1 for post in posts if post.likes > 0),
            "comments_nonzero": sum(1 for post in posts if post.comments > 0),
            "views_nonzero": sum(1 for post in posts if post.views > 0),
            "sample_posts": [
                {
                    "text": post.text[:100],
                    "date": post.date.isoformat(),
                    "format": post.format,
                    "likes": post.likes,
                    "comments": post.comments,
                    "shares": post.shares,
                    "views": post.views,
                }
                for post in posts[:5]
            ],
            "markup_debug": {
                "reaction_samples": _snippet_samples(
                    html,
                    r"<[^>]*reaction[^>]*>.*?</[^>]+>",
                ),
                "replies_samples": _snippet_samples(
                    html,
                    r"<a[^>]*tgme_widget_message_repl[^>]*>.*?</a>",
                ),
                "reply_preview_samples": _snippet_samples(
                    html,
                    r"<a[^>]*tgme_widget_message_reply[^>]*>.*?</a>",
                ),
                "message_block_inspection": _inspect_message_blocks(html),
            },
        }

    return result


if __name__ == "__main__":
    output = run()
    print(json.dumps(output, ensure_ascii=True))
