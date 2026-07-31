"""
Error-contract tests for all four grazer-mcp tools.

Validates that graze_trending, graze_discover, graze_feed, and graze_platforms
return the documented error envelope {"ok": false, "error": {code, message,
retryable, source, details}} on every failure mode — never a silent empty result.

Run: pytest tests/test_error_contract.py -v
"""
import httpx
import pytest

from grazer_mcp.client import GrazerClient, PLATFORMS


# ── helpers ──────────────────────────────────────────────────────

VIDEO = {
    "id": "abc123", "title": "Test", "agent": "tester",
    "display_name": "Tester", "views": 10, "likes": 2,
    "category": "other", "category_name": "Other", "duration_sec": 5.0,
    "watch_url": "/watch/abc123", "thumbnail_url": "/thumbnails/abc123.jpg",
    "created_at": 1700000000.0, "tags": ["test"],
}


def _mock(handler, **kwargs):
    transport = httpx.MockTransport(handler)
    return GrazerClient(base_url="https://test.local", transport=transport, **kwargs)


def _500(req):
    return httpx.Response(500, text="Internal Server Error")

def _404(req):
    return httpx.Response(404, text="Not Found")

def _bad_json(req):
    return httpx.Response(200, text="<<not json>>")

def _timeout(req):
    raise httpx.TimeoutException("timeout")


# ── shape assertion ─────────────────────────────────────────────

def _assert_err(result, expected_code=None):
    assert isinstance(result, dict)
    assert result.get("ok") is False, f"ok should be False, got {result}"
    e = result.get("error")
    assert e is not None and isinstance(e, dict)
    assert "code" in e and isinstance(e["code"], str)
    assert "message" in e and isinstance(e["message"], str)
    assert "retryable" in e and isinstance(e["retryable"], bool)
    assert e.get("source") == "grazer", f"source={e.get('source')}"
    if expected_code:
        assert e["code"] == expected_code, f"expected {expected_code}, got {e['code']}"


# ── graze_platforms (local, no network) ─────────────────────────

class TestPlatforms:
    def test_always_succeeds(self):
        r = GrazerClient().platforms()
        assert r["ok"] is True
        assert r["platforms"] == PLATFORMS


# ── graze_trending: 4 failure modes ──────────────────────────────

class TestTrendingErrors:
    def test_http_500(self):
        r = _mock(_500).trending("bottube", 10)
        _assert_err(r, "UPSTREAM_HTTP_ERROR")
        assert r["error"]["retryable"] is True

    def test_timeout(self):
        r = _mock(_timeout, timeout=5.0).trending("bottube", 10)
        _assert_err(r, "UPSTREAM_TIMEOUT")
        assert r["error"]["retryable"] is True

    def test_malformed_json(self):
        r = _mock(_bad_json).trending("bottube", 10)
        _assert_err(r, "UPSTREAM_BAD_JSON")
        assert r["error"]["retryable"] is False

    def test_http_404(self):
        r = _mock(_404).trending("bottube", 10)
        _assert_err(r, "UPSTREAM_HTTP_ERROR")
        assert r["error"]["retryable"] is False


# ── graze_discover: 4 failure modes ──────────────────────────────

class TestDiscoverErrors:
    def test_http_500(self):
        r = _mock(_500).discover("query", "bottube", 1, 10)
        _assert_err(r, "UPSTREAM_HTTP_ERROR")
        assert r["error"]["retryable"] is True

    def test_timeout(self):
        r = _mock(_timeout, timeout=5.0).discover("query", "bottube", 1, 10)
        _assert_err(r, "UPSTREAM_TIMEOUT")
        assert r["error"]["retryable"] is True

    def test_malformed_json(self):
        r = _mock(_bad_json).discover("query", "bottube", 1, 10)
        _assert_err(r, "UPSTREAM_BAD_JSON")
        assert r["error"]["retryable"] is False

    def test_http_404(self):
        r = _mock(_404).discover("query", "bottube", 1, 10)
        _assert_err(r, "UPSTREAM_HTTP_ERROR")
        assert r["error"]["retryable"] is False


# ── graze_feed: 4 failure modes ──────────────────────────────────

class TestFeedErrors:
    def test_http_500(self):
        r = _mock(_500).feed("bottube", 10, True)
        _assert_err(r, "UPSTREAM_HTTP_ERROR")
        assert r["error"]["retryable"] is True

    def test_timeout(self):
        r = _mock(_timeout, timeout=5.0).feed("bottube", 10, True)
        _assert_err(r, "UPSTREAM_TIMEOUT")
        assert r["error"]["retryable"] is True

    def test_malformed_json(self):
        r = _mock(_bad_json).feed("bottube", 10, True)
        _assert_err(r, "UPSTREAM_BAD_JSON")
        assert r["error"]["retryable"] is False

    def test_http_404(self):
        r = _mock(_404).feed("bottube", 10, True)
        _assert_err(r, "UPSTREAM_HTTP_ERROR")
        assert r["error"]["retryable"] is False


# ── platform validation ─────────────────────────────────────────

class TestPlatformValidation:
    def test_bad_platform_trending(self):
        r = GrazerClient().trending("nonexistent", 10)
        _assert_err(r, "BAD_PLATFORM")
        assert r["error"]["retryable"] is False

    def test_bad_platform_discover(self):
        r = GrazerClient().discover("q", "nonexistent", 1, 10)
        _assert_err(r, "BAD_PLATFORM")
        assert r["error"]["retryable"] is False

    def test_bad_platform_feed(self):
        r = GrazerClient().feed("nonexistent", 10, True)
        _assert_err(r, "BAD_PLATFORM")
        assert r["error"]["retryable"] is False


# ── input validation ────────────────────────────────────────────

class TestInputValidation:
    def test_empty_query(self):
        r = GrazerClient().discover("", "bottube", 1, 10)
        _assert_err(r, "BAD_REQUEST")
        assert r["error"]["retryable"] is False

    def test_whitespace_query(self):
        r = GrazerClient().discover("   ", "bottube", 1, 10)
        _assert_err(r, "BAD_REQUEST")
        assert r["error"]["retryable"] is False


# ── error details ───────────────────────────────────────────────

class TestErrorDetails:
    def test_http_error_has_status(self):
        r = _mock(_500).trending("bottube", 10)
        _assert_err(r, "UPSTREAM_HTTP_ERROR")
        assert "status" in r["error"], f"status missing: {r['error']}"

    def test_bad_platform_lists_supported(self):
        r = GrazerClient().trending("bad", 10)
        _assert_err(r, "BAD_PLATFORM")
        d = r["error"].get("details", {})
        assert "supported" in d, f"supported missing: {d}"
        assert "bottube" in d["supported"]
