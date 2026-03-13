from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.discovery import _fetch_page_html


def compact(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def inspect_channel(url: str) -> dict:
    html = _fetch_page_html(url)
    blocks = html.split('<div class="tgme_widget_message_wrap')
    messages = [f'<div class="tgme_widget_message_wrap{chunk}' for chunk in blocks[1:8]]

    inspected: list[dict[str, object]] = []
    for block in messages:
        post_match = re.search(r'data-post="([^"]+)"', block)
        post_ref = post_match.group(1) if post_match else ""

        reactions_container_match = re.search(
            r'<div class="tgme_widget_message_reactions[^"]*"[^>]*>(?P<body>.*?)</div>',
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        reactions_html = reactions_container_match.group(0) if reactions_container_match else ""

        reaction_spans = re.findall(
            r'<span class="tgme_reaction[^"]*"[^>]*>.*?</span>',
            reactions_html,
            flags=re.IGNORECASE | re.DOTALL,
        )

        reaction_items: list[dict[str, object]] = []
        for span in reaction_spans[:20]:
            reaction_items.append(
                {
                    "html": compact(span)[:420],
                    "attributes": re.findall(r'([a-zA-Z0-9_:-]+)="([^"]*)"', span)[:20],
                    "text": compact(re.sub(r"<[^>]+>", " ", span)),
                }
            )

        replies_candidates = re.findall(
            r'<a[^>]*class="[^"]*(?:repl|comment)[^"]*"[^>]*>.*?</a>',
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )

        inspected.append(
            {
                "post_ref": post_ref,
                "reaction_container_html": compact(reactions_html)[:1200],
                "reaction_container_attrs": re.findall(
                    r'([a-zA-Z0-9_:-]+)="([^"]*)"',
                    reactions_html,
                )[:40],
                "reaction_items": reaction_items,
                "replies_candidates": [compact(item)[:500] for item in replies_candidates[:10]],
            }
        )

    return {
        "url": url,
        "message_count_scanned": len(messages),
        "inspected": inspected,
    }


def run() -> dict:
    urls = ["https://t.me/s/durov", "https://t.me/s/telegram"]
    return {url: inspect_channel(url) for url in urls}


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=True))
