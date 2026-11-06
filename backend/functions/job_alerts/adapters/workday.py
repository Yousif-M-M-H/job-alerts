"""Workday public job board API (the JSON behind *.myworkdayjobs.com).

Behaviour seen on the live API:
- limit above 20 returns HTTP 400.
- 'total' is only filled on the first page; later pages say 0.
- The list can say '2 Locations', so real locations come from the detail call.
- URL paths can end in '-1', so the stable job ID is the req ID, not the path.
"""
from html.parser import HTMLParser
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..models import Company, Job, JobSummary
from .base import AdapterError

PAGE_SIZE = 20
TIMEOUT_SECONDS = 20
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.0
RETRY_STATUSES = (429, 500, 502, 503, 504)
USER_AGENT = "job-alerts/0.1"
BLOCK_TAGS = frozenset({"p", "br", "li", "div", "ul", "ol", "h1", "h2", "h3", "h4", "tr"})


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_to_text(html: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html)
    lines = (" ".join(line.split()) for line in "".join(extractor.parts).splitlines())
    return "\n".join(line for line in lines if line)


def _build_session() -> requests.Session:
    # POST is included because this POST is a read-only search.
    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=RETRY_BACKOFF_SECONDS,
        status_forcelist=RETRY_STATUSES,
        allowed_methods=frozenset({"GET", "POST"}),
        raise_on_status=False,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"Accept": "application/json", "User-Agent": USER_AGENT})
    return session


def _parse_summary(row: dict[str, Any]) -> JobSummary:
    title, path = row.get("title"), row.get("externalPath")
    if not title or not path:
        raise AdapterError(f"Workday row is missing title or externalPath: {row!r}")
    bullets = row.get("bulletFields") or []
    job_id = bullets[0] if bullets else path.rsplit("/", 1)[-1]
    return JobSummary(id=job_id, title=title, location=row.get("locationsText", ""), detail_ref=path)


class WorkdayAdapter:
    def __init__(self, company_id: str, host: str, tenant: str, site: str) -> None:
        self._company_id = company_id
        self._base_url = f"https://{host}/wday/cxs/{tenant}/{site}"
        self._session = _build_session()

    @classmethod
    def from_company(cls, company: Company) -> "WorkdayAdapter":
        config = company.ats_config
        missing = [key for key in ("host", "tenant", "site") if not config.get(key)]
        if missing:
            raise AdapterError(f"company '{company.id}': atsConfig is missing {missing}")
        return cls(company.id, config["host"], config["tenant"], config["site"])

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            response = self._session.request(method, url, timeout=TIMEOUT_SECONDS, **kwargs)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as error:
            raise AdapterError(f"Workday {method} {url} failed: {error}") from error
        if not isinstance(payload, dict):
            raise AdapterError(f"Workday {url} returned non-object JSON")
        return payload

    def _fetch_page(self, offset: int) -> dict[str, Any]:
        body = {"appliedFacets": {}, "limit": PAGE_SIZE, "offset": offset, "searchText": ""}
        payload = self._request("POST", "/jobs", json=body)
        if not isinstance(payload.get("jobPostings"), list):
            raise AdapterError(f"Workday page at offset {offset} has no jobPostings list")
        return payload

    def list_jobs(self) -> tuple[JobSummary, ...]:
        first_page = self._fetch_page(0)
        total = first_page.get("total") or 0
        rows = list(first_page["jobPostings"])
        while len(rows) < total:
            page_rows = self._fetch_page(len(rows))["jobPostings"]
            if not page_rows:
                break
            rows = [*rows, *page_rows]
        if len(rows) < total:
            raise AdapterError(f"Workday listed {len(rows)} of {total} jobs")
        return tuple(_parse_summary(row) for row in rows)

    def get_job(self, summary: JobSummary) -> Job:
        info = self._request("GET", summary.detail_ref).get("jobPostingInfo")
        if not isinstance(info, dict):
            raise AdapterError(f"Workday job {summary.id} has no jobPostingInfo")
        url = info.get("externalUrl")
        if not url:
            raise AdapterError(f"Workday job {summary.id} has no externalUrl")
        extra_locations = info.get("additionalLocations") or []
        locations = tuple(item for item in (info.get("location"), *extra_locations) if item)
        return Job(
            id=summary.id,
            company_id=self._company_id,
            title=info.get("title") or summary.title,
            locations=locations or (summary.location,),
            url=url,
            description_text=html_to_text(info.get("jobDescription") or ""),
            posted_on=info.get("startDate") or "",
        )
