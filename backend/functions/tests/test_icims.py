"""iCIMS HTML parsing, using the markup seen on the live Charles Schwab board."""
import pytest

from job_alerts.adapters import icims
from job_alerts.adapters.base import AdapterError
from job_alerts.adapters.icims import IcimsAdapter, parse_detail_page, parse_list_page
from job_alerts.models import JobSummary


def _card(job_id: str, title: str, locations: str) -> str:
    return f"""
<li class="iCIMS_JobCardItem">
<div class="col-xs-6 header left">
<span class="sr-only field-label">Job Locations</span>
<span >
{locations}</span>
</div>
<div class="col-xs-12 title">
<a href="https://career-schwab.icims.com/jobs/{job_id}/some-slug/job?in_iframe=1" class="iCIMS_Anchor" title="{job_id} - x">
<span class="sr-only field-label">Job Posting Title</span>
<h3 >
{title}</h3>
</a>
</div>
</li>"""


def _list_page(cards: str, page: int, pages: int) -> str:
    return f'<div>Page {page} of {pages}</div><ul>{cards}</ul>'


LIST_PAGE = _list_page(
    _card("127182", "Senior Full Stack Engineer C#.NET", "US-TX-Southlake | US-TX-Austin")
    + _card("127183", "Manager, R&amp;D", "US-NE-Omaha"),
    page=1,
    pages=7,
)


def test_list_page_reads_ids_titles_locations_and_page_count():
    jobs, pages = parse_list_page(LIST_PAGE)
    assert pages == 7
    assert [(job.id, job.title, job.location) for job in jobs] == [
        ("127182", "Senior Full Stack Engineer C#.NET", "US-TX-Southlake; US-TX-Austin"),
        ("127183", "Manager, R&D", "US-NE-Omaha"),
    ]
    assert jobs[0].detail_ref == "127182"


def test_list_page_without_page_count_returns_none():
    assert parse_list_page("<html>redesigned</html>") == ((), None)


def test_detail_page_reads_only_the_job_sections():
    page = """
    <div class="iCIMS_InfoMsg iCIMS_InfoMsg_Job"><p>Build <b>C#</b> &amp; Python</p></div>
    <div class="iCIMS_InfoMsg iCIMS_InfoMsg_Job"><ul><li>3 years</li></ul></div>
    <div class="iCIMS_InfoMsg iCIMS_InfoMsg_Connect"><p>Benefits text</p></div>
    """
    assert parse_detail_page(page) == "Build C# & Python\n3 years"


def test_detail_page_without_description_raises():
    with pytest.raises(AdapterError):
        parse_detail_page("<html></html>")


def test_list_jobs_pages_until_the_last_page(monkeypatch):
    pages = {0: _list_page(_card("1", "Software Engineer", "US-TX-Austin"), 1, 2),
             1: _list_page(_card("2", "Developer", "US-CO-Denver"), 2, 2)}
    requested: list[int] = []

    def fake_get(self, path, **kwargs):
        requested.append(kwargs["params"]["pr"])
        return pages[kwargs["params"]["pr"]]

    monkeypatch.setattr(IcimsAdapter, "_get_html", fake_get)
    monkeypatch.setattr(icims, "PAGE_DELAY_SECONDS", 0)
    jobs = IcimsAdapter("schwab", "career-schwab.icims.com", "").list_jobs()
    assert [job.id for job in jobs] == ["1", "2"]
    assert requested == [0, 1]


def test_list_jobs_raises_rather_than_returning_partial_list(monkeypatch):
    monkeypatch.setattr(IcimsAdapter, "_get_html", lambda self, path, **kwargs: _list_page("", 1, 3))
    monkeypatch.setattr(icims, "PAGE_DELAY_SECONDS", 0)
    with pytest.raises(AdapterError):
        IcimsAdapter("schwab", "career-schwab.icims.com", "").list_jobs()


def test_get_job_builds_public_url(monkeypatch):
    page = '<div class="iCIMS_InfoMsg iCIMS_InfoMsg_Job"><p>Write code</p></div>'
    monkeypatch.setattr(IcimsAdapter, "_get_html", lambda self, path, **kwargs: page)
    summary = JobSummary(id="127182", title="Engineer", location="US-TX-Austin; US-TX-Southlake", detail_ref="127182")
    job = IcimsAdapter("schwab", "career-schwab.icims.com", "").get_job(summary)
    assert job.url == "https://career-schwab.icims.com/jobs/127182/job"
    assert job.locations == ("US-TX-Austin", "US-TX-Southlake")
    assert job.description_text == "Write code"
