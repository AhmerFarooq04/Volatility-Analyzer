"""Manual probe of the retired Investing.com provider; not used by the app."""

import requests
import json

def fetch_earnings_data(date="2026-07-28"):
    url = "https://www.investing.com/earnings-calendar/Service/getCalendarFilteredData"
    hd = {
        "User-Agent": "Mozilla/5.0",
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "https://www.investing.com/earnings-calendar/",
    }
    pl = {
        "country[]": "5",
        "dateFrom": date,
        "dateTo": date,
        "currentTab": "custom",
        "limit_from": 0,
    }
    r = requests.post(url, headers=hd, data=pl, timeout=20)
    print("Status:", r.status_code)
    try:
        data = json.loads(r.text)
        print("Data type:", type(data))
        print("Data preview:", str(data)[:100])
        print("data['data'] preview:", str(data['data'])[:100])
    except Exception as e:
        print("Exception:", e)
        print("Raw text preview:", r.text[:200])

if __name__ == "__main__":
    fetch_earnings_data()
