"""Local state file for the CLI. Writes are atomic, so a crash can't corrupt it."""
import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

EMPTY_COMPANY: dict[str, Any] = {"baselined": False, "seen": []}


class JsonStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        with self._path.open(encoding="utf-8") as file:
            return json.load(file)

    def _company(self, company_id: str) -> dict[str, Any]:
        return self._load().get(company_id, EMPTY_COMPANY)

    def _save_company(self, company_id: str, company: dict[str, Any]) -> None:
        state = {**self._load(), company_id: company}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(".tmp")
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(state, file, indent=1, sort_keys=True)
        os.replace(temp_path, self._path)

    def is_baselined(self, company_id: str) -> bool:
        return bool(self._company(company_id)["baselined"])

    def seen_ids(self, company_id: str) -> frozenset[str]:
        return frozenset(self._company(company_id)["seen"])

    def mark_seen(self, company_id: str, job_ids: Iterable[str]) -> None:
        company = self._company(company_id)
        seen = sorted({*company["seen"], *job_ids})
        self._save_company(company_id, {**company, "seen": seen})

    def mark_baselined(self, company_id: str, job_ids: Iterable[str]) -> None:
        self._save_company(company_id, {"baselined": True, "seen": sorted(set(job_ids))})
