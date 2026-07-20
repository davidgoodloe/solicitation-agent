# STATUS.md — Live State

Last updated: 2026-07-01

## Current Phase

Ported from a prior laptop and running again. Fully operational; scheduled runs are live via launchd.

## What's Working

- SAM.gov, Grants.gov, DSIP, HUD PD&R, DOE EERE eXCHANGE searches
- Claude synthesis into the weekly brief
- Google Sheets archiving ([sheet](https://docs.google.com/spreadsheets/d/1mCXb2e0SyU-Fbd7O_Vficumg7XfycVm93-WwOOg8_Vs))
- Gmail delivery to david.goodloe@branch.technology
- Scheduled via launchd (`~/Library/LaunchAgents/com.davidgoodloe.solicitation-agent.plist`): Monday 10:00am and Wednesday 3:00pm (retimed 2026-07-20 to hours David is reliably at his laptop, after an 8am Monday run failed with total DNS resolution failure — laptop likely asleep/off-network at trigger time). Logs at `~/Library/Logs/solicitation-agent/{stdout,stderr}.log`.

## What's Broken

- **SBIR.gov API returns 403 Forbidden.** Pre-existing, not caused by the port — same error appears in `output_log.txt` from the old machine on at least 3 prior runs. Likely needs an API key/auth update or the endpoint changed. Not yet root-caused.

## Known Fragile Points

- Google OAuth `token.json` refresh_token went dead once already (invalid_grant) between machines/over time. If a scheduled run silently fails, check this first — re-run the `InstalledAppFlow` browser login to refresh it.
- No automated alerting if a scheduled run fails (e.g., due to the OAuth token going stale again) — worth periodically checking the log files or the sheet.

## Next

- Root-cause the SBIR.gov 403 (check if sbir.gov now requires an API key, or if the endpoint URL changed).
- Nothing else currently queued.
