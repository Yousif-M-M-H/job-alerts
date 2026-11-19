"""Workday throttles Python over HTTP/1.1 from GitHub's servers but not HTTP/2 (tested 2026-11-19)."""
import httpx
import pytest

from job_alerts.adapters.base import AdapterError, RateLimitedError
from job_alerts.adapters.http import USER_AGENT, build_http2_client, fetch_json_http2


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _no_sleep(seconds: float) -> None:
    return None


def test_http2_client_speaks_http2_and_identifies_itself():
    client = build_http2_client()
    assert client.headers["User-Agent"] == USER_AGENT
    assert client.headers["Accept"] == "application/json"
    assert client._transport._pool._http2 is True


def test_returns_the_json_object():
    client = _client(lambda request: httpx.Response(200, json={"total": 1}))
    assert fetch_json_http2(client, "POST", "https://example.test/jobs", json={}) == {"total": 1}


def test_429_raises_rate_limited_without_retrying():
    calls: list[int] = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429)

    with pytest.raises(RateLimitedError):
        fetch_json_http2(_client(handler), "GET", "https://example.test/jobs", sleep=_no_sleep)
    assert len(calls) == 1


def test_server_errors_are_retried_then_succeed():
    statuses = iter([503, 502, 200])
    client = _client(lambda request: httpx.Response(next(statuses), json={"ok": True}))
    assert fetch_json_http2(client, "GET", "https://example.test/jobs", sleep=_no_sleep) == {"ok": True}


def test_server_errors_that_never_clear_raise_adapter_error():
    client = _client(lambda request: httpx.Response(500))
    with pytest.raises(AdapterError) as caught:
        fetch_json_http2(client, "GET", "https://example.test/jobs", sleep=_no_sleep)
    assert not isinstance(caught.value, RateLimitedError)


def test_network_errors_become_adapter_errors():
    def handler(request):
        raise httpx.ConnectTimeout("timed out", request=request)

    with pytest.raises(AdapterError):
        fetch_json_http2(_client(handler), "GET", "https://example.test/jobs", sleep=_no_sleep)


def test_non_json_body_raises_adapter_error():
    client = _client(lambda request: httpx.Response(200, text="<html>", headers={"Content-Type": "text/html"}))
    with pytest.raises(AdapterError, match="did not return JSON"):
        fetch_json_http2(client, "GET", "https://example.test/jobs")


def test_json_list_raises_adapter_error():
    client = _client(lambda request: httpx.Response(200, json=[1, 2]))
    with pytest.raises(AdapterError, match="non-object"):
        fetch_json_http2(client, "GET", "https://example.test/jobs")
