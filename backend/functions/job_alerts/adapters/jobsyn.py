"""DirectEmployers job sites (the search API behind e.g. careers.alaskaair.com).

Behaviour seen on the live API:
- The site is chosen by the x-origin header; pages are 1-based and always 10 jobs (num_items is ignored).
- Featured jobs come in a separate list and may be missing from 'jobs', so both are read.
- The list already has each full description, so get_job needs no request.
- https://<site>/<guid>/job/ redirects to the full job page.
"""
from typing import Any

from ..models import Company, Job, JobSummary
from .base import AdapterError
from .http import build_session, fetch_json

SEARCH_URL = "https://prod-search-api.jobsyn.org/api/v1/solr/search"
MAX_PAGES = 100


def _row_location(row: dict[str, Any]) -> str:
    location, country = row.get("location_exact") or "", row.get("country_exact") or ""
    return ", ".join(part for part in (location, country) if part)


class JobsynAdapter:
    def __init__(self, company_id: str, site: str) -> None:
        self._company_id = company_id
        self._site = site
        self._session = build_session()
        self._rows_by_id: dict[str, dict[str, Any]] = {}

    @classmethod
    def from_company(cls, company: Company) -> "JobsynAdapter":
        site = company.ats_config.get("site")
        if not site:
            raise AdapterError(f"company '{company.id}': atsConfig is missing ['site']")
        return cls(company.id, site)

    def _fetch_page(self, page: int) -> dict[str, Any]:
        payload = fetch_json(
            self._session, "GET", SEARCH_URL,
            params={"q": "", "page": page}, headers={"x-origin": self._site},
        )
        if not isinstance(payload.get("jobs"), list) or not isinstance(payload.get("pagination"), dict):
            raise AdapterError(f"jobsyn page {page} has no jobs list or pagination")
        return payload

    def list_jobs(self) -> tuple[JobSummary, ...]:
        first = self._fetch_page(1)
        total = first["pagination"].get("total") or 0
        total_pages = min(int(first["pagination"].get("total_pages") or 1), MAX_PAGES)
        pages = [first, *(self._fetch_page(page) for page in range(2, total_pages + 1))]
        rows_by_id: dict[str, dict[str, Any]] = {}
        for payload in pages:
            for row in (*payload["jobs"], *(payload.get("featured_jobs") or ())):
                guid = row.get("guid")
                if guid and row.get("title_exact") and guid not in rows_by_id:
                    rows_by_id[guid] = row
        if len(rows_by_id) < total:
            raise AdapterError(f"jobsyn listed {len(rows_by_id)} of {total} jobs")
        self._rows_by_id = rows_by_id
        return tuple(
            JobSummary(id=guid, title=row["title_exact"], location=_row_location(row), detail_ref=guid)
            for guid, row in rows_by_id.items()
        )

    def get_job(self, summary: JobSummary) -> Job:
        row = self._rows_by_id.get(summary.id)
        if row is None:
            raise AdapterError(f"jobsyn job {summary.id} is not in the last list")
        company = row.get("company_exact") or ""
        return Job(
            id=summary.id,
            company_id=self._company_id,
            title=f"{summary.title} ({company})" if company else summary.title,
            locations=(summary.location,) if summary.location else (),
            url=f"https://{self._site}/{summary.id}/job/",
            description_text=row.get("description") or "",
            posted_on=row.get("date_new") or "",
        )
