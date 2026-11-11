"""Core data types. All frozen: pipeline steps return new values."""
from dataclasses import dataclass, field

DEFAULT_MIN_SCORE = 70


@dataclass(frozen=True)
class TitleLocationFilter:
    """Cheap filter settings. Empty locations means any location."""

    title_include: tuple[str, ...] = ()
    title_exclude: tuple[str, ...] = ()
    title_always: tuple[str, ...] = ()
    locations: tuple[str, ...] = ()


@dataclass(frozen=True)
class Company:
    id: str
    name: str
    ats: str
    ats_config: dict[str, str]
    filter: TitleLocationFilter = field(default_factory=TitleLocationFilter)
    is_paused: bool = False
    min_score: int = DEFAULT_MIN_SCORE
    check_every_minutes: int = 0  # 0 = every run


@dataclass(frozen=True)
class JobSummary:
    """One row from an ATS list call: enough for dedupe and the title filter."""

    id: str
    title: str
    location: str
    detail_ref: str


@dataclass(frozen=True)
class Job:
    """A fully fetched posting."""

    id: str
    company_id: str
    title: str
    locations: tuple[str, ...]
    url: str
    description_text: str
    posted_on: str = ""


@dataclass(frozen=True)
class JobScore:
    score: int
    reason: str
    is_dealbreaker: bool = False


@dataclass(frozen=True)
class PollResult:
    company_id: str
    total_listed: int = 0
    is_baseline: bool = False
    new_count: int = 0
    rejected_title: tuple[str, ...] = ()
    rejected_location: tuple[str, ...] = ()
    rejected_dealbreaker: tuple[str, ...] = ()
    rejected_score: tuple[tuple[str, int], ...] = ()
    candidates: tuple[Job, ...] = ()
    alerted_scores: tuple[int | None, ...] = ()
    baseline_title_matches: tuple[JobSummary, ...] = ()
    failed_ids: tuple[str, ...] = ()
