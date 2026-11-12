"""Ashby public job board API. Board name: jobs.ashbyhq.com/<board>."""
from ..models import Job
from .base import AdapterError
from .feed import FeedAdapter, require
from .http import fetch_json_value, html_to_text

API = "https://api.ashbyhq.com/posting-api/job-board/{board}"


class AshbyAdapter(FeedAdapter):
    def _fetch_jobs(self) -> tuple[Job, ...]:
        payload = fetch_json_value(self._session, "GET", API.format(board=self._board))
        rows = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise AdapterError(f"Ashby board '{self._board}' has no jobs list")
        listed = (row for row in rows if not isinstance(row, dict) or row.get("isListed", True))
        return tuple(self._parse(require(row, ("id", "title", "jobUrl"), "Ashby")) for row in listed)

    def _parse(self, row: dict) -> Job:
        secondary = tuple(place.get("location", "") for place in row.get("secondaryLocations") or [])
        description = row.get("descriptionPlain") or html_to_text(row.get("descriptionHtml") or "")
        return self._job(row["id"], row["title"], (row.get("location", ""), *secondary), row["jobUrl"], description)
