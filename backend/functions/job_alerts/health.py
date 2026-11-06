"""Decides which health messages to send. Pure: takes the old health, returns the new one.

Warnings fire once when a problem starts and once when it clears, so a long outage
doesn't ping every 5 minutes. The daily message is the check on the schedule itself:
if it stops arriving, the bot has stopped running.
"""
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import PollResult

FAILURES_BEFORE_WARNING = 3
DAILY_MESSAGE_HOUR_UTC = 13  # About 8-9 am in Chattanooga.


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


def _update_companies(health: dict[str, Any], outcomes: dict[str, bool]) -> tuple[dict[str, int], list[str], list[str]]:
    old_failures: dict[str, int] = health.get("failures", {})
    warned = set(health.get("warned", []))
    failures: dict[str, int] = {}
    messages: list[str] = []
    for company_id, is_ok in outcomes.items():
        if is_ok:
            if company_id in warned:
                messages.append(f"✅ {company_id} is working again.")
                warned.discard(company_id)
            continue
        failures[company_id] = old_failures.get(company_id, 0) + 1
        if failures[company_id] >= FAILURES_BEFORE_WARNING and company_id not in warned:
            messages.append(
                f"⚠️ {company_id} has failed {failures[company_id]} checks in a row. "
                "New jobs there can be missed until this is fixed."
            )
            warned.add(company_id)
    return failures, sorted(warned), messages


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
    health: dict[str, Any], outcomes: dict[str, bool], status: ScoringStatus, now: datetime
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Returns the new health and the messages to send."""
    failures, warned, company_messages = _update_companies(health, outcomes)
    scoring_warned, scoring_messages = _update_scoring(bool(health.get("scoringWarned")), status)
    last_sent = health.get("lastDailyMessage", "")
    daily = _daily_message(last_sent, now, len(outcomes), warned)
    new_health = {
        "failures": failures,
        "warned": warned,
        "scoringWarned": scoring_warned,
        "lastDailyMessage": now.date().isoformat() if daily else last_sent,
    }
    return new_health, (*company_messages, *scoring_messages, *daily)


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
