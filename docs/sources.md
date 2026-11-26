# Source audit and policy matrix

Owner: Zhaniya (Part B). Audit date: 26 Nov 2026. Re-check every source before the Spring pilot and whenever an
adapter starts failing with HTTP 403 or a robots.txt change.

Rules we follow for every source (kickoff, "Risks: source access or policy restrictions"):

1. Prefer an official API, feed or the employer's own site over third-party aggregators.
2. Respect robots.txt (RFC 9309) for anything that is not an official API; the adapter checks it on every run.
3. Identify ourselves: `User-Agent: InternshipBoardKZ/0.1 (NU senior project; contact: team26@nu.edu.kz)`.
4. Low rate: at most 1 request per second per host, collection every 6 to 24 hours.
5. Store only the posting (title, employer, text, link, dates). Never collect applicants' or recruiters' personal data.
6. Every card links back to the original posting and shows the source name (attribution).
7. A source can be switched off in one command (`python -m app.cli disable-source <key>`), which hides its vacancies.

## Matrix

| Source | Access method | Terms / robots | Personal data | Freshness | Decision |
|---|---|---|---|---|---|
| **hh.kz** (HeadHunter) | Official REST API `api.hh.ru/vacancies`, `area=40` (Kazakhstan) | API terms apply. **Since 2026 anonymous requests get HTTP 403**; an application token from dev.hh.ru is required, with manual moderation that can take up to 15 working days | Employer contact fields are not stored | Every 6 h | **MVP live source once the token is approved.** Adapter `hh_kz` is ready and tested with fixtures. Apply for the token now. |
| **inDrive Careers** (careers.indrive.com) | Public WordPress REST API, post type `open_position` | robots.txt: `Disallow:` empty for all agents (allows everything), checked 26 Nov 2026 | None in postings | Every 12 h, Kazakhstan postings only | **MVP live source (works today, no credentials).** Adapter `indrive_careers`. Few internships, mostly junior/middle roles. |
| Other employer career sites (Kaspi, Kolesa Group, Halyk, Beeline KZ, EPAM KZ, Big 4 in Almaty/Astana) | Varies: WordPress API, ATS boards (Greenhouse, Lever, SmartRecruiters, Huntflow), plain HTML | Audit per site: robots.txt + terms | Usually none | 12 to 24 h | **Spring.** Each one is a config entry if it runs WordPress (`WordPressJobsAdapter`); ATS boards need a small adapter each. Audit before adding. |
| Telegram channels (student job channels, company channels) | Telegram API needs a user account and app id; `t.me/s/<channel>` web preview is HTML | Telegram API terms must be reviewed; channel owners' rules vary | Posts may contain recruiter names/phones | Near real time | **Fall: manual collection into the seed file only** (with the post link). Spring: ask 2 or 3 channel owners for permission, then decide on an API adapter. |
| LinkedIn | No public jobs API for this use | LinkedIn's User Agreement prohibits automated scraping | Profiles of recruiters | n/a | **Rejected for automation.** Postings a team member saw may be copied manually into the seed/evaluation set with the link. |
| enbek.kz (state e-labour exchange) | Web portal; no public vacancy API found in this audit | To check with the operator (Center for Labor Resources Development) | Some postings list contact persons | n/a | **Spring: request data access officially.** Large volume, but few IT internships. |
| NU Career & Advising emails, university career fairs | Forwarded emails / PDFs | Ask Career & Advising for permission to republish | Contact persons | Weekly | **Seed only** (manual CSV), with permission. |
| Employer self-submission | Form on our site | Our own terms | Employer contact (kept private) | Immediate | **Stretch goal** (kickoff, Spring). |

## Live source for the Fall MVP

* **Now:** `indrive_careers`. It works without credentials and shows the full pipeline end to end (adapter → raw
  snapshot → extraction → dedup → feed).
* **As soon as the token arrives:** `hh_kz`, the main source of intern and junior postings in Kazakhstan. Put the token
  in `.env` (`HH_APP_TOKEN=...`) and run `python -m app.cli run-source hh_kz --limit 20` once by hand before
  enabling the schedule.
* **If the hh token is refused:** add two or three more employer career sites through `WordPressJobsAdapter`, or ATS
  job-board APIs, after auditing each one.

## Placeholder until the token arrives

Without `HH_APP_TOKEN`, source `hh_kz` runs in **stub mode**: it loads `backend/data/hh_stub/vacancies.json` (6 postings
with fictional employers, in the exact hh.ru API format) through the same mapping code as the real API. These postings are
labelled "HeadHunter (DEMO STUB, token pending)" and have ids starting with `stub-`. To switch to the real API, put
the token in `.env` and run `python -m app.cli disable-source hh_kz` then `enable-source hh_kz` (hides the stub
postings), then `run-source hh_kz`.

## Evidence for the hh.kz finding

hh.ru closed the applicant API on 15 Dec 2025, and third-party guides report that `/vacancies` returns 403 without a
token (checked 19 Nov 2026). We could not call api.hh.ru from our build environment, so verify with your own token:
`curl -H "HH-User-Agent: ..." -H "Authorization: Bearer $HH_APP_TOKEN" "https://api.hh.ru/vacancies?area=40&per_page=1"`.
