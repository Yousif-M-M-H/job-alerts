"""SuccessFactors HTML parsing, using the markup seen on the live Landis+Gyr site."""
import pytest

from job_alerts.adapters.base import AdapterError
from job_alerts.adapters.successfactors import parse_detail_page, parse_list_page

LIST_PAGE = """
<span class="paginationLabel" aria-label="Results 1 – 25">Results <b>1 – 25</b> of <b>1,040</b></span>
<a class="jobTitle-link" href="/job/Lafayette-Engineer-I%2C-Firmware-IN/1445642133/">Engineer I, Firmware</a>
<a class="jobTitle-link" href="/job/Lafayette-Engineer-I%2C-Firmware-IN/1445642133/">Engineer I, Firmware</a>
<a class="jobTitle-link" href="/job/Alpharetta-R&amp;D-GA/99/">R&amp;D Lead</a>
"""


def test_list_page_dedupes_rows_and_reads_total():
    jobs, total = parse_list_page(LIST_PAGE)
    assert total == 1040
    assert [(job.id, job.title) for job in jobs] == [("1445642133", "Engineer I, Firmware"), ("99", "R&D Lead")]
    assert jobs[1].detail_ref == "/job/Alpharetta-R&D-GA/99/"


def test_list_page_without_total_returns_none():
    assert parse_list_page("<html>redesigned</html>") == ((), None)


def test_detail_page_keeps_nested_spans_and_stops_at_the_end():
    page = """
    <span class="jobGeoLocation">Alpharetta, GA, US</span>
    <span class="jobdescription"><p>Write <span>C#</span> &amp; Python</p></span>
    <span>Footer text</span>
    """
    assert parse_detail_page(page) == ("Alpharetta, GA, US", "Write C# & Python")


def test_detail_page_without_description_raises():
    with pytest.raises(AdapterError):
        parse_detail_page("<html></html>")
