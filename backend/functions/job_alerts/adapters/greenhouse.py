"""Greenhouse public job board API. Board name: boards.greenhouse.io/<board>."""
import html as html_lib

from ..models import Job
from .base import AdapterError
from .feed import FeedAdapter, require
from .http import fetch_json_value, html_to_text

API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"


class GreenhouseAdapter(FeedAdapter):
    def _fetch_jobs(self) -> tuple[Job, ...]:
        payload = fetch_json_value(self._session, "GET", API.format(board=self._board), params={"content": "true"})
        rows = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise AdapterError(f"Greenhouse board '{self._board}' has no jobs list")
        return tuple(self._parse(require(row, ("id", "title", "absolute_url"), "Greenhouse")) for row in rows)

    def _parse(self, row: dict) -> Job:
        # Greenhouse sends the description as escaped HTML: unescape once to get HTML, then to text.
        description = html_to_text(html_lib.unescape(row.get("content") or ""))
        location = (row.get("location") or {}).get("name", "")
        return self._job(row["id"], row["title"], (location,), row["absolute_url"], description)
