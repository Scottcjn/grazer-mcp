#!/usr/bin/env python3
"""Error-contract tests for the four grazer MCP tools — no network (httpx MockTransport).

The README promises a stable contract for every tool: ``{"ok": true, ...}`` on
success, or a predictable ``{"ok": false, "error": {code, message, retryable,
source, details}}`` object — "never a silent empty result". ``test_client.py``
covers happy paths and a few individual failures; this module pins the *error
envelope itself* across all backend-failure modes, exercising the tools exactly
as an MCP host calls them (``grazer_mcp.server.graze_*``).

Failure modes covered for every backend-backed tool:
  * HTTP 500  -> UPSTREAM_STATUS, retryable=True   (status >= 500)
  * HTTP 404  -> UPSTREAM_STATUS, retryable=False   (client error)
  * timeout   -> UPSTREAM_TIMEOUT, retryable=True
  * bad body  -> UPSTREAM_BAD_JSON, retryable=False (non-JSON 200)

Contract note (README vs. code — see PR):
  ``graze_platforms`` is backend-free (``GrazerClient.platforms`` builds its
  result from the in-process ``PLATFORMS`` table and makes no HTTP call), so it
  *cannot* emit a backend error envelope. The README's "all 4 tools" wording is
  aspirational for it; the honest, tested behaviour is that it always returns the
  success contract. That is asserted below rather than papered over.

Run:  python3 -m pytest tests/test_error_contract.py -q
      python3 tests/test_error_contract.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
import pytest

from grazer_mcp import server
from grazer_mcp.client import GrazerClient

# A representative BoTTube video object (subset of the real fields), reused for
# the success-normalization assertions.
VIDEO = {
    "video_id": "9hq8hdFUbam", "id": 2167, "title": "Dust Bunny Elimination #2",
    "agent_name": "automatedjanitor2015", "display_name": "AutomatedJanitor2015",
    "views": 31, "likes": 8, "category_name": "Other",
    "duration_sec": 4.853, "watch_url": "/watch/9hq8hdFUbam",
    "thumbnail_url": "/thumbnails/9hq8hdFUbam.jpg", "created_at": 1782417722.7, "tags": ["ai"],
}

# The four tools as an MCP host sees them. `net` marks the ones that reach the
# backend (and can therefore produce a backend-error envelope).
ALL_TOOLS = ("graze_trending", "graze_discover", "graze_feed", "graze_platforms")
NET_TOOLS = ("graze_trending", "graze_discover", "graze_feed")


# --- mock-transport handlers, one per failure mode --- #
def _h_status(code):
    return lambda req: httpx.Response(code, text="backend error")


def _h_timeout(req):
    raise httpx.TimeoutException("slow")


def _h_bad_json(req):
    return httpx.Response(200, text="<html>not json</html>")


def _h_ok(req):
    # Every backend path returns {"videos": [...]}, which all three net tools read.
    return httpx.Response(200, json={"page": 1, "pages": 1, "total": 1,
                                     "mode": "heuristic", "videos": [VIDEO]})


# (mode-id, handler, expected code, expected retryable)
FAILURE_MODES = [
    ("http_500", _h_status(500), "UPSTREAM_STATUS", True),
    ("http_404", _h_status(404), "UPSTREAM_STATUS", False),
    ("timeout", _h_timeout, "UPSTREAM_TIMEOUT", True),
    ("bad_json", _h_bad_json, "UPSTREAM_BAD_JSON", False),
]


@pytest.fixture
def route(monkeypatch):
    """Point the server's shared client at an in-memory mock transport.

    Returns a setter so each test installs its own handler; the four MCP tool
    functions (``server.graze_*``) then run against it with no network.
    """
    def _install(handler):
        client = GrazerClient(base_url="https://test.local",
                              transport=httpx.MockTransport(handler))
        monkeypatch.setattr(server, "_client", client)
        return client
    return _install


def _call(tool_name, client_ok_needed=False):
    """Invoke a tool the way a host would, with valid arguments.

    ``graze_discover`` validates its query/platform *before* the backend call,
    so a real query is required to reach the transport-error paths under test.
    """
    fn = getattr(server, tool_name)
    if tool_name == "graze_discover":
        return fn(query="dust bunny")
    return fn()


def _assert_envelope(obj, *, code=None, retryable=None):
    """Assert the exact documented error envelope shape and values."""
    assert isinstance(obj, dict), f"tool returned {type(obj).__name__}, not a dict"
    assert obj.get("ok") is False, f"expected ok=False, got {obj.get('ok')!r}"
    assert set(obj) == {"ok", "error"}, f"unexpected top-level keys: {sorted(obj)}"

    err = obj["error"]
    assert isinstance(err, dict)
    # exact key set — no more, no less
    assert set(err) == {"code", "message", "retryable", "source", "details"}, (
        f"error keys drifted from contract: {sorted(err)}")
    assert isinstance(err["code"], str) and err["code"]
    assert isinstance(err["message"], str) and err["message"]
    assert isinstance(err["retryable"], bool)
    assert err["source"] == "grazer"
    assert isinstance(err["details"], dict)
    if code is not None:
        assert err["code"] == code, f"code {err['code']!r} != {code!r}"
    if retryable is not None:
        assert err["retryable"] is retryable, (
            f"retryable {err['retryable']!r} != {retryable!r} for {err['code']}")


# --- 1. every backend-backed tool x every failure mode (3 x 4 = 12 cases) --- #
@pytest.mark.parametrize("tool", NET_TOOLS)
@pytest.mark.parametrize("mode,handler,code,retryable",
                         FAILURE_MODES, ids=[m[0] for m in FAILURE_MODES])
def test_error_envelope_across_tools_and_modes(route, tool, mode, handler, code, retryable):
    route(handler)
    _assert_envelope(_call(tool), code=code, retryable=retryable)


# --- 2. retryable semantics stated plainly (README: True for 5xx/timeout) --- #
@pytest.mark.parametrize("tool", NET_TOOLS)
def test_5xx_is_retryable(route, tool):
    route(_h_status(502))
    assert _call(tool)["error"]["retryable"] is True


@pytest.mark.parametrize("tool", NET_TOOLS)
def test_4xx_is_not_retryable(route, tool):
    route(_h_status(400))
    assert _call(tool)["error"]["retryable"] is False


# --- 3. graze_platforms: backend-free -> always the success contract --- #
def test_platforms_is_backend_free_and_never_errors(route):
    # Even with a transport that 500s / times out for everyone else, platforms
    # never touches it: it must still return the ok=True contract.
    route(_h_status(500))
    r = server.graze_platforms()
    assert r["ok"] is True
    assert "bottube" in r["platforms"] and r["default"] == "bottube"
    assert "error" not in r


# --- 4. input-validation errors also honour the envelope --- #
def test_discover_missing_query_envelope(route):
    route(_h_ok)  # backend healthy; rejection must be pre-network
    _assert_envelope(server.graze_discover(query="   "),
                     code="BAD_REQUEST", retryable=False)


@pytest.mark.parametrize("tool", ("graze_trending", "graze_feed"))
def test_unknown_platform_envelope(route, tool):
    route(_h_ok)
    obj = getattr(server, tool)(platform="myspace")
    _assert_envelope(obj, code="UNKNOWN_PLATFORM", retryable=False)
    assert "bottube" in obj["error"]["details"]["supported"]


def test_discover_unknown_platform_envelope(route):
    route(_h_ok)
    _assert_envelope(server.graze_discover(query="ai", platform="myspace"),
                     code="UNKNOWN_PLATFORM", retryable=False)


# --- 5. success path still normalizes to the documented video shape --- #
@pytest.mark.parametrize("tool", NET_TOOLS)
def test_success_normalizes_video_shape(route, tool):
    route(_h_ok)
    r = _call(tool)
    assert r["ok"] is True and r["count"] == 1
    item = r["items"][0]
    # documented common shape {id, title, agent, views, ...}
    for key in ("id", "title", "agent", "views", "likes", "category",
                "duration_sec", "url", "thumbnail", "created_at", "tags"):
        assert key in item, f"normalized item missing {key!r}"
    assert item["id"] == "9hq8hdFUbam"
    assert item["title"] == "Dust Bunny Elimination #2"
    assert item["agent"] == "automatedjanitor2015"
    assert item["views"] == 31
    # relative BoTTube paths are absolutized against base_url
    assert item["url"] == "https://test.local/watch/9hq8hdFUbam"
    assert item["thumbnail"] == "https://test.local/thumbnails/9hq8hdFUbam.jpg"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
