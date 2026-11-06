"""One poll of one company: list, dedupe, baseline, filter, score, alert."""
import logging
from collections.abc import Callable

from .adapters.base import Adapter, AdapterError
from .filters import passes_location, passes_title
from .models import Company, Job, JobScore, JobSummary, PollResult
from .notify.base import Notifier, NotifyError
from .store.base import Store

logger = logging.getLogger(__name__)

# Returns None when scoring fails. The job then alerts as "not scored", so an outage can't hide it.
Scorer = Callable[[Job], JobScore | None]


def _unique_new(summaries: tuple[JobSummary, ...], seen: frozenset[str]) -> tuple[JobSummary, ...]:
    """Keep the first row per ID. A list can repeat a job while it shifts between pages."""
    by_id: dict[str, JobSummary] = {}
    for summary in summaries:
        if summary.id not in seen and summary.id not in by_id:
            by_id[summary.id] = summary
    return tuple(by_id.values())


def _run_baseline(company: Company, summaries: tuple[JobSummary, ...], store: Store) -> PollResult:
    """First poll: record everything as seen and report title matches. Nothing alerts."""
    store.mark_baselined(company.id, (summary.id for summary in summaries))
    return PollResult(
        company_id=company.id,
        total_listed=len(summaries),
        is_baseline=True,
        baseline_title_matches=tuple(
            summary for summary in summaries if passes_title(summary.title, company.filter)
        ),
    )


def poll_company(company: Company, adapter: Adapter, store: Store, score_job: Scorer, notify: Notifier) -> PollResult:
    """Raises AdapterError if the list call fails, leaving stored state untouched.

    A job is marked seen only once it is fully handled, so a failed detail fetch or
    alert retries on the next poll. Sent alerts are saved one at a time, so a crash
    partway through can't send them all again.
    """
    summaries = adapter.list_jobs()
    if not store.is_baselined(company.id):
        return _run_baseline(company, summaries, store)

    new_jobs = _unique_new(summaries, store.seen_ids(company.id))
    rejected_title: list[str] = []
    rejected_location: list[str] = []
    rejected_score: list[tuple[str, int]] = []
    candidates: list[Job] = []
    alerted_scores: list[int | None] = []
    failed_ids: list[str] = []

    for summary in new_jobs:
        if not passes_title(summary.title, company.filter):
            rejected_title.append(summary.id)
            continue
        try:
            job = adapter.get_job(summary)
            if not passes_location(job.locations, company.filter):
                rejected_location.append(summary.id)
                continue
            score = score_job(job)
            if score is not None and score.score < company.min_score:
                rejected_score.append((summary.id, score.score))
                store.mark_seen(company.id, (summary.id,))
                continue
            notify(company, job, score)
        except (AdapterError, NotifyError) as error:
            logger.warning("%s: job %s failed, will retry: %s", company.id, summary.id, error)
            failed_ids.append(summary.id)
            continue
        store.mark_seen(company.id, (job.id,))
        candidates.append(job)
        alerted_scores.append(score.score if score else None)

    rejected_ids = (*rejected_title, *rejected_location)
    if rejected_ids:
        store.mark_seen(company.id, rejected_ids)

    return PollResult(
        company_id=company.id,
        total_listed=len(summaries),
        new_count=len(new_jobs),
        rejected_title=tuple(rejected_title),
        rejected_location=tuple(rejected_location),
        rejected_score=tuple(rejected_score),
        candidates=tuple(candidates),
        alerted_scores=tuple(alerted_scores),
        failed_ids=tuple(failed_ids),
    )
