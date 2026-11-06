"""Stage 1 of matching: free checks on title and location."""
import re
from collections.abc import Iterable

from .models import TitleLocationFilter


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
