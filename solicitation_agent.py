import socket

import anthropic
import requests
from dotenv import load_dotenv

# Force IPv4 — api.sam.gov TLS handshake hangs over IPv6
_orig_getaddrinfo = socket.getaddrinfo


def _ipv4_only(*args, **kwargs):
    return [r for r in _orig_getaddrinfo(*args, **kwargs) if r[0] == socket.AF_INET]


socket.getaddrinfo = _ipv4_only
load_dotenv()
import json
import os
import smtplib
import sys
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import markdown as md
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

sys.stdout.reconfigure(encoding="utf-8")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_google_credentials():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return creds


def save_to_sheets(creds, report_text, sam_count, overlap_count):
    service = build("sheets", "v4", credentials=creds)

    spreadsheet_id = os.environ.get("GOOGLE_SHEET_ID")

    if not spreadsheet_id:
        spreadsheet = (
            service.spreadsheets()
            .create(
                body={
                    "properties": {"title": "Branch Technology - Solicitation Reports"},
                    "sheets": [{"properties": {"title": "Reports"}}],
                }
            )
            .execute()
        )
        spreadsheet_id = spreadsheet["spreadsheetId"]
        print(
            f"Created new Google Sheet: https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
        )
        print(f"Add this to your .env: GOOGLE_SHEET_ID={spreadsheet_id}")

        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range="Reports!A1:E1",
            valueInputOption="RAW",
            body={
                "values": [
                    [
                        "Date",
                        "SAM Results",
                        "Keyword Overlaps",
                        "Summary",
                        "Full Report",
                    ]
                ]
            },
        ).execute()

    # Extract first 500 chars as summary
    summary = report_text[:500].replace("\n", " ").strip()

    # Append new row
    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range="Reports!A:E",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={
            "values": [
                [
                    datetime.today().strftime("%Y-%m-%d"),
                    sam_count,
                    overlap_count,
                    summary,
                    report_text,
                ]
            ]
        },
    ).execute()

    print(
        f"Report saved to Google Sheets: https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
    )


client = anthropic.Anthropic()

sam_api_key = os.environ.get("SAM_API_KEY")

NAICS_CODES = ["236220", "238310", "541330", "541712", "541715", "238190", "332311"]
KEYWORDS = [
    "envelope",
    "insulation",
    "retrofit",
    "additive",
    "3D print",
    "weatheriz",
    "energy effici",
    "building",
    "prefabricated",
    "modular",
    "rapid construction",
    "innovative construction",
    "building retrofit",
    "facility modernization",
    "energy resilience",
    "renovation",
    "enclosure",
    "cladding",
    "facade",
    "panel",
    "building modernization",
    "facility renovation",
    "energy conservation",
    "deep energy",
    "thermal envelope",
    "prefabricated construction",
    "modular building",
    "MILCON",
    "ESPC",
]


def search_sam_by_naics(naics_codes):
    today = datetime.today().strftime("%m/%d/%Y")
    ninety_days_ago = (datetime.today() - timedelta(days=90)).strftime("%m/%d/%Y")
    six_months_ago = (datetime.today() - timedelta(days=180)).strftime("%m/%d/%Y")

    all_opportunities = []
    seen_ids = set()

    for naics in naics_codes:
        url = f"https://api.sam.gov/opportunities/v2/search?api_key={sam_api_key}&naics={naics}&limit=25&postedFrom={six_months_ago}&postedTo={today}&ptype=o,k,p,r,s"
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()
            opportunities = data.get("opportunitiesData", [])
            for opp in opportunities:
                notice_id = opp.get("noticeId")
                if notice_id not in seen_ids:
                    seen_ids.add(notice_id)
                    all_opportunities.append(opp)
        except Exception as e:
            print(f"Error searching NAICS {naics}: {e}")

    return all_opportunities


def search_sbir(keywords):
    print(f"\nSearching SBIR.gov for open topics...")
    results = []
    api_errors = []

    for keyword in keywords:
        url = f"https://api.www.sbir.gov/public/api/topics?keyword={keyword.replace(' ', '%20')}&status=open"
        try:
            response = requests.get(
                url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30
            )
            if response.status_code == 403:
                api_errors.append(
                    f"403 Forbidden — API may require authentication or be under maintenance"
                )
                break
            elif response.status_code != 200:
                api_errors.append(
                    f"HTTP {response.status_code} for keyword '{keyword}'"
                )
                continue
            data = response.json()
            if isinstance(data, dict) and "message" in data:
                api_errors.append(f"API message: {data['message']}")
                break
            topics = data if isinstance(data, list) else data.get("topics", [])
            for topic in topics[:5]:
                results.append(
                    f"Title: {topic.get('topic_title', 'N/A')}\n"
                    f"Agency: {topic.get('program_year', 'N/A')} - {topic.get('agency', 'N/A')}\n"
                    f"Branch: {topic.get('branch', 'N/A')}\n"
                    f"Topic #: {topic.get('topic_number', 'N/A')}\n"
                    f"Description: {str(topic.get('tech_abstract', 'N/A'))[:300]}\n"
                    f"Link: https://www.sbir.gov/node/{topic.get('nid', '')}\n"
                )
        except requests.exceptions.Timeout:
            api_errors.append(f"Timeout on keyword '{keyword}'")
        except Exception as e:
            api_errors.append(f"Error on keyword '{keyword}': {str(e)}")

    if api_errors:
        unique_errors = list(dict.fromkeys(api_errors))
        print(f"SBIR API issues: {'; '.join(unique_errors)}")

    seen = set()
    unique_results = []
    for r in results:
        if r not in seen:
            seen.add(r)
            unique_results.append(r)

    if unique_results:
        return "\n".join(unique_results)
    elif api_errors:
        return f"SBIR.gov API unavailable ({unique_errors[0]}). Check https://www.sbir.gov/api for status."
    else:
        return "No open SBIR topics found matching search keywords."


def search_grants_gov(keywords):
    print(f"\nSearching Grants.gov for open opportunities...")

    all_results = []
    seen_ids = set()

    agencies = ["DOE", "DOD", "NASA"]

    for agency in agencies:
        url = "https://api.grants.gov/v1/api/search2"
        payload = {
            "keyword": " ".join(keywords[:3]),
            "oppStatuses": "posted|forecasted",
            "agencies": agency,
            "rows": 10,
            "sortBy": "openDate|desc",
        }
        try:
            response = requests.post(
                url, json=payload, headers={"User-Agent": "Mozilla/5.0"}, timeout=30
            )
            data = response.json()
            opportunities = data.get("data", {}).get("oppHits", [])
            for opp in opportunities:
                opp_id = opp.get("id")
                if opp_id not in seen_ids:
                    seen_ids.add(opp_id)
                    all_results.append(opp)
        except Exception as e:
            print(f"Error searching Grants.gov for {agency}: {str(e)}")

    if not all_results:
        return "No results found on Grants.gov."

    results = []
    for opp in all_results:
        results.append(
            f"Title: {opp.get('title', 'N/A')}\n"
            f"Agency: {opp.get('agencyName', 'N/A')}\n"
            f"Status: {opp.get('oppStatus', 'N/A')}\n"
            f"Open Date: {opp.get('openDate', 'N/A')}\n"
            f"Close Date: {opp.get('closeDate', 'N/A')}\n"
            f"Award Ceiling: ${opp.get('awardCeiling', 'N/A')}\n"
            f"Link: https://grants.gov/search-results-detail/{opp.get('id', '')}\n"
        )

    return "\n".join(results)


def score_opportunity(opp):
    title = opp.get("title", "").lower()
    keyword_matches = [kw for kw in KEYWORDS if kw.lower() in title]
    return len(keyword_matches)


def format_opportunities(opportunities):
    if not opportunities:
        return "No results found."
    results = []
    for opp in opportunities:
        score = score_opportunity(opp)
        match_label = "🎯 KEYWORD + NAICS MATCH" if score > 0 else "NAICS match only"
        results.append(
            f"[{match_label}]\n"
            f"Title: {opp.get('title', 'N/A')}\n"
            f"Agency: {opp.get('fullParentPathName', 'N/A')}\n"
            f"Type: {opp.get('type', 'N/A')}\n"
            f"Deadline: {opp.get('responseDeadLine', 'N/A')}\n"
            f"NAICS: {opp.get('naicsCode', 'N/A')}\n"
            f"Set-Aside: {opp.get('typeOfSetAsideDescription', 'N/A')}\n"
            f"Link: {opp.get('uiLink', 'N/A')}\n"
        )
    return "\n".join(results)


def send_email_report(report_text, sheet_url):
    sender = os.environ.get("GMAIL_SENDER")
    recipient = os.environ.get("GMAIL_RECIPIENT")
    password = os.environ.get("GMAIL_APP_PASSWORD")

    today = datetime.today().strftime("%B %d, %Y")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Branch Technology Solicitation Report — {today}"
    msg["From"] = sender
    msg["To"] = recipient

    # Convert markdown to HTML
    report_html = md.markdown(report_text, extensions=["tables"])

    html = f"""
<html>
<head>
<style>
    body {{
        font-family: 'Helvetica Neue', Arial, sans-serif;
        font-size: 15px;
        color: #1a1a1a;
        background-color: #f4f4f4;
        margin: 0;
        padding: 0;
    }}
    .wrapper {{
        max-width: 720px;
        margin: 30px auto;
        background-color: #ffffff;
        border-radius: 8px;
        overflow: hidden;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    }}
    .header {{
        background-color: #1a1a2e;
        color: #ffffff;
        padding: 28px 36px;
    }}
    .header h1 {{
        margin: 0;
        font-size: 22px;
        font-weight: 600;
        letter-spacing: 0.3px;
    }}
    .header p {{
        margin: 6px 0 0;
        font-size: 13px;
        color: #aaaacc;
    }}
    .body {{
        padding: 32px 36px;
        line-height: 1.7;
    }}
    h2 {{
        font-size: 17px;
        color: #1a1a2e;
        border-bottom: 2px solid #e8e8f0;
        padding-bottom: 6px;
        margin-top: 28px;
    }}
    h3 {{
        font-size: 15px;
        color: #333366;
        margin-top: 20px;
    }}
    table {{
        width: 100%;
        border-collapse: collapse;
        margin: 16px 0;
        font-size: 14px;
    }}
    th {{
        background-color: #1a1a2e;
        color: #ffffff;
        padding: 10px 14px;
        text-align: left;
    }}
    td {{
        padding: 9px 14px;
        border-bottom: 1px solid #e8e8f0;
    }}
    tr:nth-child(even) td {{
        background-color: #f8f8fc;
    }}
    a {{
        color: #3333cc;
        text-decoration: none;
    }}
    a:hover {{
        text-decoration: underline;
    }}
    hr {{
        border: none;
        border-top: 1px solid #e8e8f0;
        margin: 24px 0;
    }}
    .footer {{
        background-color: #f8f8fc;
        padding: 18px 36px;
        font-size: 12px;
        color: #888888;
        border-top: 1px solid #e8e8f0;
    }}
    .footer a {{
        color: #3333cc;
    }}
</style>
</head>
<body>
    <div class="wrapper">
        <div class="header">
            <h1>Branch Technology Solicitation Report</h1>
            <p>Weekly Government Funding Intelligence — {today}</p>
        </div>
        <div class="body">
            {report_html}
        </div>
        <div class="footer">
            Full report logged at: <a href="{sheet_url}">{sheet_url}</a><br>
            Generated automatically by Branch Technology Solicitation Agent
        </div>
    </div>
</body>
</html>
"""

    plain_text = f"Branch Technology Solicitation Report — {today}\n\n{report_text}\n\nFull report: {sheet_url}"

    msg.attach(MIMEText(plain_text, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())
        print(f"Report emailed to {recipient}")
    except Exception as e:
        print(f"Email error: {str(e)}")


topic = """I'm looking for government funding solicitations that cater well to Branch Technology's offering of BranchRegenerate - a 3D printed, digital scan-to-print energy retrofit product for overcladding existing buildings for better insulation and therefore energy efficiency. I'm also interested generally in construction technology solicitations that might fit well with Branch's large-format additive prefabrication manufacturing process, Cellular Fabrication."""

print(f"\nSearching SAM.gov by NAICS codes: {', '.join(NAICS_CODES)}...")
opportunities = search_sam_by_naics(NAICS_CODES)

# Sort: keyword+NAICS matches first, NAICS-only second
opportunities.sort(key=score_opportunity, reverse=True)

overlap_count = sum(1 for opp in opportunities if score_opportunity(opp) > 0)
print(
    f"Found {len(opportunities)} opportunities ({overlap_count} with keyword overlap)"
)

sam_results = format_opportunities(opportunities)

print("\nAsking Claude to analyze the results...\n")

sbir_keywords = [
    "building envelope",
    "insulation",
    "additive manufacturing",
    "construction",
    "energy retrofit",
    "building modernization",
    "facility renovation",
    "energy conservation",
    "thermal envelope",
    "prefabricated construction",
    "modular building",
    "MILCON",
    "ESPC",
    "deep energy retrofit",
    "cladding",
    "facade",
]
sbir_results = search_sbir(sbir_keywords)
print(f"Found SBIR topics, analyzing...")
grants_results = search_grants_gov(
    [
        "building envelope",
        "energy retrofit",
        "insulation",
        "additive manufacturing",
        "building modernization",
        "energy conservation",
        "thermal envelope",
        "prefabricated construction",
        "facility renovation",
        "deep energy retrofit",
    ]
)
print(f"Grants.gov search complete.")

message = client.messages.create(
    model="claude-opus-4-8",
    max_tokens=2048,
    messages=[
        {
            "role": "user",
            "content": f"""You are a government contracting analyst preparing a weekly funding intelligence brief for Branch Technology, a small business based in Chattanooga, TN. Branch has two core offerings:
1. BranchRegenerate - a 3D-printed, scan-to-print energy retrofit system for overcladding existing buildings to improve insulation and energy efficiency
2. Cellular Fabrication - a large-format additive manufacturing process for prefabricated construction components

Branch works primarily with DOE, DoD, and NASA on R&D programs and is an experienced SBIR/STTR participant.

Today's date is {datetime.today().strftime("%B %d, %Y")}. Use this date in the report header. Do not use any other date.

Format your response as a clean, concise weekly brief with these sections only:
1. **This Week's Summary** - 2-3 sentences max on what was found
2. **Top Opportunities** - only include genuinely relevant ones, with agency, deadline, set-aside status, why it fits, and link
3. **Worth Monitoring** - brief list of lower-priority items worth a second look
4. **Recommended Actions** - 3-5 specific, actionable items for this week

Do not include a list of irrelevant opportunities. Do not repeat the company description back. No excessive headers or whitespace between sections.

Here are this week's search results:

SAM.gov (sorted by relevance, KEYWORD + NAICS MATCH results first):
{sam_results}

SBIR.gov open topics:
{sbir_results}

Grants.gov open opportunities:
{grants_results}""",
        }
    ],
)

import re

output = message.content[0].text
output = re.sub(r"[^\x00-\x7F]+", "", output)
print(output.encode("utf-8", errors="replace").decode("utf-8"))

creds = get_google_credentials()
sheet_url = (
    f"https://docs.google.com/spreadsheets/d/{os.environ.get('GOOGLE_SHEET_ID')}"
)
save_to_sheets(creds, output, len(opportunities), overlap_count)
send_email_report(output, sheet_url)
