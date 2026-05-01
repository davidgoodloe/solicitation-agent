import urllib.request
import json
from datetime import datetime, timedelta

api_key = "SAM-3c4666d7-9d24-4d8d-b40f-7752e0e25206"
today = datetime.today().strftime("%m/%d/%Y")
ninety_days_ago = (datetime.today() - timedelta(days=90)).strftime("%m/%d/%Y")

url = f"https://api.sam.gov/prod/opportunities/v2/search?api_key={api_key}&limit=3&postedFrom={ninety_days_ago}&postedTo={today}"

print("Calling URL:", url)

try:
    with urllib.request.urlopen(url) as response:
        raw = response.read().decode()
        print(raw[:2000])
except urllib.error.HTTPError as e:
    print("Error code:", e.code)
    print("Error message:", e.read().decode())