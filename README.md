# Job Alerts

A personal bot that watches company career pages and sends a Telegram message when a **new** job is posted
that matches my CV. Alerts only: applying happens on the company's site. Design notes and decisions: [docs/PLAN.md](docs/PLAN.md).

## How it runs

```
cron-job.org (every 5 min) -> GitHub Actions (.github/workflows/poll.yml) -> python -m job_alerts.cli
  per company: list jobs -> skip seen IDs -> title filter -> details -> USA only -> clearance/sponsorship skip
  -> Claude Haiku scores against the CV (0-100) -> score >= 60 -> Telegram alert -> save seen IDs (state.json)
```

- **Trigger:** cron-job.org sends a POST to the workflow's `dispatches` API every 5 minutes. It uses a fine-grained
  token from the **Yousif-M-M-H** account (only `job-alerts`, Actions: read and write). The token **expires 2027-02-09**.
  To renew it, make a new token and set the `Authorization: Bearer <token>` header on cron-job.org. GitHub's own
  `schedule` stays on as a slow backup (it runs only every few hours).
- **State:** `backend/functions/state.json` (seen job IDs) and `health.json` (failure counts, last check times,
  daily message) are committed by the workflow after every run. Runs check out the latest `main`.
- **Secrets (GitHub repo settings):** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `ANTHROPIC_API_KEY`, `CV_TEXT`.
  The repo is public: never print the CV, scores' reasons or secrets to logs.
- **Health messages on Telegram:** a warning after 3 failed checks in a row for a company (and a "working again"
  message), a warning if scoring fails, and a daily "🟢 still running" message after 13:00 UTC.

## Companies watched (13, `backend/functions/companies.json`)

| id | Company | ATS adapter | Notes |
|---|---|---|---|
| sel | Schweitzer Engineering Labs | workday | |
| microsoft | Microsoft | eightfold | newest 5 pages of "software"; `checkEveryMinutes: 15`; still rate-limits now and then (see below) |
| mesa | Mesa | ukg_pro | |
| profisee | Profisee (the CBIZ20626 board) | ukg_ready | |
| landisgyr | Landis+Gyr | successfactors | HTML |
| bentley | Bentley Systems | workday | |
| itron, itron_early | Itron (main + Early Careers) | workday | a job on both boards can alert twice |
| bcbst | BlueCross BlueShield of Tennessee | workday | |
| caterpillar | Caterpillar | workday | `searchText: software` (full board is 1000+) |
| alaska | Alaska Airlines (+ Horizon, Hawaiian) | jobsyn | DirectEmployers API |
| asurion | Asurion | workday | |
| abb | ABB | workday | `searchText: software` (full board is 2000+) |
| schwab | Charles Schwab | icims | HTML (`career-schwab.icims.com`, full board ~300 jobs, 7 pages). Its Workday tenant needs a login |

All companies: USA locations only, alert threshold `minScore: 60`.

**Not watched, and why:** Tesla and HCA Healthcare (sites return 403 to automated requests; we don't bypass blocks),
S&C Electric (403, job system not found), FedEx (Paradox site, page data only has ~25 package-handler jobs),
Epic Systems (only ~15 permanent role pages, nothing new to alert on).

## Adding a company

1. Find its job system. The easiest are **Greenhouse, Lever and Ashby** (one public API call, no scraping):
   look at the apply link on the careers page and copy the board name from it, then use
   `"ats": "greenhouse"` / `"lever"` / `"ashby"` with `"atsConfig": {"board": "<name>"}`.

   | Apply link looks like | ats | board |
   |---|---|---|
   | `boards.greenhouse.io/stripe` or `?gh_jid=` | greenhouse | `stripe` |
   | `jobs.lever.co/palantir/...` | lever | `palantir` |
   | `jobs.ashbyhq.com/ramp/...` | ashby | `ramp` |

   Check a board name works: `curl -s https://boards-api.greenhouse.io/v1/boards/<name>/jobs | head -c 200`
   (Lever: `https://api.lever.co/v0/postings/<name>`, Ashby: `https://api.ashbyhq.com/posting-api/job-board/<name>`).

   Otherwise, it is often Workday: try
   `POST https://<host>/wday/cxs/<tenant>/<site>/jobs` with `{"appliedFacets":{},"limit":20,"offset":0,"searchText":""}`.
   The `<host>/<site>` usually shows up in the apply links on the careers page.
2. Add an entry to `companies.json` (copy the caterpillar entry for its software title filter). Add `searchText`
   for huge boards.
3. A new job system needs an adapter in `backend/functions/job_alerts/adapters/` plus a line in `registry.py`.
4. Run the tests, push, then trigger a run. A new company's first run is a **baseline**: it marks every current job
   as seen and sends nothing.

## Developing

```bash
cd backend/functions
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

Useful commands:

```bash
gh run list -R Yousif-M-M-H/job-alerts --workflow poll.yml --limit 10
gh workflow run poll.yml -R Yousif-M-M-H/job-alerts
```

Runs: https://github.com/Yousif-M-M-H/job-alerts/actions/workflows/poll.yml

A run is red when **any** company fails; the other companies were still checked. The log line
`<company>: FAILED: ...` shows which one. A **429 rate limit** is not a failure: the log says
`<company>: RATE LIMITED, will retry next run` and the run stays green. It still counts toward the
3-failures-in-a-row Telegram warning, so a board that blocks us for good is still reported.
