"""
Update live stock prices in a Notion Investment Tracker database — using Twelve Data.
 
WHY TWELVE DATA INSTEAD OF FINNHUB
------------------------------------
Finnhub's free tier doesn't return volume on /quote, and doesn't support
TSX-listed tickers like XEQT.TO at all. Twelve Data's free tier supports
both real-time price AND volume, and covers the Toronto Stock Exchange,
so one provider now covers everything (XEQT, NOW, NVDA, etc.)
 
SETUP (one-time)
------------------
1. Get a free Twelve Data API key: https://twelvedata.com/pricing
   (free tier: 800 requests/day, 8 requests/minute — plenty for this)
2. You already have your Notion integration secret + database ID from before.
3. Add a new GitHub repo secret named TWELVE_DATA_API_KEY
   (Settings -> Secrets and variables -> Actions -> New repository secret)
   You can leave the old FINNHUB_API_KEY secret in place or delete it —
   it's no longer used by this version of the script.
4. Update the workflow file (.github/workflows/update-prices.yml) to pass
   TWELVE_DATA_API_KEY instead of FINNHUB_API_KEY — see the snippet at the
   bottom of this docstring.
 
TICKER FORMAT
--------------
Twelve Data uses "symbol" + "exchange" (or "mic_code") as separate params
rather than suffixes. Each entry in TICKERS below is a dict:
    {"symbol": "AAPL", "exchange": None, "notion_name": "AAPL"}
    {"symbol": "XEQT", "exchange": "TSX", "notion_name": "XEQT"}
"exchange" can be None for US-listed tickers (Twelve Data defaults to the
primary US listing). "notion_name" is what must match your Notion row's
title exactly.
 
UPDATED WORKFLOW FILE SNIPPET (replace the env: block in your .yml):
    - run: python update_notion_prices.py
      env:
        TWELVE_DATA_API_KEY: ${{ secrets.TWELVE_DATA_API_KEY }}
        NOTION_API_KEY: ${{ secrets.NOTION_API_KEY }}
        NOTION_DATABASE_ID: ${{ secrets.NOTION_DATABASE_ID }}
"""
 
import os
import time
import requests
 
# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "YOUR_TWELVE_DATA_KEY_HERE")
NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "NOTION_API_KEY")
DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "NOTION_DATABASE_ID")
 
# List of tickers to track. "exchange" is optional (None = US default).
TICKERS = [
    {"symbol": "AAPL", "exchange": None, "notion_name": "AAPL"},
    {"symbol": "NOW", "exchange": None, "notion_name": "NOW"},
    {"symbol": "NVDA", "exchange": None, "notion_name": "NVDA"},
    {"symbol": "XEQT", "exchange": "TSX", "notion_name": "XEQT"},
]
 
# Must match your Notion column names exactly.
TICKER_PROP = "Ticker"
PRICE_PROP = "Current price"
VOLUME_PROP = "Volume"
 
NOTION_VERSION = "2022-06-28"
TWELVE_DATA_BASE_URL = "https://api.twelvedata.com/quote"
NOTION_BASE_URL = "https://api.notion.com/v1"
 
 
def get_quote(symbol: str, exchange: str | None) -> dict:
    """Fetch current price and volume for one ticker from Twelve Data."""
    params = {"symbol": symbol, "apikey": TWELVE_DATA_API_KEY}
    if exchange:
        params["exchange"] = exchange
 
    resp = requests.get(TWELVE_DATA_BASE_URL, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
 
    if data.get("status") == "error":
        raise ValueError(data.get("message", "Unknown Twelve Data error"))
 
    price = data.get("close")
    volume = data.get("volume")
 
    return {
        "price": float(price) if price is not None else None,
        "volume": float(volume) if volume is not None else None,
    }
 
 
def find_notion_page(display_ticker: str) -> str | None:
    """Find the Notion database row whose title matches the ticker."""
    url = f"{NOTION_BASE_URL}/databases/{DATABASE_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    payload = {
        "filter": {
            "property": TICKER_PROP,
            "title": {"equals": display_ticker},
        }
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=10)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    return results[0]["id"] if results else None
 
 
def update_notion_page(page_id: str, price: float, volume: float | None) -> None:
    """Write the fetched price/volume into the matching Notion row."""
    url = f"{NOTION_BASE_URL}/pages/{page_id}"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    properties = {PRICE_PROP: {"number": price}}
    if volume is not None:
        properties[VOLUME_PROP] = {"number": volume}
 
    resp = requests.patch(url, headers=headers, json={"properties": properties}, timeout=10)
    resp.raise_for_status()
 
 
def main() -> None:
    for entry in TICKERS:
        symbol = entry["symbol"]
        exchange = entry.get("exchange")
        display_ticker = entry["notion_name"]
 
        try:
            quote = get_quote(symbol, exchange)
            if quote["price"] is None:
                print(f"[skip] {display_ticker}: no price returned")
                continue
 
            page_id = find_notion_page(display_ticker)
            if page_id is None:
                print(f"[skip] {display_ticker}: no matching Notion row found "
                      f"(add a row named exactly '{display_ticker}' first)")
                continue
 
            update_notion_page(page_id, quote["price"], quote["volume"])
            print(f"[ok] {display_ticker}: price={quote['price']} volume={quote['volume']}")
 
        except (requests.HTTPError, ValueError) as e:
            print(f"[error] {display_ticker}: {e}")
 
        # Twelve Data free tier: 8 requests/minute — space calls out safely
        time.sleep(8)
 
 
if __name__ == "__main__":
    main()
