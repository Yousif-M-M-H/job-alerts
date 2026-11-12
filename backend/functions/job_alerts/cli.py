"""Poll once and alert: python -m job_alerts.cli [--company sel]

Needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in the environment.
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .adapters.base import AdapterError, RateLimitedError
from .adapters.registry import build_adapter
from .config import ConfigError, parse_companies
from .health import evaluate, is_due, load_health, save_health, scoring_status
from .matching.rerank import ClaudeScorer
from .models import PollResult
from .notify.base import NotifyError
from .notify.telegram import TelegramNotifier
from .pipeline import Scorer, poll_company
from .store.json_store import JsonStore

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "companies.json"
DEFAULT_STATE = ROOT / "state.json"
DEFAULT_HEALTH = ROOT / "health.json"


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

    selected = [c for c in companies if not c.is_paused and args.company in (None, c.id)]
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

    store = JsonStore(args.state)
    score_job = _build_scorer()
    outcomes: dict[str, bool] = {}
    rate_limited: set[str] = set()
    results: list[PollResult] = []
    for company in due:
        try:
            result = poll_company(company, build_adapter(company), store, score_job, notify)
        except RateLimitedError as error:
            # Temporary; still counts toward the 3-in-a-row health warning, but keeps the run green.
            print(f"\n{company.id}: RATE LIMITED, will retry next run: {error}", file=sys.stderr)
            outcomes[company.id] = False
            rate_limited.add(company.id)
            continue
        except AdapterError as error:
            # One company failing must not stop the others.
            print(f"\n{company.id}: FAILED: {error}", file=sys.stderr)
            outcomes[company.id] = False
            continue
        _print_result(result)
        results.append(result)
        outcomes[company.id] = not result.failed_ids

    _report_health(args.health, health, outcomes, tuple(results), notify, board_count=len(selected))
    return exit_code(outcomes, frozenset(rate_limited))


def exit_code(outcomes: dict[str, bool], rate_limited: frozenset[str]) -> int:
    """1 when a company really failed; a rate limit alone is not a failure."""
    return 0 if all(is_ok or cid in rate_limited for cid, is_ok in outcomes.items()) else 1


def _report_health(
    path: Path, health: dict, outcomes: dict[str, bool], results: tuple[PollResult, ...],
    notify: TelegramNotifier, board_count: int,
) -> None:
    """Saves new health only once its messages are sent, so a failed send retries next run."""
    now = datetime.now(timezone.utc)
    new_health, messages = evaluate(health, outcomes, scoring_status(results), now, board_count)
    try:
        for message in messages:
            notify.send_text(message)
    except NotifyError as error:
        print(f"Health message not sent, will retry: {error}", file=sys.stderr)
        return
    save_health(path, new_health)


if __name__ == "__main__":
    sys.exit(main())
