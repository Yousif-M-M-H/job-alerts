"""UKG Ready (*.entertimeonline.com) careers API.

The list call already includes each full description, so get_job needs no request.
"""
from typing import Any

from ..models import Company, Job, JobSummary
from .base import AdapterError
from .http import build_session, fetch_json, html_to_text

PAGE_SIZE = 100


def _format_location(location: dict[str, Any]) -> str:
    parts = (location.get("city"), location.get("state"), location.get("country"))
    return ", ".join(part for part in parts if part)


class UkgReadyAdapter:
    def __init__(self, company_id: str, host: str, company_code: str) -> None:
        self._company_id = company_id
        self._host = host
        self._company_code = company_code
        self._session = build_session()
        self._rows_by_id: dict[str, dict[str, Any]] = {}

    @classmethod
    def from_company(cls, company: Company) -> "UkgReadyAdapter":
        config = company.ats_config
        missing = [key for key in ("host", "companyCode") if not config.get(key)]
        if missing:
            raise AdapterError(f"company '{company.id}': atsConfig is missing {missing}")
        return cls(company.id, config["host"], config["companyCode"])

    def list_jobs(self) -> tuple[JobSummary, ...]:
        url = f"https://{self._host}/ta/rest/ui/recruitment/companies/%7C{self._company_code}/job-requisitions"
        rows: list[dict[str, Any]] = []
        page = 0
        while True:
            page += 1  # The API's "offset" is a 1-based page number, not a row position.
            params = {"offset": page, "size": PAGE_SIZE, "sort": "desc", "lang": "en-US"}
            payload = fetch_json(self._session, "GET", url, params=params)
            page_rows, paging = payload.get("job_requisitions"), payload.get("_paging")
            if not isinstance(page_rows, list) or not isinstance(paging, dict):
                raise AdapterError("UKG Ready response has no job_requisitions or _paging")
            rows = [*rows, *page_rows]
            total = paging.get("total", 0)
            if len(rows) >= total:
                break
            if not page_rows:
                raise AdapterError(f"UKG Ready listed {len(rows)} of {total} jobs")
        self._rows_by_id = {str(row.get("id")): row for row in rows}
        return tuple(self._parse_summary(row) for row in rows)

    def _parse_summary(self, row: dict[str, Any]) -> JobSummary:
        job_id, title = row.get("id"), row.get("job_title")
        if not job_id or not title:
            raise AdapterError(f"UKG Ready row is missing id or job_title: {row!r}")
        location = _format_location(row.get("location") or {})
        return JobSummary(id=str(job_id), title=title, location=location, detail_ref=str(job_id))

    def get_job(self, summary: JobSummary) -> Job:
        row = self._rows_by_id.get(summary.id)
        if row is None:
            raise AdapterError(f"UKG Ready job {summary.id} is not in the last list")
        return Job(
            id=summary.id,
            company_id=self._company_id,
            title=summary.title,
            locations=(summary.location,) if summary.location else (),
            url=f"https://{self._host}/ta/{self._company_code}.careers?ShowJob={summary.id}",
            description_text=html_to_text(row.get("job_description") or ""),
        )
