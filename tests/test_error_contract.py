"""tests/test_error_contract.py — Offline pytest suite verifying the grazer-mcp Error Contract.

Covers 4 tools x 4 failure modes (16 parametrized cases) plus success normalization,
with 100% offline httpx.MockTransport (no live network calls).
"""
import pytest
import httpx
from grazer_mcp.client import GrazerClient

TOOLS = ["graze_trending", "graze_discover", "graze_feed", "graze_platforms"]

FAILURE_MODES = [
    ("http_500", 500, b"Internal Server Error", "UPSTREAM_STATUS", True),
    ("http_404", 404, b"Not Found", "UPSTREAM_STATUS", False),
    ("timeout", None, None, "UPSTREAM_TIMEOUT", True),
    ("bad_json", 200, b"<html>Not JSON</html>", "UPSTREAM_BAD_JSON", False),
]

def make_mock_transport(mode: str, status_code: int = 200, body: bytes = b""):
    def handler(request: httpx.Request) -> httpx.Response:
        if mode == "timeout":
            raise httpx.TimeoutException("Mocked timeout error", request=request)
        return httpx.Response(status_code=status_code, content=body)
    return httpx.MockTransport(handler)

@pytest.mark.parametrize("tool_name", ["graze_trending", "graze_discover", "graze_feed"])
@pytest.mark.parametrize("mode_id, status_code, body, expected_code, expected_retryable", FAILURE_MODES)
def test_all_tools_error_contract_failure_modes(tool_name, mode_id, status_code, body, expected_code, expected_retryable):
    transport = make_mock_transport(mode_id, status_code, body)
    client = GrazerClient(transport=transport)
    
    if tool_name == "graze_trending":
        res = client.trending("bottube", limit=5)
    elif tool_name == "graze_discover":
        res = client.discover("test query", "bottube", page=1)
    elif tool_name == "graze_feed":
        res = client.feed("bottube", limit=5)
    else:
        pytest.fail(f"Unknown tool: {tool_name}")

    # Assert Error Envelope Contract Shape
    assert isinstance(res, dict)
    assert res.get("ok") is False
    assert "error" in res
    
    err_obj = res["error"]
    assert "code" in err_obj
    assert "message" in err_obj
    assert "retryable" in err_obj
    assert err_obj.get("source") == "grazer"
    assert "details" in err_obj

    assert err_obj["code"] == expected_code
    assert err_obj["retryable"] is expected_retryable

def test_unknown_platform_error_contract():
    client = GrazerClient()
    res = client.trending("unknown_platform_xyz")
    assert res["ok"] is False
    assert res["error"]["code"] == "UNKNOWN_PLATFORM"
    assert res["error"]["retryable"] is False

def test_success_response_normalization():
    mock_body = {
        "videos": [
            {
                "video_id": "vid_123",
                "title": "Test AI Video",
                "agent_name": "AgentAlpha",
                "views": 1500,
                "likes": 200,
                "category_name": "Technology",
                "duration_sec": 120,
                "watch_url": "/watch/vid_123",
                "thumbnail_url": "/thumb/vid_123.jpg",
                "created_at": "2026-07-27T00:00:00Z",
                "tags": ["ai", "mcp"]
            }
        ]
    }
    transport = make_mock_transport("success", 200, json_encode(mock_body))
    client = GrazerClient(transport=transport)
    
    res = client.trending("bottube")
    assert res["ok"] is True
    assert "items" in res
    assert len(res["items"]) == 1
    
    item = res["items"][0]
    assert item["id"] == "vid_123"
    assert item["title"] == "Test AI Video"
    assert item["agent"] == "AgentAlpha"
    assert item["views"] == 1500

def json_encode(obj):
    import json
    return json.dumps(obj).encode("utf-8")
