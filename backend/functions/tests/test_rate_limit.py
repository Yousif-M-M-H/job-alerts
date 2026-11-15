"""A 429 is a temporary skip, not a red run."""
import pytest
import requests

from job_alerts.adapters.base import AdapterError, RateLimitedError
from job_alerts.adapters.http import fetch
from job_alerts.cli import exit_code


class _FakeSession:
    def __init__(self, status: int) -> None:
        self._status = status

    def request(self, method, url, **kwargs):
        response = requests.Response()
        response.status_code = self._status
        response.url = url
        return response


def test_429_raises_rate_limited_error():
    with pytest.raises(RateLimitedError):
        fetch(_FakeSession(429), "GET", "https://example.test/jobs")


def test_other_http_errors_stay_plain_adapter_errors():
    with pytest.raises(AdapterError) as caught:
        fetch(_FakeSession(500), "GET", "https://example.test/jobs")
    assert not isinstance(caught.value, RateLimitedError)


def test_a_one_off_failure_keeps_the_run_green():
    assert exit_code({"sel": False, "microsoft": True}, {}) == 0


def test_the_third_failure_in_a_row_turns_the_run_red():
    assert exit_code({"sel": False}, {"sel": 2}) == 1


def test_an_ongoing_outage_is_red_only_once():
    assert exit_code({"sel": False}, {"sel": 3}) == 0


def test_all_ok_is_green():
    assert exit_code({"sel": True}, {"sel": 5}) == 0
