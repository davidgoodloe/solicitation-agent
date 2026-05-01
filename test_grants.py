import urllib.request
import json

url = "https://api.grants.gov/v1/api/search2"

payload = json.dumps({
    "oppStatuses": "posted|forecasted",
    "keyword": "building envelope energy retrofit",
    "rows": 10
}).encode("utf-8")

request = urllib.request.Request(
    url,
    data=payload,
    headers={
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
)

try:
    with urllib.request.urlopen(request) as response:
        data = json.loads(response.read())
        opps = data.get("data", {}).get("oppHits", [])
        print(f"Total results: {data.get('data', {}).get('hitCount', 0)}")
        for opp in opps:
            print(f"Code: {opp.get('agencyCode')} | Title: {opp.get('title')[:70]}")
except urllib.error.HTTPError as e:
    print("Error:", e.code, e.read().decode())