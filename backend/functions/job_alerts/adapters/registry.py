"""Maps a company's 'ats' value to its adapter. A new ATS adds one line here."""
from collections.abc import Callable

from ..models import Company
from .base import Adapter, AdapterError
from .workday import WorkdayAdapter

_FACTORIES: dict[str, Callable[[Company], Adapter]] = {
    "workday": WorkdayAdapter.from_company,
}


def build_adapter(company: Company) -> Adapter:
    factory = _FACTORIES.get(company.ats)
    if factory is None:
        raise AdapterError(f"company '{company.id}': unknown ats '{company.ats}'")
    return factory(company)
