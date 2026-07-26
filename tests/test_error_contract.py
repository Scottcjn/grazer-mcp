"""Tests for grazer-mcp error contract — ensures every tool returns the stable
error-envelope shape on failure and normalizes videos on success.

No network — httpx.MockTransport replaces all HTTP calls.

Requirements (bounty #16250):
  * 4 tools × 4 failure modes (500, 404, timeout, bad-json) → 16 parametrized cases
  * retryable=True for 5xx/timeout, False for 4xx/bad-json
  * success responses normalise to {id, title, agent, views, …}
  * zero network calls
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from grazer_mcp.client import GrazerClient

# ═══════════════════════════════════════════════════════════════════════
#  helpers
# ═══════════════════════════════════════════════════════════════════════

VIDEO: dict[str, Any] = {
    "video_id": "9hq8hdFUbam",
    "id": 2167,
    "title": "Dust Bunny Elimination #2",
    "agent_name": "automatedjanitor2015",
    "display_name": "AutomatedJanitor2015",
    "views": 31,
    "likes": 8,
    "category": "other",
    "category_name": "Other",
    "duration_sec": 4.853,
    "watch_url": "/watch/9hq8hdFUbam",
    "thumbnail_url": "/thumbnails/9hq8hdFUbam.jpg",
    "created_at": 1782417722.7,
    "tags": ["ai"],
}

SUCCESS_PAYLOADS: dict[str, Any] = {
    "trending": {"category": None, "videos": [VIDEO]},
    "discover": {"page": 1, "pages": 10, "total": 200, "videos": [VIDEO]},
    "feed": {"mode": "heuristic", "explanation": "Popularity ranker", "videos": [VIDEO]},
}


def client(handler: Callable) -> GrazerClient:
    """Build a GrazerClient wired to an httpx.MockTransport."""
    return GrazerClient(
        base_url="https://test.local",
        transport=httpx.MockTransport(handler),
    )


# ── mock handlers ─────────────────────────────────────────────────────


def http_500(_req: httpx.Request) -> httpx.Response:
    return httpx.Response(500, text="Internal Server Error")


def http_404(_req: httpx.Request) -> httpx.Response:
    return httpx.Response(404, text="Not Found")


def http_timeout(_req: httpx.Request) -> httpx.Response:
    msg = "Request timed out"
    raise httpx.TimeoutException(msg) from None


def bad_json(_req: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text="<html>not json</html>")


def ok_json(payload: dict[str, Any]) -> Callable:
    """Return a handler that responds with a static JSON payload."""

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return handler


# ── tool-calling helpers ──────────────────────────────────────────────


def call_trending(c: GrazerClient) -> dict:
    return c.trending("bottube", 5)


def call_discover(c: GrazerClient) -> dict:
    return c.discover("ai", "bottube")


def call_feed(c: GrazerClient) -> dict:
    return c.feed("bottube", 5, ranked=True)


def call_platforms(c: GrazerClient) -> dict:
    return c.platforms()


# ── assertions ────────────────────────────────────────────────────────


def assert_normalized(v: dict) -> None:
    """Assert a video dict has every field of the documented common shape."""
    assert "id" in v, f"missing 'id' in {v}"
    assert "title" in v, f"missing 'title' in {v}"
    assert "agent" in v, f"missing 'agent' in {v}"
    assert "views" in v, f"missing 'views' in {v}"
    assert "likes" in v, f"missing 'likes' in {v}"
    assert "category" in v, f"missing 'category' in {v}"
    assert "duration_sec" in v, f"missing 'duration_sec' in {v}"
    assert "url" in v, f"missing 'url' in {v}"
    assert "thumbnail" in v, f"missing 'thumbnail' in {v}"
    assert "created_at" in v, f"missing 'created_at' in {v}"
    assert "tags" in v, f"missing 'tags' in {v}"


def assert_error_envelope(r: dict, *, code: str, retryable: bool) -> None:
    """Assert the stable error-envelope shape described in the README."""
    assert r["ok"] is False, f"expected ok=False, got {r}"
    err = r["error"]
    assert err["code"] == code, f"expected code={code!r}, got {err['code']!r}"
    assert isinstance(err["message"], str) and len(err["message"]) > 0
    assert err["retryable"] is retryable, f"expected retryable={retryable}"
    assert err["source"] == "grazer", f"expected source='grazer', got {err['source']!r}"
    assert isinstance(err["details"], dict)


# ═══════════════════════════════════════════════════════════════════════
#  parametrized test data  (3 network tools × 4 failures = 12)
# ═══════════════════════════════════════════════════════════════════════

# Each failure case: (id_suffix, mock_fn, expected_code, expected_retryable)
FAILURE_CASES: list[tuple[str, Callable, str, bool]] = [
    ("500", http_500, "UPSTREAM_STATUS", True),
    ("404", http_404, "UPSTREAM_STATUS", False),
    ("timeout", http_timeout, "UPSTREAM_TIMEOUT", True),
    ("bad_json", bad_json, "UPSTREAM_BAD_JSON", False),
]

# Each network tool case: (tool_name, call_fn, success_payload)
NETWORK_TOOL_CASES: list[tuple[str, Callable, dict]] = [
    ("graze_trending", call_trending, SUCCESS_PAYLOADS["trending"]),
    ("graze_discover", call_discover, SUCCESS_PAYLOADS["discover"]),
    ("graze_feed", call_feed, SUCCESS_PAYLOADS["feed"]),
]

# Build the 12 parametrized error-test cases
ERROR_TEST_CASES = [
    pytest.param(
        tool_name,
        call_fn,
        mock_fn,
        expected_code,
        expected_retryable,
        id=f"{tool_name}_{failure_id}",
    )
    for tool_name, call_fn, _ in NETWORK_TOOL_CASES
    for failure_id, mock_fn, expected_code, expected_retryable in FAILURE_CASES
]

# ═══════════════════════════════════════════════════════════════════════
#  Error-envelope tests  (12 cases: 3 tools × 4 failures)
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    ("tool_name", "call_fn", "mock_fn", "expected_code", "expected_retryable"),
    ERROR_TEST_CASES,
)
def test_error_envelope_shape(
    tool_name: str,
    call_fn: Callable[[GrazerClient], dict],
    mock_fn: Callable,
    expected_code: str,
    expected_retryable: bool,
) -> None:
    """Every network-dependent tool returns the same error envelope for
    HTTP 500, 404, timeout, and malformed-JSON responses."""
    c = client(mock_fn)
    result = call_fn(c)
    assert_error_envelope(result, code=expected_code, retryable=expected_retryable)


# ═══════════════════════════════════════════════════════════════════════
#  graze_platforms  (always succeeds — no HTTP dependency)
# ═══════════════════════════════════════════════════════════════════════


def test_graze_platforms_contract() -> None:
    """graze_platforms returns the documented success envelope regardless
    of transport (it never makes HTTP calls)."""
    c = client(http_500)  # broken transport — shouldn't matter
    r = c.platforms()
    assert r["ok"] is True
    assert r["default"] == "bottube"
    assert isinstance(r["platforms"], dict)
    assert "bottube" in r["platforms"]
    p = r["platforms"]["bottube"]
    assert p["status"] == "live"
    assert "description" in p


def test_graze_platforms_contract_via_broken_transport_404() -> None:
    """Same contract holds even with a 404-ing transport."""
    c = client(http_404)
    r = c.platforms()
    assert r["ok"] is True
    assert r["default"] == "bottube"


def test_graze_platforms_contract_via_broken_transport_timeout() -> None:
    """Same contract holds even with a timing-out transport."""
    c = client(http_timeout)
    r = c.platforms()
    assert r["ok"] is True


def test_graze_platforms_contract_via_broken_transport_bad_json() -> None:
    """Same contract holds even with a bad-JSON transport."""
    c = client(bad_json)
    r = c.platforms()
    assert r["ok"] is True


# ═══════════════════════════════════════════════════════════════════════
#  Success-normalisation tests  (4 tools)
# ═══════════════════════════════════════════════════════════════════════


class TestSuccessNormalization:
    """Verify success responses normalise to the documented contract."""

    @pytest.mark.parametrize(
        ("tool_name", "call_fn", "payload"),
        [
            pytest.param("graze_trending", call_trending, SUCCESS_PAYLOADS["trending"], id="graze_trending"),
            pytest.param("graze_discover", call_discover, SUCCESS_PAYLOADS["discover"], id="graze_discover"),
            pytest.param("graze_feed", call_feed, SUCCESS_PAYLOADS["feed"], id="graze_feed"),
        ],
    )
    def test_video_normalization(
        self,
        tool_name: str,
        call_fn: Callable[[GrazerClient], dict],
        payload: dict,
    ) -> None:
        """Items in a success response are normalised to the documented
        common video shape."""
        c = client(ok_json(payload))
        result = call_fn(c)
        assert result["ok"] is True
        for item in result["items"]:
            assert_normalized(item)
            # Spot-check the absolutized URL
            assert item["url"].startswith("https://test.local")
            assert item["thumbnail"].startswith("https://test.local")

    def test_graze_trending_success_shape(self) -> None:
        """graze_trending success includes platform, count, and items."""
        c = client(ok_json(SUCCESS_PAYLOADS["trending"]))
        r = c.trending("bottube", 5)
        assert r["ok"] is True
        assert r["platform"] == "bottube"
        assert r["count"] == 1
        assert len(r["items"]) == 1
        assert_normalized(r["items"][0])

    def test_graze_discover_success_shape(self) -> None:
        """graze_discover success includes query, pagination metadata."""
        c = client(ok_json(SUCCESS_PAYLOADS["discover"]))
        r = c.discover("ai", "bottube")
        assert r["ok"] is True
        assert r["platform"] == "bottube"
        assert r["query"] == "ai"
        assert r["page"] == 1
        assert r["pages"] == 10
        assert r["total"] == 200
        assert r["count"] == 1
        assert_normalized(r["items"][0])

    def test_graze_feed_success_shape(self) -> None:
        """graze_feed success includes ranker metadata."""
        c = client(ok_json(SUCCESS_PAYLOADS["feed"]))
        r = c.feed("bottube", 5, ranked=True)
        assert r["ok"] is True
        assert r["platform"] == "bottube"
        assert r["ranked"] is True
        assert r["ranker"] == "heuristic"
        assert r["count"] == 1
        assert_normalized(r["items"][0])

    def test_graze_platforms_success_shape(self) -> None:
        """graze_platforms returns platform listing with status."""
        c = GrazerClient()
        r = c.platforms()
        assert r["ok"] is True
        assert "platforms" in r
        assert r["default"] == "bottube"
        for info in r["platforms"].values():
            assert "status" in info
            assert "description" in info
