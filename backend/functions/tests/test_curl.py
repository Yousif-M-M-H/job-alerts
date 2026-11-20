"""Workday throttles Python HTTP clients from GitHub's servers but not curl.

Tested 2026-11-19 on 3 servers, 10 requests per client: curl 60/60 got 200; requests and httpx
(HTTP/1.1 and HTTP/2) got 429 on 77 of 90. Same headers, same User-Agent.
"""
import json
import subprocess

import pytest

from job_alerts.adapters.base import AdapterError, RateLimitedError
from job_alerts.adapters.http import USER_AGENT, fetch_json_curl


def _no_sleep(seconds: float) -> None:
    return None


def _fake_curl(*responses: tuple[int, str], returncode: int = 0, calls: list | None = None):
    remaining = iter(responses)

    def run(args, **kwargs):
        if calls is not None:
            calls.append((args, kwargs))
        status, body = next(remaining)
        return subprocess.CompletedProcess(args, returncode, stdout=f"{body}\n{status}", stderr="curl: (28) timed out")

    return run


def test_posts_json_with_our_user_agent_and_returns_the_object():
    calls: list = []
    run = _fake_curl((200, '{"total": 1}'), calls=calls)
    assert fetch_json_curl("POST", "https://example.test/jobs", json={"limit": 20}, run=run) == {"total": 1}
    args, kwargs = calls[0]
    assert args[0] == "curl"
    assert args[args.index("-A") + 1] == USER_AGENT
    assert args[args.index("-X") + 1] == "POST"
    assert "Content-Type: application/json" in args
    assert json.loads(kwargs["input"]) == {"limit": 20}
    assert args[-1] == "https://example.test/jobs"


def test_get_sends_no_body():
    calls: list = []
    fetch_json_curl("GET", "https://example.test/job/1", run=_fake_curl((200, "{}"), calls=calls))
    args, kwargs = calls[0]
    assert kwargs.get("input") is None
    assert "Content-Type: application/json" not in args


def test_429_raises_rate_limited_without_retrying():
    calls: list = []
    with pytest.raises(RateLimitedError):
        fetch_json_curl("GET", "https://example.test/jobs", run=_fake_curl((429, ""), (200, "{}"), calls=calls), sleep=_no_sleep)
    assert len(calls) == 1


def test_server_errors_are_retried_then_succeed():
    run = _fake_curl((503, ""), (502, ""), (200, '{"ok": true}'))
    assert fetch_json_curl("GET", "https://example.test/jobs", run=run, sleep=_no_sleep) == {"ok": True}


def test_server_errors_that_never_clear_raise_adapter_error():
    run = _fake_curl(*[(500, "")] * 10)
    with pytest.raises(AdapterError) as caught:
        fetch_json_curl("GET", "https://example.test/jobs", run=run, sleep=_no_sleep)
    assert not isinstance(caught.value, RateLimitedError)


def test_other_http_errors_raise_adapter_error():
    with pytest.raises(AdapterError, match="HTTP 404"):
        fetch_json_curl("GET", "https://example.test/jobs", run=_fake_curl((404, "")))


def test_curl_failure_becomes_adapter_error():
    with pytest.raises(AdapterError, match="timed out"):
        fetch_json_curl("GET", "https://example.test/jobs", run=_fake_curl((0, ""), returncode=28))


def test_missing_curl_becomes_adapter_error():
    def run(args, **kwargs):
        raise FileNotFoundError("curl")

    with pytest.raises(AdapterError, match="curl"):
        fetch_json_curl("GET", "https://example.test/jobs", run=run)


def test_non_json_body_raises_adapter_error():
    with pytest.raises(AdapterError, match="did not return JSON"):
        fetch_json_curl("GET", "https://example.test/jobs", run=_fake_curl((200, "<html>")))


def test_json_list_raises_adapter_error():
    with pytest.raises(AdapterError, match="non-object"):
        fetch_json_curl("GET", "https://example.test/jobs", run=_fake_curl((200, "[1, 2]")))
