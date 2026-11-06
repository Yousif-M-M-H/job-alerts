"""The contract every ATS adapter implements."""
from typing import Protocol

from ..models import Job, JobSummary


class AdapterError(RuntimeError):
    """The ATS failed or returned something unexpected."""


class Adapter(Protocol):
    def list_jobs(self) -> tuple[JobSummary, ...]:
        """Return every open posting, or raise AdapterError. Never a partial list."""
        ...

    def get_job(self, summary: JobSummary) -> Job:
        """Fetch one full posting, or raise AdapterError."""
        ...
