#!/usr/bin/env python3
"""Tests for grazer_mcp.client — no network (httpx MockTransport).

Mirrors the LIVE BoTTube API shapes (verified 2026-06-26):
  /api/trending -> {"videos":[...]}
  /api/search   -> {"page","pages","total","videos":[...]}
  /api/v2/feed  -> {"mode","explanation","videos":[...]}

Run:  python3 tests/test_client.py   (or: python3 -m pytest -q)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import httpx  # noqa: E402
from grazer_mcp.client import GrazerClient  # noqa: E402

# A representative BoTTube video object (subset of the real fields).
VIDEO = {
    "video_id": "9hq8hdFUbam", "id": 2167, "title": "Dust Bunny Elimination #2",
    "agent_name": "automatedjanitor2015", "display_name": "AutomatedJanitor2015",
    "views": 31, "likes": 8, "category": "other", "category_name": "Other",
    "duration_sec": 4.853, "watch_url": "/watch/9hq8hdFUbam",
    "thumbnail_url": "/thumbnails/9hq8hdFUbam.jpg", "created_at": 1782417722.7, "tags": ["ai"],
}


def _client(handler):
    return GrazerClient(base_url="https://test.local", transport=httpx.MockTransport(handler))


def _json(payload, capture=None):
    def h(req):
        if capture is not None:
            capture["url"] = str(req.url)
        return httpx.Response(200, json=payload)
    return h


def test_platforms_lists_bottube():
    p = GrazerClient().platforms()
    assert p["ok"] and "bottube" in p["platforms"] and p["default"] == "bottube"


def test_trending_hits_real_path_and_normalizes():
    cap = {}
    c = _client(_json({"category": None, "videos": [VIDEO]}, cap))
    r = c.trending("bottube", 5)
    assert r["ok"] and r["count"] == 1
    assert "/api/trending" in cap["url"] and "limit=5" in cap["url"]
    it = r["items"][0]
    assert it["id"] == "9hq8hdFUbam" and it["title"].startswith("Dust Bunny")
    assert it["agent"] == "automatedjanitor2015" and it["views"] == 31
    assert it["url"] == "https://test.local/watch/9hq8hdFUbam"          # absolutized
    assert it["thumbnail"] == "https://test.local/thumbnails/9hq8hdFUbam.jpg"


def test_trending_clamps_limit():
    cap = {}
    _client(_json({"videos": []}, cap)).trending("bottube", 999)
    assert "limit=50" in cap["url"]


def test_discover_uses_search_with_paging_and_metadata():
    cap = {}
    c = _client(_json({"page": 2, "pages": 76, "total": 1502, "videos": [VIDEO]}, cap))
    r = c.discover("ai", "bottube", page=2)
    assert r["ok"] and "/api/search" in cap["url"]
    assert "q=ai" in cap["url"] and "page=2" in cap["url"]
    assert r["total"] == 1502 and r["pages"] == 76 and r["count"] == 1


def test_discover_passes_optional_filters_and_omits_none():
    cap = {}
    _client(_json({"videos": []}, cap)).discover("ai", sort="recent", category="science")
    assert "sort=recent" in cap["url"] and "category=science" in cap["url"]
    assert "min_views" not in cap["url"]                                # None omitted


def test_discover_requires_query():
    r = GrazerClient().discover("   ")
    assert not r["ok"] and r["error"]["code"] == "BAD_REQUEST"


def test_feed_ranked_uses_v2_and_surfaces_explanation():
    cap = {}
    c = _client(_json({"mode": "heuristic", "explanation": "Popularity-only ranker", "videos": [VIDEO]}, cap))
    r = c.feed("bottube", 4, ranked=True)
    assert r["ok"] and "/api/v2/feed" in cap["url"] and "limit=4" in cap["url"]
    assert r["ranker"] == "heuristic" and "Popularity" in r["explanation"] and r["count"] == 1


def test_feed_latest_uses_v1():
    cap = {}
    _client(_json({"mode": "latest", "videos": []}, cap)).feed("bottube", ranked=False)
    assert "/api/feed" in cap["url"] and "/api/v2/feed" not in cap["url"]


def test_unknown_platform_rejected():
    r = GrazerClient().trending("myspace")
    assert not r["ok"] and r["error"]["code"] == "UNKNOWN_PLATFORM"
    assert "bottube" in r["error"]["details"]["supported"]


def test_upstream_500_is_retryable():
    r = _client(lambda req: httpx.Response(503, text="down")).trending()
    assert not r["ok"] and r["error"]["code"] == "UPSTREAM_STATUS" and r["error"]["retryable"] is True


def test_upstream_404_not_retryable():
    r = _client(lambda req: httpx.Response(404, text="nope")).discover("cats")
    assert not r["ok"] and r["error"]["retryable"] is False


def test_timeout_maps_to_stable_error():
    def h(req):
        raise httpx.TimeoutException("slow")
    r = _client(h).trending()
    assert not r["ok"] and r["error"]["code"] == "UPSTREAM_TIMEOUT"


def test_bad_json_handled():
    r = _client(lambda req: httpx.Response(200, text="<html>")).trending()
    assert not r["ok"] and r["error"]["code"] == "UPSTREAM_BAD_JSON"


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    ok = 0
    for t in tests:
        try:
            t()
            print(f"  PASS {t.__name__}")
            ok += 1
        except AssertionError as e:
            print(f"  FAIL {t.__name__}: {e}")
        except Exception as e:
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{ok}/{len(tests)} passed")
    return ok == len(tests)


if __name__ == "__main__":
    sys.exit(0 if _run() else 1)
