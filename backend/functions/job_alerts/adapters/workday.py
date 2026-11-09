"""Workday public job board API (the JSON behind *.myworkdayjobs.com).

Behaviour seen on the live API:
- limit above 20 returns HTTP 400.
- 'total' is only filled on the first page; later pages say 0.
- The list can say '2 Locations', so real locations come from the detail call.
- URL paths can end in '-1', so the stable job ID is the req ID, not the path.
"""
import logging
from typing import Any

from ..models import Company, Job, JobSummary
from .base import AdapterError
from .http import build_session, fetch_json, html_to_text

PAGE_SIZE = 20
logger = logging.getLogger(__name__)


def _parse_summary(row: dict[str, Any]) -> JobSummary | None:
    """None for a half-published row (seen live: only a req ID). It isn't marked seen, so it alerts once complete."""
    title, path = row.get("title"), row.get("externalPath")
    if not title or not path:
        logger.warning("Workday row skipped, missing title or externalPath: %r", row)
        return None
    bullets = row.get("bulletFields") or []
    job_id = bullets[0] if bullets else path.rsplit("/", 1)[-1]
    return JobSummary(id=job_id, title=title, location=row.get("locationsText", ""), detail_ref=path)


class WorkdayAdapter:
    def __init__(self, company_id: str, host: str, tenant: str, site: str) -> None:
        self._company_id = company_id
        self._base_url = f"https://{host}/wday/cxs/{tenant}/{site}"
        self._session = build_session()

    @classmethod
    def from_company(cls, company: Company) -> "WorkdayAdapter":
        config = company.ats_config
        missing = [key for key in ("host", "tenant", "site") if not config.get(key)]
        if missing:
            raise AdapterError(f"company '{company.id}': atsConfig is missing {missing}")
        return cls(company.id, config["host"], config["tenant"], config["site"])

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        return fetch_json(self._session, method, f"{self._base_url}{path}", **kwargs)

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
        summaries = (_parse_summary(row) for row in rows)
        return tuple(summary for summary in summaries if summary is not None)

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
