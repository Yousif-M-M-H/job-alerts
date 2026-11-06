"""What the pipeline needs from storage. Local JSON now, Firestore in phase 2."""
from collections.abc import Iterable
from typing import Protocol


class Store(Protocol):
    def is_baselined(self, company_id: str) -> bool:
        ...

    def seen_ids(self, company_id: str) -> frozenset[str]:
        ...

    def mark_seen(self, company_id: str, job_ids: Iterable[str]) -> None:
        ...

    def mark_baselined(self, company_id: str, job_ids: Iterable[str]) -> None:
        """Save the first poll's IDs and the baselined flag together."""
        ...
