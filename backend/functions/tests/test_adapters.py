"""Non-Workday adapters and the clearance/sponsorship rule."""
import json
from pathlib import Path

import pytest

from job_alerts.adapters import eightfold, ukg_pro, ukg_ready
from job_alerts.adapters.base import AdapterError
from job_alerts.adapters.eightfold import EightfoldAdapter
from job_alerts.adapters.registry import build_adapter
from job_alerts.adapters.ukg_pro import UkgProAdapter, parse_detail_html
from job_alerts.adapters.ukg_ready import UkgReadyAdapter
from job_alerts.config import parse_companies
from job_alerts.filters import has_dealbreaker
from job_alerts.models import Company, Job, JobSummary
from job_alerts.pipeline import poll_company
from job_alerts.store.json_store import JsonStore


def replay(monkeypatch, module, responses):
    remaining = iter(responses)
    monkeypatch.setattr(module, "fetch_json", lambda *args, **kwargs: next(remaining))


def test_eightfold_uses_display_id_and_stops_at_empty_page(monkeypatch):
    row = {"displayJobId": "200", "id": 197, "name": "Software Engineer", "locations": ["Redmond"]}
    replay(monkeypatch, eightfold, [{"data": {"positions": [row]}}, {"data": {"positions": []}}])
    monkeypatch.setattr(eightfold.time, "sleep", lambda seconds: None)
    jobs = EightfoldAdapter("ms", "x.test", "ms.com", "software", 5).list_jobs()
    assert [(job.id, job.detail_ref) for job in jobs] == [("200", "197")]


def test_eightfold_raises_on_unexpected_shape(monkeypatch):
    replay(monkeypatch, eightfold, [{"data": {}}])
    with pytest.raises(AdapterError):
        EightfoldAdapter("ms", "x.test", "ms.com", "software", 5).list_jobs()


def test_ukg_pro_pages_until_total(monkeypatch):
    rows = [{"Id": f"id-{n}", "Title": "Dev", "Locations": []} for n in range(3)]
    replay(
        monkeypatch,
        ukg_pro,
        [{"opportunities": rows[:2], "totalCount": 3}, {"opportunities": rows[2:], "totalCount": 3}],
    )
    assert len(UkgProAdapter("mesa", "x.test", "T", "B").list_jobs()) == 3


def test_ukg_pro_raises_rather_than_returning_partial_list(monkeypatch):
    replay(
        monkeypatch,
        ukg_pro,
        [{"opportunities": [{"Id": "1", "Title": "Dev"}], "totalCount": 5}, {"opportunities": [], "totalCount": 5}],
    )
    with pytest.raises(AdapterError):
        UkgProAdapter("mesa", "x.test", "T", "B").list_jobs()


def test_ukg_pro_reads_details_embedded_in_html():
    detail = {"Title": "Dev", "Description": "<p>Uses ) and } safely</p>"}
    html = f"<script>new US.Opportunity.CandidateOpportunityDetail({json.dumps(detail)});</script>"
    assert parse_detail_html(html) == detail


def test_ukg_pro_raises_when_details_are_missing():
    with pytest.raises(AdapterError):
        parse_detail_html("<html></html>")


def test_ukg_ready_builds_job_from_list_row(monkeypatch):
    row = {
        "id": 537,
        "job_title": "Dev",
        "location": {"city": "Alpharetta", "state": "GA", "country": "USA"},
        "job_description": "<p>Python</p>",
    }
    replay(monkeypatch, ukg_ready, [{"job_requisitions": [row], "_paging": {"total": 1}}])
    adapter = UkgReadyAdapter("profisee", "x.test", "CODE")
    job = adapter.get_job(adapter.list_jobs()[0])
    assert job.id == "537" and job.locations == ("Alpharetta, GA, USA",)
    assert job.description_text == "Python" and job.url == "https://x.test/ta/CODE.careers?ShowJob=537"


def test_ukg_ready_unknown_job_raises():
    adapter = UkgReadyAdapter("profisee", "x.test", "CODE")
    with pytest.raises(AdapterError):
        adapter.get_job(JobSummary("9", "Dev", "", "9"))


def test_every_configured_company_builds_an_adapter():
    config = Path(__file__).resolve().parent.parent / "companies.json"
    companies = parse_companies(json.loads(config.read_text(encoding="utf-8")))
    assert all(build_adapter(company) for company in companies)


@pytest.mark.parametrize(
    "text",
    [
        "Must hold an active Top Secret clearance.",
        "Active TS/SCI security clearance required",
        "Current DoD secret clearance",
        "We do not sponsor work visas.",
        "This role will not provide visa sponsorship.",
        "We are unable to sponsor applicants.",
        "Must be authorized to work without employer sponsorship.",
        "Sponsorship is not available for this position.",
    ],
)
def test_dealbreaker_phrases_are_detected(text):
    assert has_dealbreaker(text)


@pytest.mark.parametrize(
    "text",
    [
        "Build Python services on Azure.",
        "Ability to obtain a security clearance.",
        "We offer visa sponsorship.",
        "Active member of a team. Clearance sale.",
    ],
)
def test_normal_postings_are_not_dealbreakers(text):
    assert not has_dealbreaker(text)


class _Adapter:
    def __init__(self, description):
        self.description = description

    def list_jobs(self):
        return (JobSummary("1", "Software Engineer", "Boise", "1"),)

    def get_job(self, summary):
        return Job("1", "x", summary.title, ("Boise, ID",), "https://x.test", self.description)


COMPANY = Company("x", "X", "workday", {})


def _poll_new_job(tmp_path, description, scorer):
    store, alerts = JsonStore(tmp_path / "s.json"), []
    store.mark_baselined("x", ())
    send = lambda company, job, score: alerts.append(job.id)
    return poll_company(COMPANY, _Adapter(description), store, scorer, send), alerts, store


def test_dealbreaker_phrase_skips_alert_and_scoring(tmp_path):
    def scorer(job):
        raise AssertionError("should not score")

    result, alerts, store = _poll_new_job(tmp_path, "We do not sponsor visas.", scorer)
    assert alerts == [] and result.rejected_dealbreaker == ("1",) and "1" in store.seen_ids("x")


def test_dealbreaker_from_scorer_skips_even_with_high_score(tmp_path):
    from job_alerts.models import JobScore

    result, alerts, _ = _poll_new_job(tmp_path, "US citizens only.", lambda job: JobScore(95, "fit", True))
    assert alerts == [] and result.rejected_dealbreaker == ("1",)


def test_failed_scoring_still_applies_phrase_check(tmp_path):
    _, alerts, _ = _poll_new_job(tmp_path, "Active secret clearance needed.", lambda job: None)
    assert alerts == []


