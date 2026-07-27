#!/usr/bin/env python3
"""Tests for the stable error contract across all 4 grazer tools.

Per the README, every tool returns:
  - {"ok": true, ...} on success
  - {"ok": false, "error": {code, message, retryable, source, details}} on failure

This test module verifies the error envelope shape for each tool across
4 failure modes: HTTP 500, HTTP 404, timeout, and malformed/non-JSON body.

Run: python3 -m pytest tests/test_error_contract.py -v
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402
import pytest  # noqa: E402
from grazer_mcp.client import GrazerClient  # noqa: E402

# Representative BoTTube video object for success responses
VIDEO = {
    "video_id": "test123",
    "id": 100,
    "title": "Test Video",
    "agent_name": "testbot",
    "display_name": "TestBot",
    "views": 1000,
    "likes": 50,
    "category": "tech",
    "category_name": "Tech",
    "duration_sec": 120.0,
    "watch_url": "/watch/test123",
    "thumbnail_url": "/thumbnails/test123.jpg",
    "created_at": 1700000000.0,
    "tags": ["test"],
}


def _mock_client(handler):
    """Create a GrazerClient with a mock transport."""
    return GrazerClient(
        base_url="https://test.local",
        transport=httpx.MockTransport(handler),
    )


def _success_handler(capture=None):
    """Return a handler that responds with success (trending format)."""
    def h(req):
        if capture is not None:
            capture["url"] = str(req.url)
            capture["method"] = req.method
        return httpx.Response(200, json={"videos": [VIDEO]})
    return h


def _error_handler(status_code):
    """Return a handler that responds with an error status code."""
    def h(req):
        return httpx.Response(status_code, json={"error": "something went wrong"})
    return h


def _timeout_handler():
    """Return a handler that raises a timeout exception."""
    def h(req):
        raise httpx.TimeoutException("connection timed out")
    return h


def _bad_json_handler():
    """Return a handler that returns non-JSON content."""
    def h(req):
        return httpx.Response(200, text="<html><body>Error page</body></html>")
    return h


def _validate_error_envelope(result, expected_retryable=None):
    """Validate the error envelope shape matches the documented contract."""
    assert result["ok"] is False, "Expected ok=False for error responses"
    assert "error" in result, "Expected 'error' key in response"
    
    error = result["error"]
    assert "code" in error, "Expected 'code' in error envelope"
    assert "message" in error, "Expected 'message' in error envelope"
    assert "retryable" in error, "Expected 'retryable' in error envelope"
    assert "source" in error, "Expected 'source' in error envelope"
    assert "details" in error, "Expected 'details' in error envelope"
    
    assert isinstance(error["code"], str), "Error code should be a string"
    assert isinstance(error["message"], str), "Error message should be a string"
    assert isinstance(error["retryable"], bool), "retryable should be a boolean"
    assert isinstance(error["source"], str), "Error source should be a string"
    assert isinstance(error["details"], dict), "Error details should be a dict"
    
    if expected_retryable is not None:
        assert error["retryable"] == expected_retryable, (
            f"Expected retryable={expected_retryable}, got {error['retryable']}"
        )


def _validate_video_shape(video):
    """Validate a video object has the documented shape."""
    required_fields = ["id", "title", "agent", "views", "likes", "category",
                       "url", "thumbnail", "created_at", "tags"]
    for field in required_fields:
        assert field in video, f"Missing required field: {field}"


# ============================================================================
# Test cases: 4 tools × 4 failure modes = 16 cases
# ============================================================================

class TestGrazeTrending:
    """Tests for graze_trending error contract."""

    def test_http_500(self):
        c = _mock_client(_error_handler(500))
        result = c.trending("bottube")
        _validate_error_envelope(result, expected_retryable=True)
        assert result["error"]["code"] == "UPSTREAM_STATUS"

    def test_http_404(self):
        c = _mock_client(_error_handler(404))
        result = c.trending("bottube")
        _validate_error_envelope(result, expected_retryable=False)
        assert result["error"]["code"] == "UPSTREAM_STATUS"

    def test_timeout(self):
        c = _mock_client(_timeout_handler())
        result = c.trending("bottube")
        _validate_error_envelope(result, expected_retryable=True)
        assert result["error"]["code"] == "UPSTREAM_TIMEOUT"

    def test_bad_json(self):
        c = _mock_client(_bad_json_handler())
        result = c.trending("bottube")
        _validate_error_envelope(result, expected_retryable=False)
        assert result["error"]["code"] == "UPSTREAM_BAD_JSON"

    def test_success_normalizes_video(self):
        c = _mock_client(_success_handler())
        result = c.trending("bottube")
        assert result["ok"] is True
        assert result["count"] == 1
        _validate_video_shape(result["items"][0])


class TestGrazeDiscover:
    """Tests for graze_discover error contract."""

    def test_http_500(self):
        c = _mock_client(_error_handler(500))
        result = c.discover("test query", "bottube")
        _validate_error_envelope(result, expected_retryable=True)
        assert result["error"]["code"] == "UPSTREAM_STATUS"

    def test_http_404(self):
        c = _mock_client(_error_handler(404))
        result = c.discover("test query", "bottube")
        _validate_error_envelope(result, expected_retryable=False)
        assert result["error"]["code"] == "UPSTREAM_STATUS"

    def test_timeout(self):
        c = _mock_client(_timeout_handler())
        result = c.discover("test query", "bottube")
        _validate_error_envelope(result, expected_retryable=True)
        assert result["error"]["code"] == "UPSTREAM_TIMEOUT"

    def test_bad_json(self):
        c = _mock_client(_bad_json_handler())
        result = c.discover("test query", "bottube")
        _validate_error_envelope(result, expected_retryable=False)
        assert result["error"]["code"] == "UPSTREAM_BAD_JSON"

    def test_success_normalizes_video(self):
        def handler(req):
            return httpx.Response(200, json={
                "page": 1, "pages": 10, "total": 100, "videos": [VIDEO]
            })
        c = _mock_client(handler)
        result = c.discover("test query", "bottube")
        assert result["ok"] is True
        assert result["count"] == 1
        assert result["total"] == 100
        _validate_video_shape(result["items"][0])


class TestGrazeFeed:
    """Tests for graze_feed error contract."""

    def test_http_500(self):
        c = _mock_client(_error_handler(500))
        result = c.feed("bottube")
        _validate_error_envelope(result, expected_retryable=True)
        assert result["error"]["code"] == "UPSTREAM_STATUS"

    def test_http_404(self):
        c = _mock_client(_error_handler(404))
        result = c.feed("bottube")
        _validate_error_envelope(result, expected_retryable=False)
        assert result["error"]["code"] == "UPSTREAM_STATUS"

    def test_timeout(self):
        c = _mock_client(_timeout_handler())
        result = c.feed("bottube")
        _validate_error_envelope(result, expected_retryable=True)
        assert result["error"]["code"] == "UPSTREAM_TIMEOUT"

    def test_bad_json(self):
        c = _mock_client(_bad_json_handler())
        result = c.feed("bottube")
        _validate_error_envelope(result, expected_retryable=False)
        assert result["error"]["code"] == "UPSTREAM_BAD_JSON"

    def test_success_normalizes_video(self):
        def handler(req):
            return httpx.Response(200, json={
                "mode": "heuristic", "explanation": "Popularity ranker",
                "videos": [VIDEO]
            })
        c = _mock_client(handler)
        result = c.feed("bottube")
        assert result["ok"] is True
        assert result["count"] == 1
        assert result["ranker"] == "heuristic"
        _validate_video_shape(result["items"][0])


class TestGrazePlatforms:
    """Tests for graze_platforms error contract.

    Note: graze_platforms() doesn't make network calls, so it can't have
    HTTP/timeout/JSON errors. It always returns success.
    """

    def test_always_succeeds(self):
        result = GrazerClient().platforms()
        assert result["ok"] is True
        assert "platforms" in result
        assert "bottube" in result["platforms"]


# ============================================================================
# Parametrized tests for comprehensive coverage
# ============================================================================

@pytest.mark.parametrize("tool_func,tool_name", [
    (lambda c, **kw: c.trending(**kw), "trending"),
    (lambda c, **kw: c.discover("test", **kw), "discover"),
    (lambda c, **kw: c.feed(**kw), "feed"),
])
@pytest.mark.parametrize("handler,status_code,retryable", [
    (_error_handler(500), 500, True),
    (_error_handler(502), 502, True),
    (_error_handler(503), 503, True),
    (_error_handler(404), 404, False),
    (_error_handler(400), 400, False),
    (_error_handler(401), 401, False),
    (_timeout_handler(), None, True),
    (_bad_json_handler(), None, False),
], ids=[
    "500-retryable", "502-retryable", "503-retryable",
    "404-not-retryable", "400-not-retryable", "401-not-retryable",
    "timeout-retryable", "bad-json-not-retryable",
])
def test_error_contract_parametrized(tool_func, tool_name, handler, status_code, retryable):
    """Parametrized test covering all tools × all failure modes."""
    c = _mock_client(handler)
    result = tool_func(c)
    _validate_error_envelope(result, expected_retryable=retryable)
    if status_code is not None:
        assert result["error"]["code"] == "UPSTREAM_STATUS"
    elif retryable and "timeout" in str(handler):
        assert result["error"]["code"] == "UPSTREAM_TIMEOUT"
    else:
        assert result["error"]["code"] == "UPSTREAM_BAD_JSON"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
