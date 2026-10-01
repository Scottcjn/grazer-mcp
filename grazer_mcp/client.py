"""Grazer discovery client — pure logic, no MCP dependency (fully unit-testable).

Wired to the LIVE BoTTube discovery API (verified 2026-06-26):
  trending: GET /api/trending?limit=N
  search:   GET /api/search?q=...&page=N[&sort=&category=&min_views=]
  feed:     GET /api/v2/feed?per_page=N  (ranked)  |  /api/videos?page=1&per_page=N&sort=newest  (latest)

Every method returns {"ok": True, ...} or a predictable {"ok": False, "error": {...}}
object, never a silent empty result. Video objects are normalized to a common shape
so the surface is stable as platforms are added.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

# Supported platforms. Keep status honest: "live" = backed now.
PLATFORMS = {
    "bottube": {"status": "live", "description": "BoTTube AI-native video platform",
                "base": "https://bottube.ai"},
}


def err(code: str, message: str, *, retryable: bool = True, **details) -> dict:
    return {"ok": False, "error": {"code": code, "message": message,
                                   "retryable": retryable, "source": "grazer",
                                   "details": details or {}}}


def clamp(n: Any, lo: int, hi: int) -> int:
    try:
        return max(lo, min(int(n), hi))
    except (TypeError, ValueError):
        return lo


class GrazerClient:
    def __init__(self, base_url: str | None = None, timeout: float | None = None,
                 transport: httpx.BaseTransport | None = None):
        self.base_url = (base_url or os.environ.get("GRAZER_API_URL", "https://bottube.ai")).rstrip("/")
        self.timeout = timeout if timeout is not None else float(os.environ.get("GRAZER_TIMEOUT", "20"))
        self._transport = transport  # for tests (httpx.MockTransport)

    # --- transport --- #
    def _get(self, path: str, params: dict | None = None) -> dict:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True,
                              transport=self._transport) as c:
                r = c.get(f"{self.base_url}{path}", params=params)
        except httpx.TimeoutException:
            return err("UPSTREAM_TIMEOUT", f"{path} did not respond before {self.timeout}s")
        except httpx.HTTPError as e:
            return err("UPSTREAM_UNREACHABLE", str(e))
        if r.status_code != 200:
            return err("UPSTREAM_STATUS", f"{path} returned HTTP {r.status_code}",
                       retryable=r.status_code >= 500, status=r.status_code)
        try:
            return {"ok": True, "data": r.json()}
        except ValueError:
            return err("UPSTREAM_BAD_JSON", f"{path} returned non-JSON", retryable=False)

    # --- helpers --- #
    def _check_platform(self, platform: str) -> dict | None:
        if platform not in PLATFORMS:
            return err("UNKNOWN_PLATFORM", f"unsupported platform: {platform}",
                       retryable=False, supported=list(PLATFORMS))
        return None

    def _abs(self, p: Any) -> Any:
        return f"{self.base_url}{p}" if isinstance(p, str) and p.startswith("/") else p

    def _normalize(self, v: dict) -> dict:
        """Map a BoTTube video object to grazer's common content shape."""
        return {
            "id": v.get("video_id") or v.get("id"),
            "title": v.get("title"),
            "agent": v.get("agent_name") or v.get("display_name"),
            "views": v.get("views"),
            "likes": v.get("likes"),
            "category": v.get("category_name") or v.get("category"),
            "duration_sec": v.get("duration_sec"),
            "url": self._abs(v.get("watch_url") or v.get("url")),
            "thumbnail": self._abs(v.get("thumbnail_url")),
            "created_at": v.get("created_at"),
            "tags": v.get("tags"),
        }

    @staticmethod
    def _videos(data: Any) -> list:
        if isinstance(data, dict):
            return data.get("videos", []) or []
        return data if isinstance(data, list) else []

    # --- public surface (mirrored by the MCP tools) --- #
    def platforms(self) -> dict:
        return {"ok": True, "platforms": PLATFORMS, "default": "bottube"}

    def trending(self, platform: str = "bottube", limit: int = 10) -> dict:
        if (e := self._check_platform(platform)):
            return e
        res = self._get("/api/trending", {"limit": clamp(limit, 1, 50)})
        if not res["ok"]:
            return res
        items = [self._normalize(v) for v in self._videos(res["data"])]
        return {"ok": True, "platform": platform, "count": len(items), "items": items}

    def discover(self, query: str, platform: str = "bottube", page: int = 1,
                 sort: str | None = None, category: str | None = None,
                 min_views: int | None = None) -> dict:
        if not query or not query.strip():
            return err("BAD_REQUEST", "query is required", retryable=False)
        if (e := self._check_platform(platform)):
            return e
        res = self._get("/api/search", {"q": query.strip(), "page": clamp(page, 1, 10_000),
                                         "sort": sort, "category": category, "min_views": min_views})
        if not res["ok"]:
            return res
        d = res["data"] if isinstance(res["data"], dict) else {}
        items = [self._normalize(v) for v in self._videos(res["data"])]
        return {"ok": True, "platform": platform, "query": query.strip(),
                "page": d.get("page", page), "pages": d.get("pages"), "total": d.get("total"),
                "count": len(items), "items": items}

    def feed(self, platform: str = "bottube", limit: int = 10, ranked: bool = True) -> dict:
        """Discovery feed. ranked=True -> backend ranker; ranked=False -> newest.

        BoTTube's ``/api/feed`` is itself a ranking surface and can switch
        between heuristic/personalized modes, so it is not a reliable
        implementation of the unranked/newest contract.  Use the catalog's
        explicit newest sort when callers opt out of ranking.
        """
        if (e := self._check_platform(platform)):
            return e
        bounded = clamp(limit, 1, 50)
        if ranked:
            res = self._get("/api/v2/feed", {"per_page": bounded})
        else:
            res = self._get("/api/videos", {
                "page": 1, "per_page": bounded, "sort": "newest",
            })
        if not res["ok"]:
            return res
        d = res["data"] if isinstance(res["data"], dict) else {}
        items = [self._normalize(v) for v in self._videos(res["data"])]
        return {
            "ok": True,
            "platform": platform,
            "ranked": ranked,
            "ranker": d.get("mode") if ranked else "latest",
            "explanation": d.get("explanation") if ranked else "Newest-first catalog order.",
            "count": len(items),
            "items": items,
        }
