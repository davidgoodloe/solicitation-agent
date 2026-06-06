import urllib.request
import json
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
api_key = os.environ.get("SAM_API_KEY")
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