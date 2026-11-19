"""Failure warnings fire once, recover once, and the daily message fires once a day."""
from datetime import datetime, timezone

from job_alerts.health import FAILURES_BEFORE_WARNING, SUCCESSES_BEFORE_RECOVERY, ScoringStatus, evaluate, scoring_status
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


def test_recovery_needs_several_successes_and_is_sent_once():
    health = {**SETTLED, "warned": ["sel"], "failures": {"sel": 9}}
    for _ in range(SUCCESSES_BEFORE_RECOVERY - 1):
        health, messages = run(health, {"sel": True})
        assert messages == ()
    health, messages = run(health, {"sel": True})
    assert len(messages) == 1 and "working again" in messages[0].lower() and "sel" in messages[0]
    assert run(health, {"sel": True})[1] == ()


def test_a_flapping_board_sends_one_warning_and_nothing_more():
    health, sent = {**SETTLED}, []
    pattern = [False] * FAILURES_BEFORE_WARNING + [True, False, False, False] * 20
    for is_ok in pattern:
        health, messages = run(health, {"bcbst": is_ok})
        sent.extend(messages)
    assert len(sent) == 1 and "bcbst" in sent[0]


def test_short_blips_do_not_warn_when_the_board_worked_recently():
    from datetime import timedelta

    health, _ = run(SETTLED, {"sel": True})
    for minutes in range(5, 60, 5):  # 11 failures, all within an hour of the last success
        health, messages = run(health, {"sel": False}, now=MORNING + timedelta(minutes=minutes))
        assert messages == ()
    _, messages = run(health, {"sel": False}, now=MORNING + timedelta(minutes=60))
    assert len(messages) == 1 and "sel" in messages[0]


def test_changes_in_one_run_come_as_one_message():
    health = {**SETTLED, "failures": {"a": 2, "b": 2}}
    _, messages = run(health, {"a": False, "b": False})
    assert len(messages) == 1 and "a" in messages[0] and "b" in messages[0]


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


def test_interval_company_waits_its_turn():
    from datetime import timedelta
    from job_alerts.health import is_due
    from job_alerts.models import Company

    msft = Company("microsoft", "Microsoft", "eightfold", {}, check_every_minutes=15)
    health = {"lastChecked": {"microsoft": MORNING.isoformat()}}
    assert not is_due(msft, health, MORNING + timedelta(minutes=10))
    assert is_due(msft, health, MORNING + timedelta(minutes=14))  # 2 min slack for late starts
    assert is_due(msft, {}, MORNING)
    assert is_due(Company("sel", "SEL", "workday", {}), health, MORNING)


def test_skipped_company_keeps_failure_count_and_board_count():
    health = {**SETTLED, "failures": {"microsoft": 2}}
    health, _ = run(health, {"sel": True})
    assert health["failures"] == {"microsoft": 2}
    _, messages = evaluate(health, {"microsoft": False}, FINE, MORNING)
    assert "microsoft" in messages[0]
    _, daily = evaluate({"lastDailyMessage": "2026-11-05"}, {"sel": True}, FINE, MORNING, board_count=12)
    assert "watching 12 boards" in daily[0]


def test_checked_companies_are_stamped():
    health, _ = run(SETTLED, {"sel": True})
    assert health["lastChecked"] == {"sel": MORNING.isoformat()}
