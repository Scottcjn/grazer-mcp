#!/usr/bin/env python3
"""Error-contract test suite for grazer-mcp (bounty Scottcjn/rustchain-bounties#16250).

Covers the documented error envelope for all four MCP tools:

    {"ok": False, "error": {"code", "message", "retryable", "source", "details"}}

and the success-normalization shape for the three network-backed tools.

Everything runs OFFLINE via httpx.MockTransport — no live network calls.
The client methods (trending/discover/feed/platforms) are the backing logic for
the graze_trending / graze_discover / graze_feed / graze_platforms MCP tools, so
exercising them exercises the documented contract of all four tools.

Run:
    python3 -m pytest tests/test_error_contract.py -q
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402
from grazer_mcp.client import GrazerClient  # noqa: E402

# Representative BoTTube video object (subset of the real fields).
VIDEO = {
    "video_id": "9hq8hdFUbam", "id": 2167, "title": "Dust Bunny Elimination #2",
    "agent_name": "automatedjanitor2015", "display_name": "AutomatedJanitor2015",
    "views": 31, "likes": 8, "category": "other", "category_name": "Other",
    "duration_sec": 4.853, "watch_url": "/watch/9hq8hdFUbam",
    "thumbnail_url": "/thumbnails/9hq8hdFUbam.jpg", "created_at": 1782417722.7, "tags": ["ai"],
}

# The four MCP tools map 1:1 onto these client methods.
NETWORK_TOOLS = ["trending", "discover", "feed"]
ALL_TOOLS = ["trending", "discover", "feed", "platforms"]

# The exact set of keys the README promises in every error envelope.
ERROR_KEYS = {"code", "message", "retryable", "source", "details"}


# --------------------------------------------------------------------------- #
# Mock transport helpers
# --------------------------------------------------------------------------- #
def _client(handler):
    return GrazerClient(base_url="https://test.local", transport=httpx.MockTransport(handler))


def _json(payload):
    return lambda req: httpx.Response(200, json=payload)


def _status(code, text="boom"):
    return lambda req: httpx.Response(code, text=text)


def _timeout(req):
    raise httpx.TimeoutException("slow backend")


def _bad_json(req):
    # HTTP 200 but body is not valid JSON -> UPSTREAM_BAD_JSON
    return httpx.Response(200, text="<html>service unavailable</html>")


# Dispatch the right client method for a given tool name, with sensible args.
def _call(tool: str, client: GrazerClient):
    if tool == "trending":
        return client.trending("bottube", 10)
    if tool == "discover":
        return client.discover("cats", "bottube", page=1)
    if tool == "feed":
        return client.feed("bottube", 10, ranked=True)
    if tool == "platforms":
        return client.platforms()
    raise AssertionError(f"unknown tool {tool}")


def _assert_envelope(result: dict) -> dict:
    """Assert the exact documented error-envelope shape; return the error dict."""
    assert result["ok"] is False, f"expected ok=False, got {result!r}"
    assert "error" in result, f"error envelope missing, got {result!r}"
    err = result["error"]
    assert set(err.keys()) == ERROR_KEYS, f"error keys {set(err)} != {ERROR_KEYS}"
    assert isinstance(err["code"], str) and err["code"]
    assert isinstance(err["message"], str) and err["message"]
    assert isinstance(err["retryable"], bool), "retryable must be bool"
    assert err["source"] == "grazer", f"source={err['source']!r} (expected 'grazer')"
    assert isinstance(err["details"], dict), "details must be a dict"
    return err


# --------------------------------------------------------------------------- #
# 1) Error envelope shape for each network tool x each failure mode (12 cases)
# --------------------------------------------------------------------------- #
def test_envelope_shape_http500():
    for tool in NETWORK_TOOLS:
        err = _assert_envelope(_call(tool, _client(_status(500))))
        assert err["code"] == "UPSTREAM_STATUS"
        assert err["retryable"] is True
        assert err["details"]["status"] == 500


def test_envelope_shape_http404():
    for tool in NETWORK_TOOLS:
        err = _assert_envelope(_call(tool, _client(_status(404))))
        assert err["code"] == "UPSTREAM_STATUS"
        assert err["retryable"] is False  # 4xx is not retryable
        assert err["details"]["status"] == 404


def test_envelope_shape_timeout():
    for tool in NETWORK_TOOLS:
        err = _assert_envelope(_call(tool, _client(_timeout)))
        assert err["code"] == "UPSTREAM_TIMEOUT"
        assert err["retryable"] is True


def test_envelope_shape_bad_json():
    for tool in NETWORK_TOOLS:
        err = _assert_envelope(_call(tool, _client(_bad_json)))
        assert err["code"] == "UPSTREAM_BAD_JSON"
        assert err["retryable"] is False  # malformed body is not retryable


# --------------------------------------------------------------------------- #
# 2) Parametrized equivalence across all three network tools (same 4 modes)
#    — guarantees no tool special-cases the contract away.
# --------------------------------------------------------------------------- #
import pytest  # noqa: E402

FAILURE_MODES = {
    "http_500": (_status(500), "UPSTREAM_STATUS", True),
    "http_404": (_status(404), "UPSTREAM_STATUS", False),
    "timeout": (_timeout, "UPSTREAM_TIMEOUT", True),
    "bad_json": (_bad_json, "UPSTREAM_BAD_JSON", False),
}


@pytest.mark.parametrize("tool", NETWORK_TOOLS)
@pytest.mark.parametrize("mode,handler,code,retryable", [
    (m, h, c, r) for m, (h, c, r) in FAILURE_MODES.items()
])
def test_error_contract_parametrized(tool, mode, handler, code, retryable):
    err = _assert_envelope(_call(tool, _client(handler)))
    assert err["code"] == code
    assert err["retryable"] is retryable


# --------------------------------------------------------------------------- #
# 3) Success responses normalize to the documented video shape {id,title,...}
# --------------------------------------------------------------------------- #
DOC_VIDEO_KEYS = {"id", "title", "agent", "views", "likes", "category",
                  "duration_sec", "url", "thumbnail", "created_at", "tags"}


def test_trending_success_normalizes_video_shape():
    r = _client(_json({"videos": [VIDEO]})).trending("bottube", 10)
    assert r["ok"] is True
    it = r["items"][0]
    assert DOC_VIDEO_KEYS.issubset(it.keys()), f"missing {DOC_VIDEO_KEYS - set(it)}"
    assert it["id"] == "9hq8hdFUbam"
    assert it["title"] == "Dust Bunny Elimination #2"
    assert it["agent"] == "automatedjanitor2015"
    assert it["views"] == 31
    assert it["url"] == "https://test.local/watch/9hq8hdFUbam"  # absolutized
    assert it["thumbnail"] == "https://test.local/thumbnails/9hq8hdFUbam.jpg"


def test_discover_success_normalizes_video_shape():
    r = _client(_json({"page": 1, "pages": 1, "total": 1, "videos": [VIDEO]})).discover("cats")
    assert r["ok"] is True
    it = r["items"][0]
    assert DOC_VIDEO_KEYS.issubset(it.keys())
    assert it["id"] == "9hq8hdFUbam" and it["views"] == 31


def test_feed_success_normalizes_video_shape():
    r = _client(_json({"mode": "heuristic", "explanation": "x", "videos": [VIDEO]})).feed("bottube", 10, ranked=True)
    assert r["ok"] is True
    it = r["items"][0]
    assert DOC_VIDEO_KEYS.issubset(it.keys())
    assert it["title"] == "Dust Bunny Elimination #2"


# --------------------------------------------------------------------------- #
# 4) graze_platforms / platforms() — the one tool with NO backend dependency.
#    It cannot enter the error contract by design (in-memory constant), so the
#    "4 failure modes" do not apply. We assert its success envelope and that it
#    never takes the error path. See PR description for the README-vs-code note.
# --------------------------------------------------------------------------- #
def test_platforms_success_envelope():
    r = GrazerClient().platforms()
    assert r["ok"] is True
    assert r["default"] == "bottube"
    assert "bottube" in r["platforms"]
    # platforms() returns a stable envelope, not the video shape
    assert set(r.keys()) == {"ok", "platforms", "default"}


def test_platforms_has_no_backend_failure_path():
    """platforms() is backend-free: it returns ok and never raises/errors."""
    try:
        r = GrazerClient().platforms()
    except Exception as e:  # pragma: no cover - documents the invariant
        raise AssertionError(f"platforms() raised unexpectedly: {e!r}")
    assert r["ok"] is True


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
