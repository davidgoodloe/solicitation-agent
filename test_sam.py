import requests
import socket
import json
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

_orig_getaddrinfo = socket.getaddrinfo
def _ipv4_only(*args, **kwargs):
    return [r for r in _orig_getaddrinfo(*args, **kwargs) if r[0] == socket.AF_INET]
socket.getaddrinfo = _ipv4_only

api_key = os.environ.get("SAM_API_KEY")
today = datetime.today().strftime("%m/%d/%Y")
ninety_days_ago = (datetime.today() - timedelta(days=90)).strftime("%m/%d/%Y")

url = f"https://api.sam.gov/opportunities/v2/search?api_key={api_key}&limit=3&postedFrom={ninety_days_ago}&postedTo={today}"

print("Calling URL:", url)

try:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    print(response.text[:2000])
except requests.HTTPError as e:
    print("Error code:", e.response.status_code)
    print("Error message:", e.response.text)
except Exception as e:
    print("Error:", e)
