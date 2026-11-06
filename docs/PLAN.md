# Job Alerts: build plan

One job: hear about a new matching job as soon as it is posted. An instant phone alert with a link. No app.
Applying happens on the company's own site.

## Pipeline

```
about every 5 min, per unpaused company:
  adapter.list_jobs()            ATS JSON, all open postings
  drop already-seen IDs          dedupe by ATS job ID
  first poll of a company?       mark everything seen, alert nothing (baseline)
  cheap filter (title)           free
  adapter.get_details()          only for jobs that passed the title filter
  cheap filter (location)        after details: the list can say "2 Locations"
  LLM score against CV           0-100 + one-line reason
  score >= threshold             Telegram alert with apply link
  mark seen                      only after the alert was sent
```

## Phases

| # | Phase | Done when |
|---|-------|-----------|
| 1 | Adapter, cheap filter, dedupe (done) | Polls live SEL, baseline works, a new job is detected once |
| 2 | Telegram alerts, hosted | Runs on schedule with the laptop closed. A simulated new job reaches the phone |
| 3 | CV scoring | Alerts show score and reason. Below-threshold jobs stay silent |
| 4 | Health alerts | Repeated failures send a Telegram warning |
| 5 | More companies | Greenhouse and Lever adapters, as needed |

Phase 2 alone is already useful: title and location matches reach the phone before any scoring exists.

## What changed and why

| Before | Now | Why |
|---|---|---|
| Flutter iOS app | Telegram bot | Only the alert matters. No $99 Apple account |
| FCM/APNs | Telegram Bot API | Free, instant, a tapped link opens the job |
| Cloud Functions, every 30 min | GitHub Actions, about every 5 min | Free and faster |
| Firestore | `state.json` committed by the workflow | Only seen IDs need storing |
| Cloud Storage for CV | CV text in a GitHub secret | Works in a public repo |
| Embeddings + LLM | LLM only | Few jobs pass the filters, so the embedding step saves almost nothing |
| App settings screens | Edit `companies.json` | Add, remove, pause, threshold: one small file |

## Decisions worth knowing

- **Hosting is a public repo.** Public repos get unlimited Actions minutes. A private repo's free minutes cover
  about every 30 min, not every 5. Only code, job IDs and the watch list are public. The CV text and bot token
  stay in encrypted secrets, and must never be printed to logs.
- **GitHub schedules can run late.** Runs can start several minutes late or be skipped when GitHub is busy. If
  that costs too much speed, move the same code to a small always-on server (about $5/month) with a 1-2 min
  poll. Nothing else changes.
- **Fail open when scoring fails.** If the LLM is down, send the alert marked "not scored". Speed and not
  missing a job beat a little noise.
- **Mark seen only after the alert is sent.** A failed send retries next poll. Rarely, a job could alert twice
  (sent, then the state commit fails), which beats never alerting. Phase 2 must change the pipeline, which
  currently marks jobs seen before returning them.
- **No overlapping runs.** The workflow uses a concurrency group, so two runs can't both alert or clash on state.
- **A silent failure looks exactly like "no new jobs".** Phase 4 warns after repeated failures.
- **A new CV or threshold applies to future jobs only.** Old jobs are not re-scored, so nothing re-alerts.
- **Scoring model is Haiku** (`MODEL` in `matching/rerank.py`). The threshold is `minScore` in `companies.json`.
- **Clearance and sponsorship are hard skips.** A phrase check runs first (free, works if scoring is down), then Claude
  catches other wording. Ability to obtain a clearance later doesn't count on its own.
- **Tesla is not included.** Its careers API returns 403 to automated requests, and we don't bypass blocks.
- **Microsoft reads only the newest 5 pages** of one "software" search, because the board is huge and rate-limits.
- **Logs are public.** They show job IDs and scores only, never the CV or the reason.

## Alert format

```
Firmware Engineer · 88%
SEL · Idaho - Boise
Embedded C++ matches your firmware work.
https://selinc.wd1.myworkdayjobs.com/SEL/job/...
```

## Folder structure

```
job-alerts/
  .github/workflows/poll.yml         schedule, secrets, commit state (phase 2)
  docs/PLAN.md
  backend/functions/
    requirements.txt
    companies.json                   companies, filters, paused, threshold
    state.json                       seen IDs per company, committed by the workflow
    job_alerts/
      models.py, config.py, filters.py, pipeline.py, cli.py
      adapters/                      base, registry, workday, (greenhouse, lever)
      store/                         base, json_store
      notify/telegram.py             (phase 2)
      matching/rerank.py             (phase 3)
    tests/
```

## Secrets (GitHub repo settings)

`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `CV_TEXT`, and the LLM API key (phase 3).

## Costs

| Item | Cost |
|---|---|
| Telegram, GitHub Actions on a public repo | Free |
| LLM scoring | Pennies a month at this volume (needs an API key) |
| Optional always-on server, if GitHub runs too late | About $5/month |
