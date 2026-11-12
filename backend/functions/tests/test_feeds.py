"""Greenhouse, Lever and Ashby: one public JSON call returns every job with its description."""
import pytest

from job_alerts.adapters import ashby, greenhouse, lever
from job_alerts.adapters.ashby import AshbyAdapter
from job_alerts.adapters.base import AdapterError
from job_alerts.adapters.greenhouse import GreenhouseAdapter
from job_alerts.adapters.lever import LeverAdapter
from job_alerts.adapters.registry import build_adapter
from job_alerts.models import Company, JobSummary

GREENHOUSE_PAYLOAD = {
    "jobs": [
        {
            "id": 8172508,
            "title": "Software Engineer",
            "location": {"name": "Seattle, WA"},
            "absolute_url": "https://stripe.com/jobs/search?gh_jid=8172508",
            "content": "&lt;p&gt;Build &lt;b&gt;APIs&lt;/b&gt; &amp;amp; tools&lt;/p&gt;",
        }
    ]
}

LEVER_PAYLOAD = [
    {
        "id": "6ed76ce8",
        "text": "Forward Deployed Engineer",
        "categories": {"location": "Denver, CO", "allLocations": ["Denver, CO", "New York, NY"]},
        "country": "US",
        "hostedUrl": "https://jobs.lever.co/palantir/6ed76ce8",
        "descriptionPlain": "The Role",
        "lists": [{"text": "Requirements", "content": "<li>Python</li><li>Java</li>"}],
        "additionalPlain": "Benefits",
    }
]

ASHBY_PAYLOAD = {
    "jobs": [
        {
            "id": "34413f8d",
            "title": " Software Engineer, Backend ",
            "location": "New York, NY (HQ)",
            "secondaryLocations": [{"location": "Remote (US)"}],
            "isListed": True,
            "jobUrl": "https://jobs.ashbyhq.com/ramp/34413f8d",
            "descriptionPlain": "Build finance tools",
        },
        {"id": "hidden", "title": "Unlisted", "location": "NY", "isListed": False,
         "jobUrl": "https://jobs.ashbyhq.com/ramp/hidden", "descriptionPlain": "x"},
    ]
}


def _serve(monkeypatch, module, payload):
    monkeypatch.setattr(module, "fetch_json_value", lambda *args, **kwargs: payload)


def test_greenhouse_reads_jobs_and_unescapes_description(monkeypatch):
    _serve(monkeypatch, greenhouse, GREENHOUSE_PAYLOAD)
    adapter = GreenhouseAdapter("stripe", "stripe")
    [summary] = adapter.list_jobs()
    job = adapter.get_job(summary)
    assert (summary.id, summary.title, summary.location) == ("8172508", "Software Engineer", "Seattle, WA")
    assert job.url == "https://stripe.com/jobs/search?gh_jid=8172508"
    assert job.locations == ("Seattle, WA",)
    assert job.description_text == "Build APIs & tools"


def test_lever_joins_description_lists_and_marks_country(monkeypatch):
    _serve(monkeypatch, lever, LEVER_PAYLOAD)
    adapter = LeverAdapter("palantir", "palantir")
    [summary] = adapter.list_jobs()
    job = adapter.get_job(summary)
    assert summary.title == "Forward Deployed Engineer"
    assert job.locations == ("Denver, CO", "New York, NY", "US")
    assert job.url == "https://jobs.lever.co/palantir/6ed76ce8"
    assert job.description_text == "The Role\nRequirements\nPython\nJava\nBenefits"


def test_ashby_skips_unlisted_jobs_and_reads_secondary_locations(monkeypatch):
    _serve(monkeypatch, ashby, ASHBY_PAYLOAD)
    adapter = AshbyAdapter("ramp", "ramp")
    [summary] = adapter.list_jobs()
    job = adapter.get_job(summary)
    assert summary.title == "Software Engineer, Backend"
    assert job.locations == ("New York, NY (HQ)", "Remote (US)")
    assert job.description_text == "Build finance tools"


@pytest.mark.parametrize(
    ("module", "adapter_class", "payload"),
    [
        (greenhouse, GreenhouseAdapter, {"nope": []}),
        (lever, LeverAdapter, {"not": "a list"}),
        (ashby, AshbyAdapter, {"jobs": "broken"}),
    ],
)
def test_unexpected_shape_raises(monkeypatch, module, adapter_class, payload):
    _serve(monkeypatch, module, payload)
    with pytest.raises(AdapterError):
        adapter_class("c", "board").list_jobs()


@pytest.mark.parametrize(
    ("module", "adapter_class", "bad_payload"),
    [
        (greenhouse, GreenhouseAdapter, {"jobs": [{"title": "no id"}]}),
        (lever, LeverAdapter, [{"id": "x"}]),
        (ashby, AshbyAdapter, {"jobs": [{"id": "x", "isListed": True}]}),
    ],
)
def test_row_missing_id_title_or_url_raises(monkeypatch, module, adapter_class, bad_payload):
    _serve(monkeypatch, module, bad_payload)
    with pytest.raises(AdapterError):
        adapter_class("c", "board").list_jobs()


def test_get_job_for_unknown_id_raises(monkeypatch):
    _serve(monkeypatch, greenhouse, GREENHOUSE_PAYLOAD)
    adapter = GreenhouseAdapter("stripe", "stripe")
    adapter.list_jobs()
    with pytest.raises(AdapterError):
        adapter.get_job(JobSummary(id="999", title="x", location="", detail_ref="999"))


@pytest.mark.parametrize("ats", ["greenhouse", "lever", "ashby"])
def test_registry_builds_each_reader_and_requires_board(ats):
    assert build_adapter(Company(id="c", name="C", ats=ats, ats_config={"board": "acme"})) is not None
    with pytest.raises(AdapterError):
        build_adapter(Company(id="c", name="C", ats=ats, ats_config={}))
