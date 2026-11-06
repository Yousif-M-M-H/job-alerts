"""Eightfold careers search API, used by Microsoft.

The board is huge and rate-limits bursts, so this reads only the newest pages of one
search, slowly. New postings appear at the top, so polling the newest pages catches them.
A job reposted with a new date could alert once more.
"""
import time

from ..models import Company, Job, JobSummary
from .base import AdapterError
from .http import build_session, fetch_json, html_to_text

PAGE_SIZE = 10
PAGE_DELAY_SECONDS = 1.0
DEFAULT_MAX_PAGES = 5


class EightfoldAdapter:
    def __init__(self, company_id: str, host: str, domain: str, query: str, max_pages: int) -> None:
        self._company_id = company_id
        self._base = f"https://{host}"
        self._domain = domain
        self._query = query
        self._max_pages = max_pages
        self._session = build_session()

    @classmethod
    def from_company(cls, company: Company) -> "EightfoldAdapter":
        config = company.ats_config
        missing = [key for key in ("host", "domain", "query") if not config.get(key)]
        if missing:
            raise AdapterError(f"company '{company.id}': atsConfig is missing {missing}")
        max_pages = int(config.get("maxPages", DEFAULT_MAX_PAGES))
        return cls(company.id, config["host"], config["domain"], config["query"], max_pages)

    def list_jobs(self) -> tuple[JobSummary, ...]:
        summaries: list[JobSummary] = []
        for page in range(self._max_pages):
            if page:
                time.sleep(PAGE_DELAY_SECONDS)
            params = {
                "domain": self._domain,
                "query": self._query,
                "location": "",
                "start": page * PAGE_SIZE,
                "sort_by": "timestamp",
            }
            payload = fetch_json(self._session, "GET", f"{self._base}/api/pcsx/search", params=params)
            positions = (payload.get("data") or {}).get("positions")
            if not isinstance(positions, list):
                raise AdapterError(f"Eightfold page {page} has no positions list")
            if not positions:
                break
            summaries = [*summaries, *(self._parse_summary(row) for row in positions)]
        return tuple(summaries)

    def _parse_summary(self, row: dict) -> JobSummary:
        job_id, position_id, title = row.get("displayJobId"), row.get("id"), row.get("name")
        if not job_id or not position_id or not title:
            raise AdapterError(f"Eightfold row is missing id or name: {row!r}")
        return JobSummary(
            id=str(job_id),
            title=title,
            location="; ".join(row.get("locations") or []),
            detail_ref=str(position_id),
        )

    def get_job(self, summary: JobSummary) -> Job:
        params = {"position_id": summary.detail_ref, "domain": self._domain, "hl": "en"}
        payload = fetch_json(self._session, "GET", f"{self._base}/api/pcsx/position_details", params=params)
        info = payload.get("data")
        if not isinstance(info, dict) or not info.get("positionUrl"):
            raise AdapterError(f"Eightfold job {summary.id} has no details")
        return Job(
            id=summary.id,
            company_id=self._company_id,
            title=info.get("name") or summary.title,
            locations=tuple(info.get("locations") or ()) or (summary.location,),
            url=info.get("publicUrl") or f"{self._base}{info['positionUrl']}",
            description_text=html_to_text(info.get("jobDescription") or ""),
        )
