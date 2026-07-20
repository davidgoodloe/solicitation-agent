# AGENTS.md — Solicitation-Searching Agent

This file provides durable guidance to Codex when working in this project. Live state (current phase, what's working, what's broken, what's next) belongs in `STATUS.md`, not here.

---

## Read First

Before starting any work, read:
1. `~/Codex/BranchRegenerate/guide/ONBOARDING.md` — working methodology
2. `~/Codex/BranchRegenerate/guide/README.md` — methods index
3. `~/Codex/BranchRegenerate/guide/BR-master-context.md` — BranchRegenerate product, GTM, and vocabulary context

Reference individual methods in `~/Codex/BranchRegenerate/guide/methods/` as needed.

---

## What This Is

A personal Python workflow tool that automatically searches federal government databases for contract and grant opportunities relevant to Branch Technology's offerings, scores and ranks results, sends them to Codex for synthesis, and delivers a formatted weekly intelligence brief via email, archived to Google Sheets.

This is a **solo internal tool**, not a product. Optimize for reliability and maintainability over elegance. David is the only user.

---

## Why It Exists

Manual federal opportunity monitoring across SAM.gov, SBIR.gov, and Grants.gov is time-consuming and easy to let slip. This tool closes that gap — surfacing relevant solicitations weekly without requiring David to search manually. The output feeds directly into BR's GTM pipeline (grant pursuit, federal sales, SBIR tracking).

---

## Tech Stack

| Component | Technology |
|---|---|
| Language | Python |
| AI synthesis | Anthropic Codex API |
| Federal search | SAM.gov API, SBIR.gov API, Grants.gov API |
| Output / archiving | Google Sheets & Drive API |
| Delivery | Gmail SMTP |
| Credentials | Environment variables (never hardcoded) |

---

## What It Does (pipeline)

1. Searches **SAM.gov** by NAICS code for active solicitations
2. Searches **SBIR.gov** for open topics matching relevant keywords
3. Searches **Grants.gov** for open opportunities across DOE, DoD, and NASA
4. Scores and ranks results by keyword relevance
5. Sends results to **Codex API** for analysis and synthesis into a weekly intelligence brief
6. Saves the report to **Google Sheets** for archiving
7. Emails the formatted report automatically

---

## Key Design Constraints

- Credentials and API keys are managed via **environment variables only** — never write keys or secrets into code or commit them
- **NEVER print, read aloud, or otherwise display the value of an API key, password, token, or other secret in the conversation** — this includes `.env` contents, tool output, or any other channel visible in chat. If you need to confirm a `.env` file's structure, list variable *names* only (e.g. `grep -o '^[A-Z_]*=' .env`), never their values. If a secret must be changed, either let the user edit the file themselves or make the edit via a non-echoing method (e.g. `sed`) without displaying the before/after value.
- This is a single-developer tool — don't over-engineer; favor readable, maintainable Python over abstraction
- The output is a **weekly brief**, not a real-time dashboard — batch processing is fine

---

## Files in This Project

| File | Description |
|---|---|
| `AGENTS.md` | This file — durable project facts and instructions |
| `README.md` | Project overview (public-facing summary) |
| `STATUS.md` | Live state: current phase, what's working, what's broken, next action *(create this)* |
| *(add main script, config, etc. as they exist)* | |

---

## Open Items — Confirm Before Building

1. **Current state** — is this tool partially built, fully built, or starting from scratch on the new machine? What's working?
2. **NAICS codes in use** — which codes are being searched on SAM.gov? (Relevant: 236220 commercial/institutional construction, 541330 engineering services, 541715 R&D in physical sciences)
3. **Keywords** — what keyword list is currently used for SBIR/Grants.gov scoring?
4. **Delivery cadence** — weekly on a specific day, or triggered manually?
5. **Codex model in use** — which model is the API call hitting, and what does the synthesis prompt look like?
6. **Google Sheets destination** — is the archive sheet already set up?
