# Solicitation Agent

A personal workflow tool that automatically searches federal government databases for contract and grant opportunities relevant to Branch Technology's core offerings — BranchRegenerate (a 3D-printed building energy retrofit system) and Cellular Fabrication (large-format additive manufacturing for construction).

## What it does

- Searches SAM.gov by NAICS code for active solicitations
- Searches SBIR.gov for open topics matching relevant keywords
- Searches Grants.gov for open opportunities across DOE, DoD, and NASA
- Scores and ranks results by keyword relevance
- Sends results to Claude (Anthropic) for analysis and synthesis into a weekly intelligence brief
- Saves the report to Google Sheets for archiving
- Emails the formatted report automatically

## Technologies used

- Python
- Anthropic Claude API
- SAM.gov API
- SBIR.gov API
- Grants.gov API
- Google Sheets & Drive API
- Gmail SMTP

## Notes

This tool was built as a personal productivity tool to support government business development workflow. Credentials and API keys are managed via environment variables and are not included in this repository.