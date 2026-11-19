"""A 429 is a temporary skip, not a red run."""
import pytest
import requests

from job_alerts.adapters.base import AdapterError, RateLimitedError
from job_alerts.adapters.http import fetch
from job_alerts.cli import exit_code
from job_alerts.models import PollResult


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


def test_429_is_not_retried():
    from job_alerts.adapters.http import build_session

    retry = build_session().get_adapter("https://example.test").max_retries
    assert 429 not in retry.status_forcelist
    assert 503 in retry.status_forcelist


def _company(company_id: str, ats: str):
    from job_alerts.models import Company, TitleLocationFilter

    return Company(company_id, company_id, ats, {}, TitleLocationFilter())


def test_after_a_429_other_boards_on_the_same_system_are_skipped():
    from job_alerts.cli import poll_all

    companies = [_company("sel", "workday"), _company("cat", "workday"), _company("schwab", "icims")]
    called: list[str] = []

    def poll_one(company):
        called.append(company.id)
        if company.ats == "workday":
            raise RateLimitedError("429")
        return PollResult(company.id)

    outcomes, _ = poll_all(companies, poll_one)
    assert called == ["sel", "schwab"]
    assert outcomes == {"sel": False, "cat": False, "schwab": True}


def test_other_failures_do_not_skip_the_rest():
    from job_alerts.cli import poll_all

    companies = [_company("sel", "workday"), _company("cat", "workday")]
    called: list[str] = []

    def poll_one(company):
        called.append(company.id)
        raise AdapterError("timeout")

    outcomes, _ = poll_all(companies, poll_one)
    assert called == ["sel", "cat"]
    assert outcomes == {"sel": False, "cat": False}


def test_only_a_few_boards_per_job_system_run_each_time():
    from job_alerts.cli import cap_per_ats

    companies = [_company(f"wd{n}", "workday") for n in range(5)] + [_company("schwab", "icims")]
    kept, deferred = cap_per_ats(companies, {"workday": 3})
    assert [c.id for c in kept] == ["wd0", "wd1", "wd2", "schwab"]
    assert [c.id for c in deferred] == ["wd3", "wd4"]
