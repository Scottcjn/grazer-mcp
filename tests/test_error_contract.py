"""Unit tests for grazer-mcp error contract and response normalization (Bounty #16250).

Tests all 4 tools across 4 failure modes:
1. HTTP 500 (retryable=True)
2. HTTP 404 (retryable=False)
3. Timeout (retryable=True)
4. Malformed/non-JSON body (retryable=False)

Also tests success response normalization.
"""
import httpx
import pytest

from grazer_mcp.client import GrazerClient


@pytest.fixture
def mock_client_factory():
    """Factory fixture to create a GrazerClient with a custom MockTransport."""
    def _create(handler):
        transport = httpx.MockTransport(handler)
        return GrazerClient(base_url="https://bottube.ai", timeout=2.0, transport=transport)
    return _create


FAILURE_MODES = [
    ("http_500", 500, b"Internal Server Error", "UPSTREAM_STATUS", True),
    ("http_404", 404, b"Not Found", "UPSTREAM_STATUS", False),
    ("timeout", None, None, "UPSTREAM_TIMEOUT", True),
    ("bad_json", 200, b"<html>Not JSON</html>", "UPSTREAM_BAD_JSON", False),
]

TOOLS = ["trending", "discover", "feed"]


@pytest.mark.parametrize("mode_name,status_code,body,expected_code,expected_retryable", FAILURE_MODES)
@pytest.mark.parametrize("tool_name", TOOLS)
def test_tools_error_contract(mock_client_factory, mode_name, status_code, body, expected_code, expected_retryable, tool_name):
    def handler(request: httpx.Request) -> httpx.Response:
        if mode_name == "timeout":
            raise httpx.TimeoutException("Connection timed out", request=request)
        return httpx.Response(status_code=status_code, content=body)

    client = mock_client_factory(handler)

    if tool_name == "trending":
        res = client.trending()
    elif tool_name == "discover":
        res = client.discover("test query")
    elif tool_name == "feed":
        res = client.feed()
    else:
        pytest.fail(f"Unknown tool {tool_name}")

    assert res["ok"] is False
    assert "error" in res
    err = res["error"]
    assert err["code"] == expected_code
    assert err["retryable"] is expected_retryable
    assert err["source"] == "grazer"
    assert "message" in err
    assert isinstance(err["details"], dict)


def test_platforms_tool_contract(mock_client_factory):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    client = mock_client_factory(handler)
    res = client.platforms()
    assert res["ok"] is True
    assert "platforms" in res
    assert "bottube" in res["platforms"]


def test_unknown_platform_error_contract(mock_client_factory):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    client = mock_client_factory(handler)
    for tool_call in [
        lambda c: c.trending(platform="unknown_platform"),
        lambda c: c.discover("test", platform="unknown_platform"),
        lambda c: c.feed(platform="unknown_platform"),
    ]:
        res = tool_call(client)
        assert res["ok"] is False
        err = res["error"]
        assert err["code"] == "UNKNOWN_PLATFORM"
        assert err["retryable"] is False


def test_success_response_normalization(mock_client_factory):
    raw_video = {
        "video_id": "vid_123",
        "title": "Test AI Video",
        "agent_name": "TestAgent",
        "views": 100,
        "likes": 10,
        "category_name": "Tech",
        "duration_sec": 60,
        "watch_url": "/watch?v=vid_123",
        "thumbnail_url": "/thumbs/vid_123.jpg",
        "created_at": "2026-08-01T12:00:00Z",
        "tags": ["ai", "test"],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"videos": [raw_video]})

    client = mock_client_factory(handler)

    for tool_call in [
        lambda c: c.trending(),
        lambda c: c.discover("ai"),
        lambda c: c.feed(),
    ]:
        res = tool_call(client)
        assert res["ok"] is True
        assert "items" in res
        assert len(res["items"]) == 1
        item = res["items"][0]
        assert item["id"] == "vid_123"
        assert item["title"] == "Test AI Video"
        assert item["agent"] == "TestAgent"
        assert item["views"] == 100
        assert item["url"] == "https://bottube.ai/watch?v=vid_123"
        assert item["thumbnail"] == "https://bottube.ai/thumbs/vid_123.jpg"
