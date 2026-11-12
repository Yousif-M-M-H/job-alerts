"""iCIMS career boards, used by Charles Schwab.

iCIMS has no public JSON feed, so this reads the public HTML pages (the in_iframe view,
which is plain server-rendered HTML). A redesign raises AdapterError rather than
silently finding nothing.
"""
import html as html_lib
import re
import time

from ..models import Company, Job, JobSummary
from .base import AdapterError
from .http import build_session, fetch, html_to_text

PAGE_DELAY_SECONDS = 0.5
MAX_PAGES = 40
_CARD_START = '<li class="iCIMS_JobCardItem">'
_PAGE_COUNT = re.compile(r"Page\s+\d+\s+of\s+(\d+)")
_LINK_AND_TITLE = re.compile(r'href="[^"]*/jobs/(\d+)/[^"]*"[^>]*>.*?<h3[^>]*>(.*?)</h3>', re.DOTALL)
_LOCATIONS = re.compile(r'Job Locations</span>\s*<span[^>]*>(.*?)</span>', re.DOTALL)
_JOB_SECTION = 'class="iCIMS_InfoMsg iCIMS_InfoMsg_Job"'
_SECTION_END = re.compile(r'class="iCIMS_InfoMsg iCIMS_InfoMsg_(?!Job")|class="iCIMS_JobOptions')


def _clean(raw: str) -> str:
    return " ".join(html_lib.unescape(raw).split())


def _parse_card(card: str) -> JobSummary | None:
    match = _LINK_AND_TITLE.search(card)
    if not match:
        return None
    job_id, title = match.group(1), _clean(match.group(2))
    location = _LOCATIONS.search(card)
    places = [_clean(place) for place in location.group(1).split("|")] if location else []
    return JobSummary(id=job_id, title=title, location="; ".join(p for p in places if p), detail_ref=job_id)


def parse_list_page(page: str) -> tuple[tuple[JobSummary, ...], int | None]:
    """Returns the page's jobs and the number of pages (None if not shown)."""
    cards = page.split(_CARD_START)[1:]
    jobs = tuple(job for job in (_parse_card(card) for card in cards) if job)
    count = _PAGE_COUNT.search(page)
    return jobs, int(count.group(1)) if count else None


def parse_detail_page(page: str) -> str:
    """Returns the description text: every 'Job' section, without the benefits boilerplate."""
    start = page.find(_JOB_SECTION)
    if start < 0:
        raise AdapterError("iCIMS job page has no description")
    end = _SECTION_END.search(page, start)
    body = page[page.rfind("<", 0, start): end.start() if end else len(page)]
    description = html_to_text(body)
    if not description:
        raise AdapterError("iCIMS job page has an empty description")
    return description


class IcimsAdapter:
    def __init__(self, company_id: str, host: str, search_keyword: str) -> None:
        self._company_id = company_id
        self._base = f"https://{host}"
        self._search_keyword = search_keyword
        self._session = build_session()

    @classmethod
    def from_company(cls, company: Company) -> "IcimsAdapter":
        config = company.ats_config
        if not config.get("host"):
            raise AdapterError(f"company '{company.id}': atsConfig is missing host")
        return cls(company.id, config["host"], config.get("searchKeyword", ""))

    def _get_html(self, path: str, **kwargs) -> str:
        headers = {"Accept": "text/html"}
        return fetch(self._session, "GET", f"{self._base}{path}", headers=headers, **kwargs).text

    def list_jobs(self) -> tuple[JobSummary, ...]:
        summaries: tuple[JobSummary, ...] = ()
        for page_index in range(MAX_PAGES):
            if page_index:
                time.sleep(PAGE_DELAY_SECONDS)
            params = {"ss": 1, "in_iframe": 1, "pr": page_index, "searchKeyword": self._search_keyword}
            page_jobs, page_count = parse_list_page(self._get_html("/jobs/search", params=params))
            if page_count is None:
                raise AdapterError(f"iCIMS page {page_index} shows no page count")
            if not page_jobs:
                raise AdapterError(f"iCIMS page {page_index + 1} of {page_count} has no jobs")
            summaries = (*summaries, *page_jobs)
            if page_index + 1 >= page_count:
                return summaries
        raise AdapterError(f"iCIMS board has more than {MAX_PAGES} pages")

    def get_job(self, summary: JobSummary) -> Job:
        path = f"/jobs/{summary.detail_ref}/job"
        description = parse_detail_page(self._get_html(path, params={"in_iframe": 1}))
        return Job(
            id=summary.id,
            company_id=self._company_id,
            title=summary.title,
            locations=tuple(place for place in summary.location.split("; ") if place),
            url=f"{self._base}{path}",
            description_text=description,
        )
