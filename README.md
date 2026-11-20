# Job Alerts

A personal bot that watches company career pages and sends a Telegram message when a **new** job is posted
that matches my CV. Alerts only: applying happens on the company's site. Design notes and decisions: [docs/PLAN.md](docs/PLAN.md).

## How it runs

```
cron-job.org (every 5 min) -> GitHub Actions (.github/workflows/poll.yml) -> python -m job_alerts.cli
  per company: list jobs -> skip seen IDs -> title filter -> details -> USA only -> clearance/sponsorship skip
  -> Claude Haiku scores against the CV (0-100) -> score >= 60 -> Telegram alert -> save seen IDs (state.json)
```

- **Workday requests go through curl (since 2026-11-19):** from GitHub's servers, Workday throttles Python HTTP
  clients but not curl. Test on 3 `ubuntu-latest` servers, 10 interleaved requests per client: curl (HTTP/1.1 and
  HTTP/2) 60 of 60 `200`; `requests` and `httpx` (HTTP/1.1 and HTTP/2) `429` on 77 of 90. Same headers and
  User-Agent (`job-alerts/0.1`) everywhere, so it is how the client connects, not the server address or headers.
  The Workday adapter calls curl (`fetch_json_curl` in `adapters/http.py`); the other adapters still use `requests`.
  If Workday starts returning `429` from GitHub again, rerun that comparison with a throwaway `workflow_dispatch`
  workflow (repeat each client 10+ times: single requests misled us once, see below).

- **Trigger:** cron-job.org sends a POST to the workflow's `dispatches` API every 5 minutes. It uses a fine-grained
  token from the **Yousif-M-M-H** account (only `job-alerts`, Actions: read and write). The token **expires 2027-02-09**.
  To renew it, make a new token and set the `Authorization: Bearer <token>` header on cron-job.org. GitHub's own
  `schedule` stays on as a slow backup (it runs only every few hours).
- **State:** `backend/functions/state.json` (seen job IDs) and `health.json` (failure counts, last check times,
  daily message) are committed by the workflow after every run (`.github/scripts/save-state.sh` rebases and
  retries a rejected push). Runs check out the latest `main`.
- **Secrets (GitHub repo settings):** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `ANTHROPIC_API_KEY`, `CV_TEXT`.
  The repo is public: never print the CV, scores' reasons or secrets to logs.
- **Health messages on Telegram:** "⚠️ Not working" once a company has failed 3 checks in a row **and** had no
  successful check for an hour; "✅ Working again" only after 3 successes in a row; all changes in one run come as
  one message (`health.py`). A run is red only when it sends a new warning. Also a warning if scoring fails, and a
  daily "🟢 still running" message after 13:00 UTC. (Before 2026-11-19 a single success cleared a warning, so boards
  that got through now and then sent ~300 messages a day; replaying Nov 16-19 with the new rules gives 5-10.)

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

## Status and next steps (updated 2026-11-19, start a new session here)

Context: I graduate in **May 2027** and want new-grad software/firmware/embedded roles, so speed and new-grad fit
matter most.

### What happened (2026-11-09 to 2026-11-19, full diagnosis done 2026-11-19)
- **Workday rate limit.** From about 07:00 UTC on 2026-11-16, Workday answered almost every check with `429`. SEL,
  Caterpillar, ABB and Generac had about 0% successful checks for 3 days; the other Workday boards 3-20%. Measured:
  Workday returns `429` after **about 6 quick requests to one board**, from a home connection too, and the adapter
  sent pages back-to-back. Big boards (16-25 pages) could never finish.
- **Warning flood.** A single lucky success cleared a warning, so flapping boards sent about 1,160 health messages in
  10 days against **34 job alerts** (26 Microsoft, 6 Schwab, 2 SEL, none from the other 16 boards).
- **Weak targeting.** Senior titles got past the title filter (`titleAlways` beat `titleExclude`) and the scorer did
  not know I am a new grad. Most alerts scored 62-72, just over `minScore: 60`.
- An earlier Workday outage (521 errors / "did not return JSON") hit on 2026-11-13/14 and recovered on its own.

### Deployed 2026-11-19 (live on `main`)
- `d3e49ec` **New-grad targeting:** the scorer prompt (`matching/rerank.py`) says I graduate May 2027, ranks entry-level
  higher and 3-5+ year roles and internships below 40; titles with senior/sr/staff/principal/lead/manager are skipped
  for every company before `titleAlways` (`SENIOR_TITLE_TERMS` in `filters.py`).
- `505f0f7` **Workday pacing:** requests 5 s apart (`REQUEST_INTERVAL_SECONDS` in `adapters/workday.py`), at most 3
  Workday boards per run (`MAX_BOARDS_PER_RUN` in `cli.py`, the rest go first next run), Workday checked every 30 min
  (Zebra 60), `429` not retried, the rest of a job system skipped for the run after a `429`, workflow timeout 15 min.
- `a7bd036` **No more warning flapping** (`health.py`): "⚠️ Not working" after 3 failures in a row **and** an hour with
  no success; "✅ Working again" only after 3 successes in a row; one combined message per run; a run is red only when
  it sends a new warning. Replaying Nov 16-19 gives 5-10 messages a day instead of 220-320.

- **Pacing was not enough (checked 2026-11-19 23:00 UTC):** over 30 runs after `505f0f7`, 49 of 52 Workday attempts
  got `429` on the run's first Workday request. curl got `200` from every GitHub server type. A one-request test
  suggested HTTP/2 fixed Python; it didn't (3 of 3 live runs still `429`), and a 10-request-per-client test showed
  curl is what gets through. Fixed by sending Workday requests through curl (see "Workday requests go through curl"
  above). A self-hosted runner on the home Mac was used for about 30 minutes in between and has been removed.

### Do first in a new session: check that the fixes worked
1. **Workday checks succeed.** `gh run list -R Yousif-M-M-H/job-alerts --workflow poll.yml --limit 20`, then open a
   recent run's "Poll and alert" log. Expect Workday boards with `open jobs` lines and no `RATE LIMITED`. Target:
   every Workday board succeeds on 95%+ of checks over 24 h, and `failures` in `backend/functions/health.json`
   stays at 0 for SEL.
   - If `429`s continue: raise `REQUEST_INTERVAL_SECONDS` (try 8-10 s) and/or lower `MAX_BOARDS_PER_RUN` to 2.
   - Check run time stays well under the 15 min timeout (`gh run list` shows durations).
2. **Telegram is quiet.** The daily 🟢 message (after 13:00 UTC) should list few or no "Problems", with only a handful
   of ⚠️/✅ messages a day. The companies still in `warned` from before need 3 good checks in a row to clear.
3. **Alerts look right.** Over a week, alerts should be entry-level roles, more of them from SEL and the other Workday
   companies.

### Remaining work, in priority order
4. **Log job titles** (not the scorer's reasons) for alerted and title-rejected jobs, so alert quality and the title
   filter can be judged from the logs (now only IDs and scores are logged). Titles are public, so this is safe in a
   public repo. Example gap: SEL rejected 68 of 76 new jobs on title, and the logs can't show which.
5. **Drop the duplicate board:** all 26 `itron_early` jobs are also on `itron`. Remove `itron_early` or skip jobs
   already alerted with the same company + title + location (also catches reposts with a new ID).
6. **Weekly near-miss list** (scores 45-59) to tune `minScore: 60`; scores bunch at 22/35/42/62/72.
7. **Early-career boards:** add companies' separate new-grad/university boards, but only ones that are not copies of
   the main board (see 5).
8. **👍 / 👎 buttons** on Telegram alerts, read with `getUpdates` each run; feed 👎 reasons into scoring. Also
   `/status` and `/pause <company>` commands.
9. **More companies:** power/grid companies like SEL with a real H-1B record for software roles (h1bdata.info).
   Already rejected for rare or no sponsorship: Woodward, nVent, Xylem/Sensus, Badger Meter. For any company named,
   check its job system (Workday / Greenhouse / Lever / Ashby / iCIMS) and H-1B record, then add.
10. **Reminders before it stops:** Telegram reminder 2 weeks before the GitHub token expires (2027-02-09), and turn on
    cron-job.org's failure email.
11. **Failure counts:** a board skipped because another Workday board already got a `429` counts as a failure
    (`poll_all` in `cli.py`), which inflates `failures` in `health.json`.

### Notes for analysis sessions
- Downloading logs for thousands of runs uses up the account's GitHub API limit (5,000 requests/hour), which the
  cron-job.org token shares. On 2026-11-19 this happened for about an hour; runs kept going, but fetch only the runs
  you need (for example, only runs whose `state.json` commit added new job IDs).
- `health.json` and `state.json` are committed after every run, so `git log` of those files is a full history of
  checks, failures and new jobs without using the API.

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

A run is red only when it sends a new Telegram "Not working" warning, so each real incident gives one red run. Single blips (timeouts, 5xx, a `429` rate
limit) stay green but are still logged as `<company>: FAILED: ...` or `<company>: RATE LIMITED ...`.
While a board stays down, later runs are green again; the Telegram "working again" message and the
daily "Problems: ..." line tell you when it is fixed. Example: on 2026-11-13/14 Workday returned
521 errors for about 22 hours (SEL, Bentley, Itron, BCBST, Caterpillar) and recovered on its own.
