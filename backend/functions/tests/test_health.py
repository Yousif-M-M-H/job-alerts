"""Failure warnings fire once, recover once, and the daily message fires once a day."""
from datetime import datetime, timezone

from job_alerts.health import FAILURES_BEFORE_WARNING, ScoringStatus, evaluate, scoring_status
from job_alerts.models import PollResult

MORNING = datetime(2026, 11, 6, 14, tzinfo=timezone.utc)
SETTLED = {"lastDailyMessage": "2026-11-06"}
FINE = ScoringStatus()


def run(health, outcomes, status=FINE, now=MORNING):
    return evaluate(health, outcomes, status, now)


def test_warns_only_after_repeated_failures_and_only_once():
    health, sent = {**SETTLED}, []
    for _ in range(FAILURES_BEFORE_WARNING + 3):
        health, messages = run(health, {"sel": False})
        sent.extend(messages)
    assert len(sent) == 1 and "sel" in sent[0]


def test_success_resets_the_failure_count():
    health, _ = run(SETTLED, {"sel": False})
    health, _ = run(health, {"sel": True})
    for _ in range(FAILURES_BEFORE_WARNING - 1):
        health, messages = run(health, {"sel": False})
        assert messages == ()


def test_recovery_message_sent_once():
    health = {**SETTLED, "warned": ["sel"], "failures": {"sel": 9}}
    health, messages = run(health, {"sel": True})
    assert len(messages) == 1 and "working again" in messages[0]
    assert run(health, {"sel": True})[1] == ()


def test_scoring_warning_once_then_recovery():
    failing = ScoringStatus(has_failure=True)
    health, first = run(SETTLED, {"sel": True}, failing)
    _, second = run(health, {"sel": True}, failing)
    _, recovered = run(health, {"sel": True}, ScoringStatus(has_success=True))
    assert "scoring" in first[0] and second == () and "working again" in recovered[0]


def test_scoring_stays_warned_when_no_jobs_were_scored():
    health, _ = run(SETTLED, {"sel": True}, ScoringStatus(has_failure=True))
    health, messages = run(health, {"sel": True}, FINE)
    assert messages == () and health["scoringWarned"] is True


def test_scoring_status_reads_results():
    failed = PollResult("a", alerted_scores=(None,))
    scored = PollResult("b", alerted_scores=(88,))
    rejected = PollResult("c", rejected_score=(("1", 10),))
    assert scoring_status((failed,)) == ScoringStatus(has_failure=True, has_success=False)
    assert scoring_status((scored,)) == ScoringStatus(has_failure=False, has_success=True)
    assert scoring_status((rejected,)).has_success
    assert scoring_status(()) == FINE


def test_first_ever_run_sends_daily_message_at_any_hour():
    night = datetime(2026, 11, 6, 3, tzinfo=timezone.utc)
    health, messages = run({}, {"a": True, "b": True}, now=night)
    assert "watching 2 boards" in messages[0] and health["lastDailyMessage"] == "2026-11-06"


def test_daily_message_waits_for_morning_and_sends_once():
    yesterday = {"lastDailyMessage": "2026-11-05"}
    early = datetime(2026, 11, 6, 3, tzinfo=timezone.utc)
    assert run(yesterday, {"a": True}, now=early)[1] == ()
    health, messages = run(yesterday, {"a": True})
    assert len(messages) == 1 and "No problems" in messages[0]
    assert run(health, {"a": True})[1] == ()


def test_daily_message_names_problems():
    health = {"lastDailyMessage": "2026-11-05", "warned": ["sel"], "failures": {"sel": 5}}
    _, messages = run(health, {"sel": False})
    assert "Problems: sel" in messages[0]
