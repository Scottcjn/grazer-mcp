#!/usr/bin/env python3
"""Test error contract for all 4 tools x 4 failure modes.

Asserts every public GrazerClient method returns the documented
error envelope on backend failure.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from grazer_mcp.client import GrazerClient


def _mock(status: int = 200, text: str = "ok", exc: bool = False):
    """Return a transport-less client that raises or returns a stub response."""
    def handler(req):
        if exc:
            raise httpx.TimeoutException("simulated timeout")
        return httpx.Response(status, text=text)
    return GrazerClient(base_url="https://test.local", transport=httpx.MockTransport(handler))


ERROR_SHAPE  = {"ok": False, "error": {"code": str, "message": str, "retryable": bool,
                                        "source": "grazer", "details": dict}}
SUCCESS_SHAPE = {"ok": True}


def _check_envelope(r: dict, *, ok: bool):
    """Verify the response matches the documented envelope."""
    assert isinstance(r, dict), f"response must be a dict, got {type(r)}"
    if ok:
        assert r.get("ok") is True, f"expected ok=True, got {r}"
    else:
        assert r.get("ok") is False, f"expected ok=False, got {r}"
        e = r.get("error")
        assert isinstance(e, dict), f"error must be a dict, got {type(e)}"
        for key in ("code", "message", "retryable", "source", "details"):
            assert key in e, f"missing error.{key}"
        assert e["source"] == "grazer"
        assert isinstance(e["details"], dict)


def _check_success(fn, *a, **kw):
    r = fn(*a, **kw)
    _check_envelope(r, ok=True)
    return r


def _check_failure(fn, *a, **kw):
    r = fn(*a, **kw)
    _check_envelope(r, ok=False)
    return r


# --- platforms --- #

def test_platforms_no_error():
    r = _check_success(GrazerClient().platforms)
    assert "platforms" in r and "default" in r


def test_platforms_never_fails():
    # platforms() is the one tool that never hits the network
    r = GrazerClient().platforms()
    assert r.get("ok") is True


# --- trending --- #

def test_trending_http_500():
    r = _check_failure(_mock(500).trending)
    assert r["error"]["code"] == "UPSTREAM_STATUS"
    assert r["error"]["retryable"] is True


def test_trending_http_404():
    r = _check_failure(_mock(404).trending)
    assert r["error"]["code"] == "UPSTREAM_STATUS"
    assert r["error"]["retryable"] is False


def test_trending_timeout():
    r = _check_failure(_mock(exc=True).trending)
    assert r["error"]["code"] == "UPSTREAM_TIMEOUT"
    assert r["error"]["retryable"] is True


def test_trending_bad_json():
    r = _check_failure(_mock(text="<html>").trending)
    assert r["error"]["code"] == "UPSTREAM_BAD_JSON"
    assert r["error"]["retryable"] is False


# --- discover --- #

def test_discover_http_500():
    r = _check_failure(_mock(500).discover, "ai")
    assert r["error"]["code"] == "UPSTREAM_STATUS"
    assert r["error"]["retryable"] is True


def test_discover_http_404():
    r = _check_failure(_mock(404).discover, "ai")
    assert r["error"]["code"] == "UPSTREAM_STATUS"
    assert r["error"]["retryable"] is False


def test_discover_timeout():
    r = _check_failure(_mock(exc=True).discover, "ai")
    assert r["error"]["code"] == "UPSTREAM_TIMEOUT"
    assert r["error"]["retryable"] is True


def test_discover_bad_json():
    r = _check_failure(_mock(text="<html>").discover, "ai")
    assert r["error"]["code"] == "UPSTREAM_BAD_JSON"
    assert r["error"]["retryable"] is False


# --- feed (ranked) --- #

def test_feed_http_500():
    r = _check_failure(_mock(500).feed)
    assert r["error"]["code"] == "UPSTREAM_STATUS"
    assert r["error"]["retryable"] is True


def test_feed_http_404():
    r = _check_failure(_mock(404).feed)
    assert r["error"]["code"] == "UPSTREAM_STATUS"
    assert r["error"]["retryable"] is False


def test_feed_timeout():
    r = _check_failure(_mock(exc=True).feed)
    assert r["error"]["code"] == "UPSTREAM_TIMEOUT"
    assert r["error"]["retryable"] is True


def test_feed_bad_json():
    r = _check_failure(_mock(text="<html>").feed)
    assert r["error"]["code"] == "UPSTREAM_BAD_JSON"
    assert r["error"]["retryable"] is False


# --- discover empty query --- #

def test_discover_empty_query_maps_to_bad_request():
    r = _check_failure(GrazerClient().discover, "")
    assert r["error"]["code"] == "BAD_REQUEST"
    assert r["error"]["retryable"] is False


# --- unknown platform --- #

def test_unknown_platform_rejected():
    r = _check_failure(GrazerClient().trending, "myspace")
    assert r["error"]["code"] == "UNKNOWN_PLATFORM"
    assert r["error"]["retryable"] is False
    assert "supported" in r["error"]["details"]


if __name__ == "__main__":
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
    sys.exit(0 if ok == len(tests) else 1)