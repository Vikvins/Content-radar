from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import app


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run() -> dict:
    report: dict[str, object] = {
        "scenario_1": {},
        "scenario_2": {},
        "scenario_3": {},
        "status": "ok",
    }

    with TestClient(app) as client:
        # Scenario 1: file/demo mode -> load demo -> analyze
        demo_response = client.post("/load_demo")
        assert_true(demo_response.status_code == 200, "load_demo must return 200")
        demo_payload = demo_response.json()
        demo_posts_count = int(demo_payload.get("posts_count", 0))
        demo_posts = demo_payload.get("posts", [])
        assert_true(demo_posts_count > 0, "load_demo must prepare posts for analysis")
        assert_true(
            len(demo_posts) == demo_posts_count,
            "load_demo must return posts list consistent with posts_count",
        )

        analyze_1 = client.post("/analyze_content", json={"competitors": []})
        assert_true(analyze_1.status_code == 200, "analyze_content after load_demo must return 200")
        analyze_1_payload = analyze_1.json()
        analyzed_1_posts = len(analyze_1_payload.get("posts", []))
        assert_true(analyzed_1_posts > 0, "analysis after load_demo must contain posts")

        report["scenario_1"] = {
            "load_demo_posts_count": demo_posts_count,
            "analyze_posts_count": analyzed_1_posts,
        }

        # Scenario 2: discover by link -> select -> save -> analyze
        discover_payload = {
            "source_url": "https://example.com/competitor",
            "competitor": "MarketPulse",
            "limit": 12,
        }
        discover_response = client.post("/discover_posts", json=discover_payload)
        assert_true(discover_response.status_code == 200, "discover_posts must return 200")
        discover_body = discover_response.json()

        discovered_posts = discover_body.get("posts", [])
        discovered_count = len(discovered_posts)
        assert_true(discovered_count > 0, "discover_posts must return selectable posts")

        selected_ids = [post["discovered_id"] for post in discovered_posts[:3]]
        assert_true(len(selected_ids) > 0, "there must be ids for select_posts")

        select_response = client.post("/select_posts", json={"selected_ids": selected_ids})
        assert_true(select_response.status_code == 200, "select_posts must return 200")
        select_body = select_response.json()
        saved_count = int(select_body.get("posts_count", 0))
        assert_true(saved_count == len(selected_ids), "select_posts must save exactly selected posts")

        analyze_2 = client.post("/analyze_content", json={"competitors": []})
        assert_true(analyze_2.status_code == 200, "analyze_content after select_posts must return 200")
        analyze_2_payload = analyze_2.json()
        analyzed_2_posts = len(analyze_2_payload.get("posts", []))
        assert_true(analyzed_2_posts == saved_count, "analysis posts count must match saved selected posts")

        report["scenario_2"] = {
            "discovered_posts_count": discovered_count,
            "selected_ids": selected_ids,
            "saved_posts_count": saved_count,
            "analyze_posts_count": analyzed_2_posts,
        }

        # Scenario 3: discover by link -> load demo -> verify discovered data replaced by demo posts
        discover_before_demo = client.post("/discover_posts", json=discover_payload)
        assert_true(
            discover_before_demo.status_code == 200,
            "discover_posts before demo reset must return 200",
        )

        demo_reset_response = client.post("/load_demo")
        assert_true(
            demo_reset_response.status_code == 200,
            "load_demo after discovery must return 200",
        )
        demo_reset_payload = demo_reset_response.json()
        demo_reset_posts = demo_reset_payload.get("posts", [])
        demo_reset_count = int(demo_reset_payload.get("posts_count", 0))

        assert_true(
            demo_reset_count == len(demo_reset_posts),
            "load_demo reset payload must have consistent posts_count and posts length",
        )
        assert_true(demo_reset_count > 0, "load_demo reset must return demo posts")

        first_demo_post_text = str(demo_reset_posts[0].get("text", ""))
        assert_true(
            len(first_demo_post_text.strip()) > 0,
            "first demo post text in load_demo payload must be non-empty",
        )

        select_after_demo = client.post("/select_posts", json={"selected_ids": [0]})
        assert_true(
            select_after_demo.status_code == 200,
            "select_posts after load_demo reset must use demo discovered posts and return 200",
        )

        analyze_3 = client.post("/analyze_content", json={"competitors": []})
        assert_true(
            analyze_3.status_code == 200,
            "analyze_content after selecting post from reset demo list must return 200",
        )
        analyze_3_payload = analyze_3.json()
        analyzed_3_posts = analyze_3_payload.get("posts", [])
        assert_true(
            len(analyzed_3_posts) == 1,
            "analysis after selecting one post from reset demo list must contain exactly one post",
        )

        analyzed_text = str(analyzed_3_posts[0].get("text", ""))
        assert_true(
            analyzed_text == first_demo_post_text,
            "selected post after load_demo reset must match demo payload, not stale discovered content",
        )

        report["scenario_3"] = {
            "load_demo_reset_posts_count": demo_reset_count,
            "selected_ids_after_reset": [0],
            "analyzed_posts_count": len(analyzed_3_posts),
            "matched_demo_text": analyzed_text == first_demo_post_text,
        }

    return report


if __name__ == "__main__":
    try:
        result = run()
        print(json.dumps(result, ensure_ascii=True))
    except Exception as exc:  # pragma: no cover - script-level guard
        failure = {
            "status": "error",
            "error_type": exc.__class__.__name__,
            "error": str(exc),
        }
        print(json.dumps(failure, ensure_ascii=True))
        raise
