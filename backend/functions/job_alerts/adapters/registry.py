"""Maps a company's 'ats' value to its adapter. A new ATS adds one line here."""
from collections.abc import Callable

from ..models import Company
from .base import Adapter, AdapterError
from .eightfold import EightfoldAdapter
from .icims import IcimsAdapter
from .jobsyn import JobsynAdapter
from .successfactors import SuccessFactorsAdapter
from .ukg_pro import UkgProAdapter
from .ukg_ready import UkgReadyAdapter
from .workday import WorkdayAdapter

_FACTORIES: dict[str, Callable[[Company], Adapter]] = {
    "workday": WorkdayAdapter.from_company,
    "eightfold": EightfoldAdapter.from_company,
    "ukg_pro": UkgProAdapter.from_company,
    "ukg_ready": UkgReadyAdapter.from_company,
    "successfactors": SuccessFactorsAdapter.from_company,
    "jobsyn": JobsynAdapter.from_company,
    "icims": IcimsAdapter.from_company,
}


def build_adapter(company: Company) -> Adapter:
    factory = _FACTORIES.get(company.ats)
    if factory is None:
        raise AdapterError(f"company '{company.id}': unknown ats '{company.ats}'")
    return factory(company)
