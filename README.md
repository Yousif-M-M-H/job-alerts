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

## Companies watched (18 companies, 19 boards, `backend/functions/companies.json`)

| id | Company | ATS adapter | Notes |
|---|---|---|---|
| sel | Schweitzer Engineering Labs | workday | all Workday boards: `checkEveryMinutes: 30` (see Open issue) |
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
| zebra | Zebra Technologies | workday | `wd501` host; `searchText: software`, `checkEveryMinutes: 60`. Its site rate-limits GitHub's servers (works from a home connection); if hourly still fails, pause it |
| trimble | Trimble | workday | |
| cognex | Cognex | workday | |
| adtran | ADTRAN | workday | |
| generac | Generac | workday | |

All companies: USA locations only, alert threshold `minScore: 60`.

The last 5 (added 2026-11-15) were picked for size (similar to SEL) and an H-1B record of sponsoring software
roles (h1bdata.info filings, 2023-2026). Checked and left out for rare or no software sponsorship: Woodward,
nVent, Xylem/Sensus, Badger Meter (none). Lattice Semiconductor is borderline.

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

## Next steps (planned improvements)

Context: I graduate in **May 2027** and am looking for new-grad software/firmware/embedded roles, so speed and
new-grad fit matter most. Do these in order; 1 and 2 together first.

**For the job search now**
1. ~~**New-grad scoring.**~~ Done 2026-11-15: the scorer prompt (`matching/rerank.py`) says I graduate May 2027,
   ranks "Software Engineer I" / "Associate" / "New Grad" / "Early Career" higher, and scores roles asking 3-5+ years
   (and internships) below 40.
2. ~~**Skip senior roles.**~~ Done 2026-11-15: titles with "senior", "sr", "staff", "principal", "lead" or "manager"
   are skipped for every company before scoring (`SENIOR_TITLE_TERMS` in `filters.py`). It is a built-in list, not
   `titleExclude`, because `titleAlways` beats `titleExclude` and would let "Senior Software Engineer" through.
3. **Early-career boards.** Add companies' separate new-grad/university boards, like `itron_early`.

**Better alerts**
4. **👍 / 👎 buttons** on Telegram alerts, read with `getUpdates` each run; feed 👎 reasons into scoring. Also
   `/status` and `/pause <company>` commands.
5. **No duplicate alerts.** Skip a job already alerted with the same company + title + location (two boards of one
   company, or a repost with a new ID).
6. **Weekly near-miss list.** Jobs scoring 45-59, to tune `minScore: 60`.

**More companies**
7. **Better power/grid companies** like SEL with a real H-1B record for software roles (check h1bdata.info).
   Already rejected for rare or no sponsorship: Woodward, nVent, Xylem/Sensus, Badger Meter.
8. **Any company named:** check its job system (Workday / Greenhouse / Lever / Ashby / iCIMS) and H-1B record, then add.

**Keeping it running**
9. **Reminders before it stops:** Telegram reminder 2 weeks before the GitHub token expires (2027-02-09), and turn on
   cron-job.org's failure email.

**Open issue: Workday rate-limits GitHub's servers.** Since about 07:00 UTC on 2026-11-16 every Workday board
gets `429` from GitHub Actions on almost every run (single requests work from a home connection, but bursts get 429 there too). Reduced load
the same day:
- a `429` is no longer retried (`RETRY_STATUSES` in `adapters/http.py`);
- after the first `429` in a run, the other boards on that job system are skipped for the run (`poll_all` in `cli.py`);
- Workday boards are checked every 30 min (`checkEveryMinutes: 30`; Zebra stays at 60).
- Workday requests are paced 5 s apart (`REQUEST_INTERVAL_SECONDS` in `adapters/workday.py`), and a run checks at
  most 3 Workday boards (`MAX_BOARDS_PER_RUN` in `cli.py`); the rest go first next run. Measured 2026-11-19: Workday
  returns `429` after about 6 quick requests to one board, **from a home connection too**, so pacing is the real fix.
  The workflow timeout is 15 min to fit the slower runs.

If the daily message still lists the Workday companies under "Problems" after a day, the next option is to run the
poll from a self-hosted GitHub runner on a home machine (it only runs while that machine is on), or pause them.

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

A run is red only when a company reaches **3 failed checks in a row**, the same moment the Telegram
warning is sent, so each real incident gives one red run. Single blips (timeouts, 5xx, a `429` rate
limit) stay green but are still logged as `<company>: FAILED: ...` or `<company>: RATE LIMITED ...`.
While a board stays down, later runs are green again; the Telegram "working again" message and the
daily "Problems: ..." line tell you when it is fixed. Example: on 2026-11-13/14 Workday returned
521 errors for about 22 hours (SEL, Bentley, Itron, BCBST, Caterpillar) and recovered on its own.
