"""Stage 1 of matching: free checks on title and location."""
import re
from collections.abc import Iterable

from .models import TitleLocationFilter


# Clear statements that a job needs an active clearance or won't sponsor. Free, and works
# when scoring is down. Claude catches other wording (see matching/rerank.py).
# "Ability to obtain a clearance" is deliberately not matched here.
_DEALBREAKER_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:active|current)\s+(?:[\w/-]+\s+){0,4}?clearance\b",
        r"\b(?:not|n['’]t|unable to|cannot|no)\s+(?:[\w-]+\s+){0,4}?sponsor",
        r"\bwithout\s+(?:[\w-]+\s+){0,3}?sponsor",
        r"\bsponsorship\s+(?:[\w-]+\s+){0,3}?(?:not|unavailable)\b",
    )
)


_US_STATES = (
    "Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|Hawaii|Idaho|"
    "Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|"
    "Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|"
    "Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|"
    "Virginia|Washington|West Virginia|Wisconsin|Wyoming|District of Columbia"
)
_US_STATE_CODES = (
    "AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|"
    "OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC"
)
_US_NAME = re.compile(rf"\b(?:United States|{_US_STATES})\b", re.IGNORECASE)
_US_CODE = re.compile(rf"\b(?:USA|US|U\.S\.)(?:\b|$)|(?:^|,\s*)(?:{_US_STATE_CODES})(?:\s*,|\s+\d{{5}}|\s*\(|\s*$)")
_REGION_AND_COUNTRY = re.compile(r",\s*[A-Z]{2},\s*([A-Z]{2})\s*$")
_NOT_THE_US_STATE = re.compile(r"\brep(?:ublic)?\.?\s+of\s+georgia\b", re.IGNORECASE)
_COUNTRY_ONLY_REMOTE = re.compile(r"^\s*remote\s*$", re.IGNORECASE)


def _is_us_location(location: str) -> bool:
    cleaned = _NOT_THE_US_STATE.sub("", location)
    # "City, ST, CC": the last code is the country, so "Noida, UP, IN" is India, not Indiana.
    region_and_country = _REGION_AND_COUNTRY.search(cleaned)
    if region_and_country:
        return region_and_country.group(1) == "US"
    return bool(_US_NAME.search(cleaned) or _US_CODE.search(cleaned) or _COUNTRY_ONLY_REMOTE.match(cleaned))


def is_us_job(locations: Iterable[str]) -> bool:
    """True if any location is in the US. A job with no stated location passes, so it can't be silently lost."""
    known = [location for location in locations if location.strip()]
    return not known or any(_is_us_location(location) for location in known)


def has_dealbreaker(description: str) -> bool:
    return any(pattern.search(description) for pattern in _DEALBREAKER_PATTERNS)


def _has_term(text: str, terms: Iterable[str]) -> bool:
    """Whole-word match, so 'engineer' does not match 'Engineering Support'."""
    return any(re.search(rf"\b{re.escape(term)}\b", text, re.IGNORECASE) for term in terms)


def passes_title(title: str, rules: TitleLocationFilter) -> bool:
    """titleAlways beats titleExclude, which beats titleInclude."""
    if _has_term(title, rules.title_always):
        return True
    if _has_term(title, rules.title_exclude):
        return False
    return not rules.title_include or _has_term(title, rules.title_include)


def passes_location(locations: Iterable[str], rules: TitleLocationFilter) -> bool:
    """True if any job location contains any wanted location."""
    if not rules.locations:
        return True
    wanted = [place.lower() for place in rules.locations]
    return any(place in location.lower() for location in locations for place in wanted)
