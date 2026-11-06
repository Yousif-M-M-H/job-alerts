"""SAP SuccessFactors career sites, used by Landis+Gyr.

These sites have no public JSON feed, so this reads the public HTML pages.
A site redesign would raise AdapterError rather than silently finding nothing.
"""
import html as html_lib
import re
from html.parser import HTMLParser

from ..models import Company, Job, JobSummary
from .base import AdapterError
from .http import build_session, fetch, html_to_text

PAGE_SIZE = 25
_ROW = re.compile(r'class="jobTitle-link"\s+href="(/job/[^"]*?/(\d+)/?)"[^>]*>([^<]+)')
_TOTAL = re.compile(r"Results\s*<b>[^<]*</b>\s*of\s*<b>\s*([\d,]+)\s*</b>", re.IGNORECASE)
_LOCATION = re.compile(r'class="jobGeoLocation"[^>]*>([^<]+)')
_DESCRIPTION_CLASS = "jobdescription"


class _DescriptionExtractor(HTMLParser):
    """Collects the inner HTML of the description span, including nested spans."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self.depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.depth == 0:
            if tag == "span" and dict(attrs).get("class") == _DESCRIPTION_CLASS:
                self.depth = 1
            return
        if tag == "span":
            self.depth += 1
        self.parts.append(self.get_starttag_text() or "")

    def handle_endtag(self, tag: str) -> None:
        if self.depth == 0:
            return
        if tag == "span":
            self.depth -= 1
            if self.depth == 0:
                return
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self.depth:
            self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        if self.depth:
            self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self.depth:
            self.parts.append(f"&#{name};")


def parse_list_page(page: str) -> tuple[tuple[JobSummary, ...], int | None]:
    """Returns the page's unique jobs and the board total (None if not shown)."""
    by_id: dict[str, JobSummary] = {}
    for path, job_id, title in _ROW.findall(page):
        if job_id not in by_id:
            by_id[job_id] = JobSummary(id=job_id, title=html_lib.unescape(title).strip(), location="", detail_ref=html_lib.unescape(path))
    total = _TOTAL.search(page)
    return tuple(by_id.values()), int(total.group(1).replace(",", "")) if total else None


def parse_detail_page(page: str) -> tuple[str, str]:
    """Returns (location, description text)."""
    extractor = _DescriptionExtractor()
    extractor.feed(page)
    description = html_to_text("".join(extractor.parts))
    if not description:
        raise AdapterError("SuccessFactors job page has no description")
    location = _LOCATION.search(page)
    return (html_lib.unescape(location.group(1)).strip() if location else ""), description


class SuccessFactorsAdapter:
    def __init__(self, company_id: str, host: str) -> None:
        self._company_id = company_id
        self._base = f"https://{host}"
        self._session = build_session()

    @classmethod
    def from_company(cls, company: Company) -> "SuccessFactorsAdapter":
        host = company.ats_config.get("host")
        if not host:
            raise AdapterError(f"company '{company.id}': atsConfig is missing host")
        return cls(company.id, host)

    def _get_html(self, path: str, **kwargs) -> str:
        headers = {"Accept": "text/html"}
        return fetch(self._session, "GET", f"{self._base}{path}", headers=headers, **kwargs).text

    def list_jobs(self) -> tuple[JobSummary, ...]:
        summaries: tuple[JobSummary, ...] = ()
        row = 0
        while True:
            page_jobs, total = parse_list_page(self._get_html("/search/", params={"q": "", "startrow": row}))
            if total is None:
                raise AdapterError("SuccessFactors list page shows no total")
            summaries = (*summaries, *page_jobs)
            row += PAGE_SIZE
            if row >= total:
                return summaries
            if not page_jobs:
                raise AdapterError(f"SuccessFactors listed {len(summaries)} of {total} jobs")

    def get_job(self, summary: JobSummary) -> Job:
        location, description = parse_detail_page(self._get_html(summary.detail_ref))
        return Job(
            id=summary.id,
            company_id=self._company_id,
            title=summary.title,
            locations=(location,) if location else (),
            url=f"{self._base}{summary.detail_ref}",
            description_text=description,
        )
