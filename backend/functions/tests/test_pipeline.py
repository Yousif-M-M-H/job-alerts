"""Dedupe, baseline and retry behaviour, using a fake adapter and the real JSON store."""
from pathlib import Path

import pytest
import requests

from job_alerts.adapters.base import AdapterError
from job_alerts.filters import passes_location, passes_title
from job_alerts.models import Company, Job, JobSummary, TitleLocationFilter
from job_alerts.notify.base import NotifyError
from job_alerts.notify.telegram import TelegramNotifier, format_alert
from job_alerts.pipeline import poll_company as run_poll
from job_alerts.store.json_store import JsonStore


def poll_company(company, adapter, store, notify=lambda company, job: None):
    return run_poll(company, adapter, store, notify)

RULES = TitleLocationFilter(
    title_include=("software", "engineer"),
    title_exclude=("mechanical",),
    locations=("Boise",),
)
COMPANY = Company("sel", "SEL", "workday", {}, RULES)


def summary(job_id: str, title: str = "Software Engineer") -> JobSummary:
    return JobSummary(job_id, title, "Idaho - Boise", f"/job/{job_id}")


class FakeAdapter:
    def __init__(self, jobs, failing=(), locations=("Idaho - Boise",)):
        self.jobs, self.failing, self.locations = tuple(jobs), set(failing), locations
        self.detail_calls: list[str] = []

    def list_jobs(self):
        return self.jobs

    def get_job(self, job_summary):
        self.detail_calls.append(job_summary.id)
        if job_summary.id in self.failing:
            raise AdapterError("boom")
        return Job(job_summary.id, "sel", job_summary.title, self.locations, "https://x.test", "text")


@pytest.fixture
def store(tmp_path: Path) -> JsonStore:
    return JsonStore(tmp_path / "state.json")


def test_first_poll_is_baseline_with_no_candidates(store):
    result = poll_company(COMPANY, FakeAdapter([summary("1"), summary("2")]), store)
    assert result.is_baseline and result.candidates == ()
    assert store.seen_ids("sel") == {"1", "2"}


def test_new_job_is_candidate_once_and_never_again(store):
    poll_company(COMPANY, FakeAdapter([summary("1")]), store)
    adapter = FakeAdapter([summary("1"), summary("2")])
    assert [job.id for job in poll_company(COMPANY, adapter, store).candidates] == ["2"]
    assert poll_company(COMPANY, adapter, store).candidates == ()


def test_removed_then_reposted_job_does_not_return(store):
    poll_company(COMPANY, FakeAdapter([summary("1")]), store)
    poll_company(COMPANY, FakeAdapter([]), store)
    assert poll_company(COMPANY, FakeAdapter([summary("1")]), store).candidates == ()


def test_duplicate_rows_in_one_list_give_one_candidate(store):
    poll_company(COMPANY, FakeAdapter([]), store)
    result = poll_company(COMPANY, FakeAdapter([summary("1"), summary("1")]), store)
    assert len(result.candidates) == 1


def test_title_reject_skips_detail_fetch(store):
    poll_company(COMPANY, FakeAdapter([]), store)
    adapter = FakeAdapter([summary("1", "Mechanical Engineer")])
    result = poll_company(COMPANY, adapter, store)
    assert result.rejected_title == ("1",) and adapter.detail_calls == []


def test_location_reject_uses_detail_locations(store):
    poll_company(COMPANY, FakeAdapter([]), store)
    adapter = FakeAdapter([summary("1")], locations=("Washington - Pullman",))
    assert poll_company(COMPANY, adapter, store).rejected_location == ("1",)


def test_failed_detail_retries_next_poll(store):
    poll_company(COMPANY, FakeAdapter([]), store)
    failed = poll_company(COMPANY, FakeAdapter([summary("1")], failing=["1"]), store)
    assert failed.failed_ids == ("1",) and failed.candidates == ()
    retried = poll_company(COMPANY, FakeAdapter([summary("1")]), store)
    assert [job.id for job in retried.candidates] == ["1"]


def test_baseline_sends_no_alerts(store):
    alerts = []
    poll_company(COMPANY, FakeAdapter([summary("1")]), store, lambda company, job: alerts.append(job.id))
    assert alerts == []


def test_new_job_alerts_exactly_once(store):
    alerts = []
    send = lambda company, job: alerts.append(job.id)
    poll_company(COMPANY, FakeAdapter([]), store, send)
    adapter = FakeAdapter([summary("1")])
    poll_company(COMPANY, adapter, store, send)
    poll_company(COMPANY, adapter, store, send)
    assert alerts == ["1"]


def test_failed_alert_stays_unseen_and_retries(store):
    def fail(company, job):
        raise NotifyError("down")

    poll_company(COMPANY, FakeAdapter([]), store)
    failed = poll_company(COMPANY, FakeAdapter([summary("1")]), store, fail)
    assert failed.failed_ids == ("1",) and "1" not in store.seen_ids("sel")
    assert [job.id for job in poll_company(COMPANY, FakeAdapter([summary("1")]), store).candidates] == ["1"]


def test_one_failed_alert_does_not_block_others(store):
    def fail_first(company, job):
        if job.id == "1":
            raise NotifyError("down")

    poll_company(COMPANY, FakeAdapter([]), store)
    result = poll_company(COMPANY, FakeAdapter([summary("1"), summary("2")]), store, fail_first)
    assert result.failed_ids == ("1",) and [job.id for job in result.candidates] == ["2"]


def test_alert_has_title_company_location_and_link():
    job = Job("1", "sel", "Firmware Engineer", ("Idaho - Boise", "Utah"), "https://x.test/1", "text")
    assert format_alert(COMPANY, job) == "Firmware Engineer\nSEL · Idaho - Boise; Utah\nhttps://x.test/1"


def test_telegram_error_never_contains_token(monkeypatch):
    def explode(url, **kwargs):
        raise requests.ConnectionError(f"could not reach {url}")

    monkeypatch.setattr(requests, "post", explode)
    job = Job("1", "sel", "T", ("L",), "https://x.test", "text")
    with pytest.raises(NotifyError) as caught:
        TelegramNotifier("SECRET-TOKEN", "1")(COMPANY, job)
    assert "SECRET-TOKEN" not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


def test_failed_list_leaves_state_untouched(store):
    class DownAdapter(FakeAdapter):
        def list_jobs(self):
            raise AdapterError("down")

    with pytest.raises(AdapterError):
        poll_company(COMPANY, DownAdapter([]), store)
    assert not store.is_baselined("sel")


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Software Engineer", True),
        ("Firmware Engineer", True),
        ("Mechanical Engineer", False),
        ("Engineering Support Specialist", False),
        ("Customer Service Representative", False),
    ],
)
def test_title_filter(title, expected):
    assert passes_title(title, RULES) is expected


def test_title_always_beats_exclude():
    rules = TitleLocationFilter(
        title_include=("engineer",), title_exclude=("protection", "power"), title_always=("firmware", "software")
    )
    assert passes_title("Firmware Engineer - Protection Systems Platforms", rules)
    assert passes_title("Power Systems Software Engineer", rules)
    assert not passes_title("Power Systems Protection Engineer", rules)


def test_empty_location_filter_allows_all():
    assert passes_location(["Anywhere"], TitleLocationFilter())
