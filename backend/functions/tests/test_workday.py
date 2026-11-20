"""Workday adapter against recorded API shapes, including the live quirks."""
import pytest

from job_alerts.adapters.base import AdapterError
from job_alerts.adapters.workday import PAGE_SIZE, WorkdayAdapter, html_to_text
from job_alerts.models import JobSummary


def row(number: int) -> dict:
    return {
        "title": f"Job {number}",
        "externalPath": f"/job/Idaho---Boise/Job_{number}-1",
        "locationsText": "Idaho - Boise",
        "bulletFields": [f"2026-{number}"],
    }


def adapter_with_pages(monkeypatch, responses: list[dict]) -> WorkdayAdapter:
    adapter = WorkdayAdapter("sel", "example.test", "tenant", "SITE")
    remaining = iter(responses)
    monkeypatch.setattr(adapter, "_request", lambda *args, **kwargs: next(remaining))
    return adapter


def test_list_paginates_when_later_pages_report_total_zero(monkeypatch):
    adapter = adapter_with_pages(
        monkeypatch,
        [
            {"total": PAGE_SIZE + 1, "jobPostings": [row(n) for n in range(PAGE_SIZE)]},
            {"total": 0, "jobPostings": [row(PAGE_SIZE)]},
        ],
    )
    assert len(adapter.list_jobs()) == PAGE_SIZE + 1


def test_list_uses_req_id_not_url_path(monkeypatch):
    adapter = adapter_with_pages(monkeypatch, [{"total": 1, "jobPostings": [row(7)]}])
    assert adapter.list_jobs()[0].id == "2026-7"


def test_list_skips_half_published_row(monkeypatch):
    broken = {"bulletFields": ["2026-24646"]}
    adapter = adapter_with_pages(monkeypatch, [{"total": 2, "jobPostings": [row(7), broken]}])
    assert [job.id for job in adapter.list_jobs()] == ["2026-7"]


def test_list_raises_rather_than_returning_partial_results(monkeypatch):
    adapter = adapter_with_pages(
        monkeypatch,
        [{"total": 5, "jobPostings": [row(1)]}, {"total": 0, "jobPostings": []}],
    )
    with pytest.raises(AdapterError):
        adapter.list_jobs()


def test_list_raises_on_unexpected_shape(monkeypatch):
    adapter = adapter_with_pages(monkeypatch, [{"error": "nope"}])
    with pytest.raises(AdapterError):
        adapter.list_jobs()


def test_get_job_combines_primary_and_additional_locations(monkeypatch):
    info = {
        "title": "Firmware Engineer",
        "location": "Idaho - Boise",
        "additionalLocations": ["Washington - Pullman"],
        "externalUrl": "https://example.test/job",
        "jobDescription": "<p>Write <b>C++</b></p><ul><li>Firmware</li></ul>",
        "startDate": "2026-11-05",
    }
    adapter = adapter_with_pages(monkeypatch, [{"jobPostingInfo": info}])
    job = adapter.get_job(JobSummary("2026-1", "x", "2 Locations", "/job/x"))
    assert job.locations == ("Idaho - Boise", "Washington - Pullman")
    assert job.description_text == "Write C++\nFirmware"


def test_html_to_text_decodes_entities():
    assert html_to_text("<p>R&amp;D team</p>") == "R&D team"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_requests_are_spaced_to_stay_under_the_burst_limit(monkeypatch):
    import job_alerts.adapters.workday as workday

    clock = FakeClock()
    monkeypatch.setattr(workday, "fetch_json_curl", lambda *args, **kwargs: {})
    adapter = WorkdayAdapter("sel", "example.test", "tenant", "SITE", clock=clock.time, sleep=clock.sleep)
    for _ in range(3):
        adapter._request("POST", "/jobs")
    assert clock.sleeps == [workday.REQUEST_INTERVAL_SECONDS] * 2


def test_no_wait_when_enough_time_already_passed(monkeypatch):
    import job_alerts.adapters.workday as workday

    clock = FakeClock()
    monkeypatch.setattr(workday, "fetch_json_curl", lambda *args, **kwargs: {})
    adapter = WorkdayAdapter("sel", "example.test", "tenant", "SITE", clock=clock.time, sleep=clock.sleep)
    adapter._request("POST", "/jobs")
    clock.now += workday.REQUEST_INTERVAL_SECONDS + 1
    adapter._request("GET", "/job/1")
    assert clock.sleeps == []
