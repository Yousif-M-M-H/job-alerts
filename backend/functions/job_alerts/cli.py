"""Poll once and alert: python -m job_alerts.cli [--company sel]

Needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in the environment.
"""
import argparse
import json
import logging
import os
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from .adapters.base import AdapterError, RateLimitedError
from .adapters.registry import build_adapter
from .config import ConfigError, parse_companies
from .health import evaluate, is_due, load_health, save_health, scoring_status
from .matching.rerank import ClaudeScorer
from .models import Company, PollResult
from .notify.base import NotifyError
from .notify.telegram import TelegramNotifier
from .pipeline import Scorer, poll_company
from .store.json_store import JsonStore

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "companies.json"
DEFAULT_STATE = ROOT / "state.json"
DEFAULT_HEALTH = ROOT / "health.json"
# Workday boards are paced (5 s per request), so a run checks only a few of them. Ones not reached
# stay due and go first next run, so all 13 Workday boards are covered within their 30-minute interval.
MAX_BOARDS_PER_RUN = {"workday": 3}


def _print_result(result: PollResult) -> None:
    print(f"\n{result.company_id}: {result.total_listed} open jobs")
    if result.is_baseline:
        print(f"  BASELINE: all marked seen, nothing alerted. {len(result.baseline_title_matches)} pass the title filter.")
        return
    print(
        f"  new {result.new_count}, alerted {len(result.candidates)}, rejected by title "
        f"{len(result.rejected_title)}, by location {len(result.rejected_location)}, "
        f"by clearance/sponsorship {len(result.rejected_dealbreaker)}, "
        f"by score {len(result.rejected_score)}, failed {len(result.failed_ids)}"
    )
    # Workflow logs are public: IDs and scores only, never the reason.
    for job, score in zip(result.candidates, result.alerted_scores):
        print(f"  ALERTED {job.id}  score {'none' if score is None else score}")
    for job_id, score in result.rejected_score:
        print(f"  BELOW THRESHOLD {job_id}  score {score}")


def _build_scorer() -> Scorer:
    """Without credentials, alerts still go out, marked "not scored"."""
    cv_text = os.environ.get("CV_TEXT", "")
    if not cv_text.strip() or not os.environ.get("ANTHROPIC_API_KEY"):
        print("WARNING: CV_TEXT or ANTHROPIC_API_KEY missing, alerts will not be scored.", file=sys.stderr)
        return lambda job: None
    return ClaudeScorer(cv_text)


def main() -> int:
    parser = argparse.ArgumentParser(description="Poll company career pages once.")
    parser.add_argument("--company", help="only this company id")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--health", type=Path, default=DEFAULT_HEALTH)
    # Workday blocks GitHub's servers, so Workday boards run on a home machine (poll-workday.yml)
    # and the GitHub-hosted run skips them. Each side keeps its own --state and --health files.
    parser.add_argument("--only-ats", action="append", default=[], help="only this job system (repeatable)")
    parser.add_argument("--skip-ats", action="append", default=[], help="skip this job system (repeatable)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    token, chat_id = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set.", file=sys.stderr)
        return 2
    notify = TelegramNotifier(token, chat_id)

    try:
        companies = parse_companies(json.loads(args.config.read_text(encoding="utf-8")))
    except (OSError, ValueError, ConfigError) as error:
        print(f"Bad config {args.config}: {error}", file=sys.stderr)
        return 2

    in_scope = select_by_ats(companies, only=tuple(args.only_ats), skip=tuple(args.skip_ats))
    selected = [c for c in in_scope if not c.is_paused and args.company in (None, c.id)]
    if not selected:
        print("No matching unpaused company.", file=sys.stderr)
        return 2

    # An explicit --company always runs; otherwise companies with checkEveryMinutes wait their turn.
    now = datetime.now(timezone.utc)
    health = load_health(args.health)
    due = [c for c in selected if args.company or is_due(c, health, now)]
    for company in selected:
        if company not in due:
            print(f"\n{company.id}: skipped, checked less than {company.check_every_minutes} min ago")
    if not args.company:
        due, deferred = cap_per_ats(due, MAX_BOARDS_PER_RUN)
        for company in deferred:
            print(f"\n{company.id}: waiting, at most {MAX_BOARDS_PER_RUN[company.ats]} {company.ats} boards per run")

    store = JsonStore(args.state)
    score_job = _build_scorer()
    outcomes, results = poll_all(
        due, lambda company: poll_company(company, build_adapter(company), store, score_job, notify)
    )
    new_warned = _report_health(args.health, health, outcomes, results, notify, board_count=len(selected))
    return exit_code(health.get("warned", []), new_warned)


def select_by_ats(companies: list[Company], only: tuple[str, ...], skip: tuple[str, ...]) -> list[Company]:
    """Companies on the `only` job systems (all when empty), minus those on `skip`."""
    return [c for c in companies if (not only or c.ats in only) and c.ats not in skip]


def cap_per_ats(
    companies: list[Company], caps: dict[str, int]
) -> tuple[list[Company], list[Company]]:
    """Keep the first `caps[ats]` companies of each capped job system; the rest wait for a later run."""
    counts: dict[str, int] = {}
    kept: list[Company] = []
    deferred: list[Company] = []
    for company in companies:
        counts = {**counts, company.ats: counts.get(company.ats, 0) + 1}
        is_over = company.ats in caps and counts[company.ats] > caps[company.ats]
        (deferred if is_over else kept).append(company)
    return kept, deferred


def poll_all(
    companies: list[Company], poll_one: Callable[[Company], PollResult]
) -> tuple[dict[str, bool], tuple[PollResult, ...]]:
    """Poll each company. One company failing must not stop the others.

    After a 429, the other boards on the same job system (e.g. every Workday board) are skipped
    for this run: they share the rate limit, so asking again only keeps us blocked longer.
    They still count as a failed check, like the 429 they would almost surely get.
    """
    outcomes: dict[str, bool] = {}
    results: list[PollResult] = []
    rate_limited_ats: set[str] = set()
    for company in companies:
        if company.ats in rate_limited_ats:
            print(f"\n{company.id}: RATE LIMITED, skipped: {company.ats} already returned 429 this run", file=sys.stderr)
            outcomes[company.id] = False
            continue
        try:
            result = poll_one(company)
        except RateLimitedError as error:
            print(f"\n{company.id}: RATE LIMITED, will retry next run: {error}", file=sys.stderr)
            rate_limited_ats = rate_limited_ats | {company.ats}
            outcomes[company.id] = False
            continue
        except AdapterError as error:
            print(f"\n{company.id}: FAILED: {error}", file=sys.stderr)
            outcomes[company.id] = False
            continue
        _print_result(result)
        results.append(result)
        outcomes[company.id] = not result.failed_ids
    return outcomes, tuple(results)


def exit_code(old_warned: list[str], new_warned: list[str]) -> int:
    """1 only on a run that sends a new 'not working' warning, so red runs match Telegram.

    Boards blip often (timeouts, 5xx, rate limits); those stay green and are still logged.
    """
    return 1 if set(new_warned) - set(old_warned) else 0


def _report_health(
    path: Path, health: dict, outcomes: dict[str, bool], results: tuple[PollResult, ...],
    notify: TelegramNotifier, board_count: int,
) -> list[str]:
    """Saves new health only once its messages are sent, so a failed send retries next run.
    Returns the companies now warned about."""
    now = datetime.now(timezone.utc)
    new_health, messages = evaluate(health, outcomes, scoring_status(results), now, board_count)
    try:
        for message in messages:
            notify.send_text(message)
    except NotifyError as error:
        print(f"Health message not sent, will retry: {error}", file=sys.stderr)
        return new_health["warned"]
    save_health(path, new_health)
    return new_health["warned"]


if __name__ == "__main__":
    sys.exit(main())
