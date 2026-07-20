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
import html
import json
import os
import re
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


def parse_date_safe(value, fmt=None):
    """Best-effort date parsing that never raises — returns None on any failure
    so a single unexpected date format can't take down the whole run."""
    if not value:
        return None
    try:
        if fmt:
            return datetime.strptime(value, fmt)
        return datetime.fromisoformat(value)
    except Exception:
        return None


def is_past_due(dt):
    if dt is None:
        return False
    return dt.date() < datetime.today().date()


def fmt_date(dt):
    return dt.strftime("%B %d, %Y") if dt else None


def sam_deadline(opp):
    return parse_date_safe(opp.get("responseDeadLine"))


def fetch_sam_description(opp, max_chars=600):
    """Best-effort fetch of the full solicitation text so Claude can judge real
    application (not just shared process vocabulary). Never raises — returns
    None on any failure, so callers just fall back to no description."""
    desc_url = opp.get("description")
    if not desc_url:
        return None
    try:
        r = requests.get(f"{desc_url}&api_key={sam_api_key}", timeout=15)
        r.raise_for_status()
        raw = r.json().get("description", "")
        if not raw:
            return None
        text = re.sub(r"<[^>]+>", " ", raw)
        text = re.sub(r"&[a-zA-Z#0-9]+;|\s+", " ", text).strip()
        return text[:max_chars] or None
    except Exception:
        return None


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

    try:
        all_opportunities = [
            opp for opp in all_opportunities if not is_past_due(sam_deadline(opp))
        ]
    except Exception:
        pass

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


def dsip_deadline(topic):
    raw = topic.get("topicEndDate")
    if not raw:
        return None
    try:
        return datetime.fromtimestamp(raw / 1000)
    except Exception:
        return None


def search_dsip(keywords):
    print(f"\nSearching DSIP (DoD SBIR/STTR Innovation Portal) for open topics...")
    url = "https://www.dodsbirsttr.mil/topics/api/public/topics/search"

    # The portal's keyword search ranks against its ~30k-topic historical archive,
    # not the small set of currently open topics — so pull the open set directly
    # (it's small, typically a few dozen) and score it locally instead.
    try:
        response = requests.get(
            url,
            params={"searchParam": json.dumps({}), "size": 200},
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        return f"DSIP unavailable ({str(e)}). Check https://www.dodsbirsttr.mil/ for status."

    open_topics = [
        t for t in data.get("data", []) if t.get("topicStatus") in ("Open", "Pre-Release")
    ]

    try:
        open_topics = [t for t in open_topics if not is_past_due(dsip_deadline(t))]
    except Exception:
        pass

    def keyword_matches(topic):
        title = topic.get("topicTitle", "").lower()
        return [kw for kw in keywords if kw.lower() in title]

    relevant = [t for t in open_topics if keyword_matches(t)]
    relevant.sort(key=lambda t: len(keyword_matches(t)), reverse=True)

    if not open_topics:
        return "No open or pre-release DSIP topics currently posted."

    shown = relevant if relevant else open_topics
    note = "" if relevant else " (none matched search keywords — showing all currently open topics)"

    results = [
        f"Currently {len(open_topics)} open/pre-release DSIP topics{note}:\n"
    ]
    for topic in shown:
        code = topic.get("topicCode")
        due_str = fmt_date(dsip_deadline(topic)) or "Not listed (verify on portal)"
        results.append(
            f"Title: {topic.get('topicTitle', 'N/A')}\n"
            f"Status: {topic.get('topicStatus', 'N/A')}\n"
            f"Component: {topic.get('component', 'N/A')}\n"
            f"Topic #: {code or 'N/A'}\n"
            f"Due Date: {due_str}\n"
            f"Solicitation: {topic.get('solicitationTitle', 'N/A')}\n"
            f"Link: https://www.dodsbirsttr.mil/topics-app/ (search for topic # {code})\n"
        )

    return "\n".join(results)


def grants_deadline(raw):
    return parse_date_safe(raw, "%m/%d/%Y")


# Grants.gov's applicantEligibilityDesc is a comma-separated list drawn from a
# fixed, official category taxonomy — these substrings are the categories a
# for-profit small business like Branch actually falls under.
BRANCH_ELIGIBLE_CATEGORIES = (
    "small business",
    "for profit organizations",
    "unrestricted",
    "other (see text field",
)


def fetch_grants_eligibility(opp_id):
    """Best-effort fetch of Grants.gov's structured eligible-applicants field.
    Never raises — returns None on any failure, so the caller keeps the item
    rather than guessing at eligibility it can't confirm."""
    try:
        r = requests.post(
            "https://api.grants.gov/v1/api/fetchOpportunity",
            json={"opportunityId": int(opp_id)},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("data", {}).get("synopsis", {}).get("applicantEligibilityDesc")
    except Exception:
        return None


def branch_ineligible(eligibility_desc):
    """Conservative by design: only excludes when eligibility text is present
    AND names none of Branch's own applicant categories. Missing/unparseable/
    ambiguous text is left alone (kept) rather than risk hiding a real fit."""
    if not eligibility_desc:
        return False
    text = eligibility_desc.lower()
    return not any(cat in text for cat in BRANCH_ELIGIBLE_CATEGORIES)


def search_grants_gov(keywords):
    print(f"\nSearching Grants.gov for open opportunities...")

    all_results = []
    seen_ids = set()

    url = "https://api.grants.gov/v1/api/search2"

    for keyword in keywords:
        payload = {
            "keyword": keyword,
            "oppStatuses": "posted|forecasted",
            "rows": 10,
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
            print(f"Error searching Grants.gov for '{keyword}': {str(e)}")

    try:
        all_results = [
            opp for opp in all_results if not is_past_due(grants_deadline(opp.get("closeDate")))
        ]
    except Exception:
        pass

    # Fetch eligibility only for the (already date-filtered) survivors — one
    # extra call each, but this is a weekly batch job so the added time is fine.
    kept_results = []
    for opp in all_results:
        eligibility = fetch_grants_eligibility(opp.get("id"))
        if branch_ineligible(eligibility):
            continue
        opp["_eligibility"] = eligibility
        kept_results.append(opp)
    all_results = kept_results

    if not all_results:
        return "No results found on Grants.gov."

    results = []
    for opp in all_results:
        title = html.unescape(opp.get("title", "N/A"))
        due_str = fmt_date(grants_deadline(opp.get("closeDate"))) or "Not listed (rolling — verify on portal)"
        eligibility_line = (
            f"Eligible Applicants: {opp['_eligibility']}\n" if opp.get("_eligibility") else ""
        )
        results.append(
            f"Title: {title}\n"
            f"Agency: {opp.get('agency', 'N/A')} ({opp.get('agencyCode', 'N/A')})\n"
            f"Status: {opp.get('oppStatus', 'N/A')}\n"
            f"Open Date: {opp.get('openDate', 'N/A')}\n"
            f"Due Date: {due_str}\n"
            f"{eligibility_line}"
            f"Link: https://grants.gov/search-results-detail/{opp.get('id', '')}\n"
        )

    return "\n".join(results)


def hud_due_date(body):
    match = re.search(
        r"Application (?:Close|Due) Date:\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4})", body
    )
    if not match:
        return None
    return parse_date_safe(match.group(1).replace(",", ""), "%B %d %Y")


def search_hud():
    print(f"\nSearching HUD PD&R Funding Opportunities page...")
    url = "https://www.huduser.gov/portal/ota/funding-opportunities.html"

    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=30,
        )
        response.raise_for_status()
        html = response.text
    except Exception as e:
        return f"HUD PD&R Funding Opportunities page unavailable ({str(e)}). Check {url}."

    anchor = html.find("Welcome to the Funding Opportunities page")
    if anchor == -1:
        return "Could not locate the funding opportunities listing on the HUD PD&R page."
    section = html[anchor : anchor + 30000]

    # Each opportunity sits in its own <h2-4>...</h2-4> heading followed by body
    # text up to the next heading — split on heading boundaries to pair them up.
    parts = re.split(r"(<h[2-4][^>]*>.*?</h[2-4]>)", section, flags=re.S)

    def clean(html_fragment):
        text = re.sub(r"<[^>]+>", " ", html_fragment)
        text = re.sub(r"&[a-zA-Z#0-9]+;|\s+", " ", text).strip()
        return text

    results = []
    for i in range(1, len(parts) - 1, 2):
        title = clean(parts[i])
        body = clean(parts[i + 1])
        body = re.sub(r"^Funding Opportunity Title:.*?--> ?", "", body)

        if not title or title == "Quick Links" or len(body) < 50:
            continue

        try:
            due_dt = hud_due_date(body)
        except Exception:
            due_dt = None
        if is_past_due(due_dt):
            continue
        due_str = fmt_date(due_dt) or "Not listed (rolling — verify on portal)"

        results.append(
            f"Title: {title}\n"
            f"Agency: HUD — Office of Policy Development and Research (PD&R)\n"
            f"Due Date: {due_str}\n"
            f"Description: {body[:400]}\n"
            f"Link: {url}\n"
        )

    # This page is small and hand-curated by HUD PD&R, so pass everything through
    # rather than keyword-filtering — let the analyst judge relevance.
    if results:
        return "\n".join(results)
    else:
        return f"No funding opportunities currently listed on the HUD PD&R page ({url})."


# Column order for the 4 deadline cells that follow Program in each EERE table row
EERE_DEADLINE_STAGES = ["RFI Deadline", "LOI Deadline", "CP Deadline", "FA Deadline"]


def eere_parse_deadline(raw):
    if not raw:
        return None
    return parse_date_safe(raw.replace(" ET", "").strip(), "%m/%d/%Y %I:%M %p")


def eere_deadline_info(values):
    """Never raises — returns (exclude, next_deadline_str, all_stages_str),
    defaulting to 'keep it, no deadline info' if anything is unexpected."""
    try:
        stage_cells = values[4:8] if len(values) >= 8 else []
        stages = [
            (label, raw_val, eere_parse_deadline(raw_val))
            for label, raw_val in zip(EERE_DEADLINE_STAGES, stage_cells)
            if raw_val
        ]

        parsed_dts = [dt for _, _, dt in stages if dt]
        exclude = bool(parsed_dts) and is_past_due(max(parsed_dts))

        upcoming = sorted(
            [(dt, label) for label, _, dt in stages if dt and not is_past_due(dt)],
            key=lambda pair: pair[0],
        )
        next_deadline_str = (
            f"{upcoming[0][1]}: {fmt_date(upcoming[0][0])}" if upcoming else None
        )

        all_stages_str = (
            "; ".join(
                f"{label}: {fmt_date(dt) if dt else raw_val}" for label, raw_val, dt in stages
            )
            if stages
            else None
        )
        return exclude, next_deadline_str, all_stages_str
    except Exception:
        return False, None, None


def search_eere(keywords):
    print(f"\nSearching DOE EERE eXCHANGE for funding announcements...")
    url = "https://eere-exchange.energy.gov/Default.aspx"

    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            },
            timeout=30,
        )
        response.raise_for_status()
        page_html = response.text
    except Exception as e:
        return f"DOE EERE eXCHANGE unavailable ({str(e)}). Check {url}."

    rows = re.findall(
        r'<tr[^>]*class="[^"]*dxgvDataRow[^"]*"[^>]*>(.*?)</tr>', page_html, re.S
    )

    announcements = []
    for row in rows:
        cells = re.findall(r'<td[^>]*class="dxgv"[^>]*>(.*?)</td>', row, re.S)
        values = []
        for cell in cells:
            text = re.sub(r"<[^>]+>", " ", cell)
            text = re.sub(r"&[a-zA-Z#0-9]+;|\s+", " ", text).strip()
            values.append(text)
        if len(values) < 4:
            continue

        number, title, announcement_type, program_office = values[0], values[1], values[2], values[3]
        if announcement_type in ("Teaming Partner List", "Notice of Intent to Publish Announcement (NOI)"):
            continue

        exclude, next_deadline_str, all_stages_str = eere_deadline_info(values)
        if exclude:
            continue

        foa_id_match = re.search(r"#FoaId([0-9a-fA-F-]+)", row)
        link = (
            f"https://eere-exchange.energy.gov/Default.aspx?foaId={foa_id_match.group(1)}"
            if foa_id_match
            else url
        )

        announcements.append(
            {
                "number": number,
                "title": title,
                "type": announcement_type,
                "program_office": program_office,
                "link": link,
                "next_deadline": next_deadline_str,
                "all_deadlines": all_stages_str,
            }
        )

    def keyword_matches(announcement):
        haystack = f"{announcement['title']} {announcement['program_office']}".lower()
        return [kw for kw in keywords if kw.lower() in haystack]

    relevant = [a for a in announcements if keyword_matches(a)]
    relevant.sort(key=lambda a: len(keyword_matches(a)), reverse=True)

    if not announcements:
        return f"Could not parse any announcements from DOE EERE eXCHANGE ({url})."
    if not relevant:
        return f"No keyword matches among the {len(announcements)} current DOE EERE eXCHANGE announcements."

    results = []
    for a in relevant:
        due_line = a["next_deadline"] or "Not listed (verify on portal)"
        stages_line = (
            f"\nAll Stage Deadlines: {a['all_deadlines']}" if a["all_deadlines"] else ""
        )
        results.append(
            f"Title: {a['title']}\n"
            f"Type: {a['type']}\n"
            f"Program Office: {a['program_office']}\n"
            f"Announcement #: {a['number']}\n"
            f"Next Deadline (may disqualify if missed): {due_line}{stages_line}\n"
            f"Link: {a['link']}\n"
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
        due_str = fmt_date(sam_deadline(opp)) or "Not listed (verify on portal)"

        # Only worth the extra fetch for the small subset that already scored
        # a keyword+NAICS hit — Claude needs real content to judge these fairly.
        description_line = ""
        if score > 0:
            desc = fetch_sam_description(opp)
            if desc:
                description_line = f"Description: {desc}\n"

        results.append(
            f"[{match_label}]\n"
            f"Title: {opp.get('title', 'N/A')}\n"
            f"Agency: {opp.get('fullParentPathName', 'N/A')}\n"
            f"Type: {opp.get('type', 'N/A')}\n"
            f"Due Date: {due_str}\n"
            f"NAICS: {opp.get('naicsCode', 'N/A')}\n"
            f"Set-Aside: {opp.get('typeOfSetAsideDescription', 'N/A')}\n"
            f"{description_line}"
            f"Link: {opp.get('uiLink', 'N/A')}\n"
        )
    return "\n".join(results)


def send_email_report(report_text, sheet_url):
    sender = os.environ.get("GMAIL_SENDER")
    recipients = [r.strip() for r in os.environ.get("GMAIL_RECIPIENT", "").split(",") if r.strip()]
    password = os.environ.get("GMAIL_APP_PASSWORD")

    today = datetime.today().strftime("%B %d, %Y")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Branch Technology Solicitation Report — {today}"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)

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
            server.sendmail(sender, recipients, msg.as_string())
        print(f"Report emailed to {', '.join(recipients)}")
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
dsip_results = search_dsip(sbir_keywords)
print(f"DSIP search complete.")
hud_results = search_hud()
print(f"HUD PD&R search complete.")
eere_results = search_eere(KEYWORDS)
print(f"DOE EERE eXCHANGE search complete.")
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
2. **Top Opportunities** - only include genuinely relevant ones, with agency, due date, set-aside status, why it fits, and link
3. **Worth Monitoring** - brief list of lower-priority items worth a second look
4. **Recommended Actions** - 3-5 specific, actionable items for this week

Every opportunity you list under Top Opportunities or Worth Monitoring must state its due date exactly as given in the search results below (or "rolling / not listed" if that's how it's labeled) — do not omit it, and do not guess one. The results below already exclude anything already past its due date, so nothing further needs to be filtered on that basis.

When judging fit, require the opportunity's actual described application to genuinely involve buildings, construction, or energy-retrofit/envelope work. Sharing a process term like "additive manufacturing" or "3D print" with an unrelated end use (e.g., tooling, fixtures, currency, aerospace parts, medical devices) is not sufficient on its own — name the real described application in your "why it fits" reasoning, not just the shared process term.

Where a result includes an "Eligible Applicants" line, take it at face value: if it does not plausibly include a for-profit small business like Branch, exclude that opportunity entirely rather than listing it with a caveat.

Do not include a list of irrelevant opportunities. Do not repeat the company description back. No excessive headers or whitespace between sections.

Here are this week's search results:

SAM.gov (sorted by relevance, KEYWORD + NAICS MATCH results first):
{sam_results}

SBIR.gov open topics:
{sbir_results}

DSIP (DoD SBIR/STTR Innovation Portal) open topics:
{dsip_results}

HUD PD&R Funding Opportunities:
{hud_results}

DOE EERE eXCHANGE announcements:
{eere_results}

Grants.gov open opportunities:
{grants_results}""",
        }
    ],
)

output = message.content[0].text
output = re.sub(r"[^\x00-\x7F]+", "", output)
print(output.encode("utf-8", errors="replace").decode("utf-8"))

sheet_url = (
    f"https://docs.google.com/spreadsheets/d/{os.environ.get('GOOGLE_SHEET_ID')}"
)
try:
    creds = get_google_credentials()
    save_to_sheets(creds, output, len(opportunities), overlap_count)
except Exception as e:
    print(f"Google Sheets archiving failed: {e}")
    output = (
        f"**Warning: Google Sheets archiving failed this run ({e}). "
        f"This report was not saved to the archive — check token.json / credentials.**\n\n{output}"
    )

send_email_report(output, sheet_url)
