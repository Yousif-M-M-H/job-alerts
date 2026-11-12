"""Lever public postings API. Board name: jobs.lever.co/<board>."""
from ..models import Job
from .base import AdapterError
from .feed import FeedAdapter, require
from .http import fetch_json_value, html_to_text

API = "https://api.lever.co/v0/postings/{board}"


class LeverAdapter(FeedAdapter):
    def _fetch_jobs(self) -> tuple[Job, ...]:
        rows = fetch_json_value(self._session, "GET", API.format(board=self._board), params={"mode": "json"})
        if not isinstance(rows, list):
            raise AdapterError(f"Lever board '{self._board}' did not return a list")
        return tuple(self._parse(require(row, ("id", "text", "hostedUrl"), "Lever")) for row in rows)

    def _parse(self, row: dict) -> Job:
        categories = row.get("categories") or {}
        places = categories.get("allLocations") or [categories.get("location", "")]
        # The country code (e.g. "US") helps the USA-only filter when a city is ambiguous.
        locations = (*places, row.get("country", ""))
        sections = [
            row.get("descriptionPlain", ""),
            *(part for item in row.get("lists") or [] for part in (item.get("text", ""), html_to_text(item.get("content", "")))),
            row.get("additionalPlain", ""),
        ]
        description = "\n".join(section.strip() for section in sections if section and section.strip())
        return self._job(row["id"], row["text"], locations, row["hostedUrl"], description)
