"""UKG Pro (recruiting.ultipro.com) job board, used by Mesa.

The list is JSON. Full details only exist as JSON embedded in the job's HTML page.
"""
import json
from typing import Any

from ..models import Company, Job, JobSummary
from .base import AdapterError
from .http import build_session, fetch, fetch_json, html_to_text

PAGE_SIZE = 50
DETAIL_MARKER = "CandidateOpportunityDetail("


def _search_body(skip: int) -> dict[str, Any]:
    return {
        "opportunitySearch": {
            "Top": PAGE_SIZE,
            "Skip": skip,
            "QueryString": "",
            "OrderBy": [{"Value": "postedDateDesc", "PropertyName": "PostedDate", "Ascending": False}],
            "Filters": [],
        },
        "matchCriteria": {
            "PreferredJobs": [],
            "Educations": [],
            "LicenseAndCertifications": [],
            "Skills": [],
            "hasNoLicenses": False,
            "SkippedSkills": [],
        },
    }


def _format_location(location: dict[str, Any]) -> str:
    address = location.get("Address") or {}
    state = (address.get("State") or {}).get("Name")
    parts = (address.get("City"), state)
    return ", ".join(part for part in parts if part) or location.get("LocalizedName") or ""


def parse_detail_html(html: str) -> dict[str, Any]:
    start = html.find(DETAIL_MARKER)
    if start < 0:
        raise AdapterError("UKG job page has no embedded details")
    try:
        detail, _ = json.JSONDecoder().raw_decode(html, start + len(DETAIL_MARKER))
    except ValueError as error:
        raise AdapterError("UKG job page has unreadable details") from error
    if not isinstance(detail, dict):
        raise AdapterError("UKG job page has unexpected details")
    return detail


class UkgProAdapter:
    def __init__(self, company_id: str, host: str, tenant: str, board: str) -> None:
        self._company_id = company_id
        self._board_url = f"https://{host}/{tenant}/JobBoard/{board}"
        self._session = build_session()

    @classmethod
    def from_company(cls, company: Company) -> "UkgProAdapter":
        config = company.ats_config
        missing = [key for key in ("host", "tenant", "board") if not config.get(key)]
        if missing:
            raise AdapterError(f"company '{company.id}': atsConfig is missing {missing}")
        return cls(company.id, config["host"], config["tenant"], config["board"])

    def list_jobs(self) -> tuple[JobSummary, ...]:
        url = f"{self._board_url}/JobBoardView/LoadSearchResults"
        rows: list[dict[str, Any]] = []
        while True:
            payload = fetch_json(self._session, "POST", url, json=_search_body(len(rows)))
            page_rows, total = payload.get("opportunities"), payload.get("totalCount")
            if not isinstance(page_rows, list) or not isinstance(total, int):
                raise AdapterError("UKG response has no opportunities or totalCount")
            rows = [*rows, *page_rows]
            if len(rows) >= total:
                break
            if not page_rows:
                raise AdapterError(f"UKG listed {len(rows)} of {total} jobs")
        return tuple(self._parse_summary(row) for row in rows)

    def _parse_summary(self, row: dict[str, Any]) -> JobSummary:
        job_id, title = row.get("Id"), row.get("Title")
        if not job_id or not title:
            raise AdapterError(f"UKG row is missing Id or Title: {row!r}")
        location = "; ".join(_format_location(item) for item in row.get("Locations") or [])
        return JobSummary(id=job_id, title=title, location=location, detail_ref=job_id)

    def get_job(self, summary: JobSummary) -> Job:
        url = f"{self._board_url}/OpportunityDetail"
        params = {"opportunityId": summary.detail_ref}
        response = fetch(self._session, "GET", url, params=params, headers={"Accept": "text/html"})
        detail = parse_detail_html(response.text)
        locations = tuple(_format_location(item) for item in detail.get("Locations") or [])
        return Job(
            id=summary.id,
            company_id=self._company_id,
            title=detail.get("Title") or summary.title,
            locations=tuple(place for place in locations if place) or (summary.location,),
            url=f"{url}?opportunityId={summary.detail_ref}",
            description_text=html_to_text(detail.get("Description") or ""),
            posted_on=detail.get("PostedDate") or "",
        )
