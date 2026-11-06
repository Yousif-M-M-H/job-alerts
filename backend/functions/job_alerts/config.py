"""Parse and validate company config. Fails fast with a clear message."""
from typing import Any

from .models import Company, TitleLocationFilter


class ConfigError(ValueError):
    pass


def _string_tuple(raw: dict[str, Any], key: str, company_id: str) -> tuple[str, ...]:
    value = raw.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ConfigError(f"company '{company_id}': filter.{key} must be a list of non-empty strings")
    return tuple(value)


def parse_company(raw: dict[str, Any]) -> Company:
    company_id = raw.get("id")
    if not isinstance(company_id, str) or not company_id:
        raise ConfigError(f"company is missing an id: {raw!r}")

    for key in ("name", "ats"):
        if not isinstance(raw.get(key), str) or not raw[key]:
            raise ConfigError(f"company '{company_id}': missing '{key}'")

    ats_config = raw.get("atsConfig")
    if not isinstance(ats_config, dict):
        raise ConfigError(f"company '{company_id}': missing 'atsConfig'")

    rules = raw.get("filter", {})
    if not isinstance(rules, dict):
        raise ConfigError(f"company '{company_id}': 'filter' must be an object")

    return Company(
        id=company_id,
        name=raw["name"],
        ats=raw["ats"],
        ats_config=dict(ats_config),
        filter=TitleLocationFilter(
            title_include=_string_tuple(rules, "titleInclude", company_id),
            title_exclude=_string_tuple(rules, "titleExclude", company_id),
            title_always=_string_tuple(rules, "titleAlways", company_id),
            locations=_string_tuple(rules, "locations", company_id),
        ),
        is_paused=bool(raw.get("paused", False)),
    )


def parse_companies(raw: Any) -> tuple[Company, ...]:
    if not isinstance(raw, list):
        raise ConfigError("company config must be a list")
    companies = tuple(parse_company(item) for item in raw)
    ids = [company.id for company in companies]
    if len(ids) != len(set(ids)):
        raise ConfigError(f"duplicate company ids in {ids}")
    return companies
