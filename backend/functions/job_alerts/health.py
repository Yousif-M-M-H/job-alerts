"""Decides which health messages to send. Pure: takes the old health, returns the new one.

Warnings fire once when a problem starts (3 failures, an hour since the last success) and once
when it clears (3 successes), so a long or flapping outage doesn't ping every 5 minutes. The daily message is the check on the schedule itself:
if it stops arriving, the bot has stopped running.
"""
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .models import Company, PollResult

FAILURES_BEFORE_WARNING = 3
OUTAGE_MINUTES_BEFORE_WARNING = 60
SUCCESSES_BEFORE_RECOVERY = 3
DAILY_MESSAGE_HOUR_UTC = 13  # About 8-9 am in Chattanooga.
INTERVAL_SLACK_MINUTES = 2  # Runs start a little late, so a 15-minute company isn't pushed to 20.


@dataclass(frozen=True)
class ScoringStatus:
    has_failure: bool = False
    has_success: bool = False


def scoring_status(results: tuple[PollResult, ...]) -> ScoringStatus:
    """A None score on a sent alert means scoring failed. Any real score means it works."""
    scores = [score for result in results for score in result.alerted_scores]
    has_rejected_score = any(result.rejected_score for result in results)
    return ScoringStatus(
        has_failure=any(score is None for score in scores),
        has_success=has_rejected_score or any(score is not None for score in scores),
    )


@dataclass(frozen=True)
class _CompanyHealth:
    failures: dict[str, int]
    ok_streak: dict[str, int]
    last_ok: dict[str, str]
    warned: list[str]
    messages: list[str]


def _is_down_long_enough(last_ok: str | None, now: datetime) -> bool:
    """No recorded success (old health file, new company): the failure count alone decides."""
    return last_ok is None or now - datetime.fromisoformat(last_ok) >= timedelta(minutes=OUTAGE_MINUTES_BEFORE_WARNING)


def _summary(new_warnings: list[str], recovered: list[str]) -> list[str]:
    """One message per run, however many companies changed."""
    lines = []
    if new_warnings:
        lines.append(f"⚠️ Not working: {', '.join(new_warnings)}. New jobs there can be missed until this is fixed.")
    if recovered:
        lines.append(f"✅ Working again: {', '.join(recovered)}.")
    return ["\n".join(lines)] if lines else []


def _update_companies(health: dict[str, Any], outcomes: dict[str, bool], now: datetime) -> _CompanyHealth:
    """Warn after FAILURES_BEFORE_WARNING failures in a row once the last success is an hour old.
    All-clear only after SUCCESSES_BEFORE_RECOVERY successes in a row, so a board that gets through
    now and then stays in one 'not working' state instead of flipping (2026-11-16..19: ~1,100 messages).
    """
    old_failures: dict[str, int] = health.get("failures", {})
    old_streak: dict[str, int] = health.get("okStreak", {})
    old_last_ok: dict[str, str] = health.get("lastOk", {})
    old_warned = set(health.get("warned", []))
    # Companies skipped this run keep their counts.
    failures = {cid: n for cid, n in old_failures.items() if cid not in outcomes}
    ok_streak = {cid: n for cid, n in old_streak.items() if cid not in outcomes}
    last_ok = {**old_last_ok, **{cid: now.isoformat() for cid, is_ok in outcomes.items() if is_ok}}
    new_warnings: list[str] = []
    recovered: list[str] = []
    for company_id, is_ok in outcomes.items():
        is_warned = company_id in old_warned
        if is_ok:
            streak = old_streak.get(company_id, 0) + 1
            if is_warned and streak >= SUCCESSES_BEFORE_RECOVERY:
                recovered.append(company_id)
            elif is_warned:
                ok_streak[company_id] = streak
            continue
        failures[company_id] = old_failures.get(company_id, 0) + 1
        is_due = failures[company_id] >= FAILURES_BEFORE_WARNING and _is_down_long_enough(
            old_last_ok.get(company_id), now
        )
        if is_due and not is_warned:
            new_warnings.append(company_id)
    warned = sorted((old_warned | set(new_warnings)) - set(recovered))
    return _CompanyHealth(failures, ok_streak, last_ok, warned, _summary(new_warnings, recovered))


def _update_scoring(was_warned: bool, status: ScoringStatus) -> tuple[bool, list[str]]:
    if status.has_failure and not was_warned:
        return True, [
            "⚠️ CV scoring is failing, so alerts are arriving as \"not scored\". "
            "Your API credit may be out, or the key may be broken."
        ]
    if status.has_success and not status.has_failure and was_warned:
        return False, ["✅ CV scoring is working again."]
    return was_warned, []


def _daily_message(last_sent: str, now: datetime, board_count: int, warned: list[str]) -> list[str]:
    today = now.date().isoformat()
    is_due = not last_sent or (last_sent != today and now.hour >= DAILY_MESSAGE_HOUR_UTC)
    if not is_due:
        return []
    problems = f" Problems: {', '.join(warned)}." if warned else " No problems."
    return [f"🟢 Job alerts still running, watching {board_count} boards.{problems}"]


def evaluate(
    health: dict[str, Any], outcomes: dict[str, bool], status: ScoringStatus, now: datetime,
    board_count: int | None = None,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Returns the new health and the messages to send."""
    companies = _update_companies(health, outcomes, now)
    scoring_warned, scoring_messages = _update_scoring(bool(health.get("scoringWarned")), status)
    last_sent = health.get("lastDailyMessage", "")
    daily = _daily_message(last_sent, now, len(outcomes) if board_count is None else board_count, companies.warned)
    new_health = {
        "failures": companies.failures,
        "okStreak": companies.ok_streak,
        "lastOk": companies.last_ok,
        "warned": companies.warned,
        "scoringWarned": scoring_warned,
        "lastDailyMessage": now.date().isoformat() if daily else last_sent,
        "lastChecked": {**health.get("lastChecked", {}), **{cid: now.isoformat() for cid in outcomes}},
    }
    return new_health, (*companies.messages, *scoring_messages, *daily)


def is_due(company: Company, health: dict[str, Any], now: datetime) -> bool:
    """A company with checkEveryMinutes is skipped until that long has passed since its last check."""
    if not company.check_every_minutes:
        return True
    last = health.get("lastChecked", {}).get(company.id)
    if not last:
        return True
    waited = now - datetime.fromisoformat(last)
    return waited >= timedelta(minutes=company.check_every_minutes - INTERVAL_SLACK_MINUTES)


def load_health(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def save_health(path: Path, health: dict[str, Any]) -> None:
    temp_path = path.with_suffix(".tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(health, file, indent=1, sort_keys=True)
    os.replace(temp_path, path)
