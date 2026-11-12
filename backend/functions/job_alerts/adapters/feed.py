"""Shared base for job boards whose public API returns every job, with its description, in one call.

Greenhouse, Lever and Ashby work this way. list_jobs fetches once and keeps the full jobs,
so get_job needs no extra request. Config: {"board": "<name in the board's URL>"}.
"""
from typing import Any

from ..models import Company, Job, JobSummary
from .base import AdapterError
from .http import build_session


def require(row: Any, keys: tuple[str, ...], source: str) -> dict[str, Any]:
    """Return the row if it is an object with every key set, or raise AdapterError."""
    if not isinstance(row, dict) or any(not row.get(key) for key in keys):
        raise AdapterError(f"{source} row is missing one of {list(keys)}: {row!r:.200}")
    return row


class FeedAdapter:
    def __init__(self, company_id: str, board: str) -> None:
        self._company_id = company_id
        self._board = board
        self._session = build_session()
        self._jobs: dict[str, Job] = {}

    @classmethod
    def from_company(cls, company: Company) -> "FeedAdapter":
        board = company.ats_config.get("board")
        if not board:
            raise AdapterError(f"company '{company.id}': atsConfig is missing board")
        return cls(company.id, board)

    def _fetch_jobs(self) -> tuple[Job, ...]:
        raise NotImplementedError

    def _job(self, job_id: Any, title: str, locations: tuple[str, ...], url: str, description: str) -> Job:
        return Job(
            id=str(job_id),
            company_id=self._company_id,
            title=" ".join(title.split()),
            locations=tuple(place for place in locations if place),
            url=url,
            description_text=description.strip(),
        )

    def list_jobs(self) -> tuple[JobSummary, ...]:
        jobs = self._fetch_jobs()
        self._jobs = {job.id: job for job in jobs}
        return tuple(
            JobSummary(id=job.id, title=job.title, location="; ".join(job.locations), detail_ref=job.id)
            for job in jobs
        )

    def get_job(self, summary: JobSummary) -> Job:
        job = self._jobs.get(summary.id)
        if job is None:
            raise AdapterError(f"job {summary.id} was not in the last list call")
        return job
