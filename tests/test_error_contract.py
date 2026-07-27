"""Tests for grazer-mcp error contract.

Covers all 4 tools x 4 failure modes + success contracts.
All tests run offline using httpx.MockTransport.
"""
import httpx
import pytest
from grazer_mcp.client import GrazerClient


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def make_client(handler):
    """Create a GrazerClient with a mock transport."""
    transport = httpx.MockTransport(handler)
    return GrazerClient(base_url="https://mock.test", timeout=5.0, transport=transport)


def mock_handler(status_code: int, body: str = "", content_type: str = "application/json"):
    """Return a handler that always responds with the given status/body."""
    def handler(request):
        headers = {"Content-Type": content_type}
        return httpx.Response(status_code, content=body.encode(), headers=headers)
    return handler


def mock_handler_json(data: dict, status_code: int = 200):
    """Return a handler that responds with JSON."""
    import json
    body = json.dumps(data)
    return mock_handler(status_code, body, "application/json")


def assert_error_shape(result: dict, expected_retryable: bool = None):
    """Assert the result matches the documented error envelope."""
    assert result["ok"] is False
    error = result["error"]
    assert "code" in error
    assert "message" in error
    assert "retryable" in error
    assert "source" in error
    assert error["source"] == "grazer"
    assert isinstance(error["details"], dict)
    if expected_retryable is not None:
        assert error["retryable"] == expected_retryable


def assert_success_shape(result: dict, tool: str):
    """Assert the result matches the documented success shape."""
    assert result["ok"] is True
    if tool == "platforms":
        assert "platforms" in result
    elif tool == "trending":
        assert "items" in result
        assert "count" in result
        assert "platform" in result
    elif tool == "discover":
        assert "items" in result
        assert "count" in result
        assert "query" in result
    elif tool == "feed":
        assert "items" in result
        assert "count" in result


def assert_video_shape(video: dict):
    """Assert a normalized video has the documented fields."""
    assert "id" in video
    assert "title" in video
    assert "agent" in video
    assert "views" in video


# ═══════════════════════════════════════════════════════════════
# Test: graze_platforms
# NOTE: platforms() is a local-only function that never makes HTTP
# calls — it returns the static PLATFORMS dict directly. Error
# contract tests are therefore not applicable. This is a
# README-vs-code inconsistency documented in the PR description.
# ═══════════════════════════════════════════════════════════════

class TestGrazePlatforms:
    def test_success(self):
        """platforms() always returns success (local-only, no HTTP)."""
        client = make_client(mock_handler(200, '{}'))
        result = client.platforms()
        assert_success_shape(result, "platforms")


# ═══════════════════════════════════════════════════════════════
# Test: graze_trending
# ═══════════════════════════════════════════════════════════════

class TestGrazeTrending:
    MOCK_VIDEOS = {"videos": [
        {"video_id": "v1", "title": "Test Video", "agent_name": "agent1", "views": 100},
    ]}

    def test_success(self):
        """trending() returns normalized video shape."""
        client = make_client(mock_handler_json(self.MOCK_VIDEOS))
        result = client.trending("bottube", 10)
        assert_success_shape(result, "trending")
        assert len(result["items"]) == 1
        assert_video_shape(result["items"][0])

    def test_timeout(self):
        """trending() timeout returns UPSTREAM_TIMEOUT."""
        def handler(request):
            raise httpx.TimeoutException("timed out")
        client = make_client(handler)
        result = client.trending("bottube", 10)
        assert_error_shape(result, expected_retryable=True)
        assert result["error"]["code"] == "UPSTREAM_TIMEOUT"

    def test_http_500(self):
        """trending() 500 returns retryable error."""
        client = make_client(mock_handler(500, '{"error": "Internal Server Error"}'))
        result = client.trending("bottube", 10)
        assert_error_shape(result, expected_retryable=True)

    def test_http_404(self):
        """trending() 404 returns non-retryable error."""
        client = make_client(mock_handler(404, '{"error": "Not Found"}'))
        result = client.trending("bottube", 10)
        assert_error_shape(result, expected_retryable=False)

    def test_malformed_json(self):
        """trending() non-JSON returns UPSTREAM_BAD_JSON."""
        client = make_client(mock_handler(200, "not json", "text/plain"))
        result = client.trending("bottube", 10)
        assert_error_shape(result, expected_retryable=False)
        assert result["error"]["code"] == "UPSTREAM_BAD_JSON"


# ═══════════════════════════════════════════════════════════════
# Test: graze_discover
# ═══════════════════════════════════════════════════════════════

class TestGrazeDiscover:
    MOCK_SEARCH = {"videos": [
        {"video_id": "v2", "title": "Search Result", "agent_name": "agent2", "views": 50},
    ], "page": 1, "pages": 1, "total": 1}

    def test_success(self):
        """discover() returns normalized video shape with query."""
        client = make_client(mock_handler_json(self.MOCK_SEARCH))
        result = client.discover("test query", "bottube", 1)
        assert_success_shape(result, "discover")
        assert result["query"] == "test query"
        assert_video_shape(result["items"][0])

    def test_timeout(self):
        """discover() timeout returns UPSTREAM_TIMEOUT."""
        def handler(request):
            raise httpx.TimeoutException("timed out")
        client = make_client(handler)
        result = client.discover("test", "bottube", 1)
        assert_error_shape(result, expected_retryable=True)
        assert result["error"]["code"] == "UPSTREAM_TIMEOUT"

    def test_http_500(self):
        """discover() 500 returns retryable error."""
        client = make_client(mock_handler(500, '{"error": "Internal Server Error"}'))
        result = client.discover("test", "bottube", 1)
        assert_error_shape(result, expected_retryable=True)

    def test_http_404(self):
        """discover() 404 returns non-retryable error."""
        client = make_client(mock_handler(404, '{"error": "Not Found"}'))
        result = client.discover("test", "bottube", 1)
        assert_error_shape(result, expected_retryable=False)

    def test_malformed_json(self):
        """discover() non-JSON returns UPSTREAM_BAD_JSON."""
        client = make_client(mock_handler(200, "bad", "text/plain"))
        result = client.discover("test", "bottube", 1)
        assert_error_shape(result, expected_retryable=False)
        assert result["error"]["code"] == "UPSTREAM_BAD_JSON"

    def test_empty_query(self):
        """discover() empty query returns BAD_REQUEST."""
        client = make_client(mock_handler(200, '{"videos": []}'))
        result = client.discover("", "bottube", 1)
        assert_error_shape(result, expected_retryable=False)
        assert result["error"]["code"] == "BAD_REQUEST"

    def test_unknown_platform(self):
        """discover() unknown platform returns UNKNOWN_PLATFORM."""
        client = make_client(mock_handler(200, '{"videos": []}'))
        result = client.discover("test", "nonexistent", 1)
        assert_error_shape(result, expected_retryable=False)
        assert result["error"]["code"] == "UNKNOWN_PLATFORM"


# ═══════════════════════════════════════════════════════════════
# Test: graze_feed
# ═══════════════════════════════════════════════════════════════

class TestGrazeFeed:
    MOCK_FEED = {"videos": [
        {"video_id": "v3", "title": "Feed Item", "agent_name": "agent3", "views": 200},
    ], "mode": "ranked", "explanation": "sorted by popularity"}

    def test_success(self):
        """feed() returns normalized video shape."""
        client = make_client(mock_handler_json(self.MOCK_FEED))
        result = client.feed("bottube", 10, True)
        assert_success_shape(result, "feed")
        assert_video_shape(result["items"][0])

    def test_timeout(self):
        """feed() timeout returns UPSTREAM_TIMEOUT."""
        def handler(request):
            raise httpx.TimeoutException("timed out")
        client = make_client(handler)
        result = client.feed("bottube", 10, True)
        assert_error_shape(result, expected_retryable=True)
        assert result["error"]["code"] == "UPSTREAM_TIMEOUT"

    def test_http_500(self):
        """feed() 500 returns retryable error."""
        client = make_client(mock_handler(500, '{"error": "Internal Server Error"}'))
        result = client.feed("bottube", 10, True)
        assert_error_shape(result, expected_retryable=True)

    def test_http_404(self):
        """feed() 404 returns non-retryable error."""
        client = make_client(mock_handler(404, '{"error": "Not Found"}'))
        result = client.feed("bottube", 10, True)
        assert_error_shape(result, expected_retryable=False)

    def test_malformed_json(self):
        """feed() non-JSON returns UPSTREAM_BAD_JSON."""
        client = make_client(mock_handler(200, "nope", "text/plain"))
        result = client.feed("bottube", 10, True)
        assert_error_shape(result, expected_retryable=False)
        assert result["error"]["code"] == "UPSTREAM_BAD_JSON"

    def test_unknown_platform(self):
        """feed() unknown platform returns UNKNOWN_PLATFORM."""
        client = make_client(mock_handler(200, '{"videos": []}'))
        result = client.feed("nonexistent", 10, True)
        assert_error_shape(result, expected_retryable=False)
        assert result["error"]["code"] == "UNKNOWN_PLATFORM"
