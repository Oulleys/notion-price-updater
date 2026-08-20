"""
Update live stock prices in a Notion Investment Tracker database.
 
DATA SOURCES (hybrid approach)
---------------------------------
- US-listed stocks (AAPL, NOW, NVDA, etc.) -> Twelve Data (free tier, real-time,
  includes volume).
- TSX-listed ETFs (XEQT, XDIV, etc.)       -> Yahoo Finance's free public
  endpoint (no API key needed). Twelve Data's free tier only offers "trial"
  access to most international exchanges including the TSX, so it 404s on
  these — Yahoo's unofficial endpoint is the standard free workaround and
  covers Canadian tickers with the ".TO" suffix (e.g. "XEQT.TO").
 
  Note: this Yahoo endpoint is unofficial/undocumented. It's free, doesn't
  require a key, and is widely used for exactly this purpose, but Yahoo
  could change or restrict it without notice. Fine for a personal tracker;
  not something to build a commercial product on.
 
SETUP (one-time)
------------------
1. Twelve Data: https://twelvedata.com/pricing (free tier)
2. Notion integration secret + database ID (same as before)
3. No signup needed for Yahoo — it's used directly, no key required.
4. GitHub repo secrets needed: TWELVE_DATA_API_KEY, NOTION_API_KEY,
   NOTION_DATABASE_ID (same three as your last working version — nothing
   new to add for Yahoo).
 
TICKER FORMAT
--------------
Each entry in TICKERS is a dict with a "source" field:
    {"source": "twelvedata", "symbol": "AAPL", "exchange": None, "notion_name": "AAPL"}
    {"source": "yahoo", "symbol": "XEQT.TO", "notion_name": "XEQT"}
"notion_name" must match your Notion row's title exactly.
"""
 
import os
import time
import requests
 
# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "TWELVE_DATA_API_KEY")
NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "NOTION_API_KEY")
DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "NOTION_DATABASE_ID")
 
TICKERS = [
    {"source": "twelvedata", "symbol": "AAPL", "exchange": None, "notion_name": "AAPL"},
    {"source": "twelvedata", "symbol": "NOW", "exchange": None, "notion_name": "NOW"},
    {"source": "twelvedata", "symbol": "NVDA", "exchange": None, "notion_name": "NVDA"},
    {"source": "twelvedata", "symbol": "TSM", "exchange": None, "notion_name": "TSM"},
    {"source": "twelvedata", "symbol": "META", "exchange": None, "notion_name": "META"},
    {"source": "twelvedata", "symbol": "MSFT", "exchange": None, "notion_name": "MSFT"},
    {"source": "twelvedata", "symbol": "BE", "exchange": None, "notion_name": "BE"},
    {"source": "twelvedata", "symbol": "NBIS", "exchange": None, "notion_name": "NBIS"},
    {"source": "twelvedata", "symbol": "AAOI", "exchange": None, "notion_name": "AAOI"},
    {"source": "twelvedata", "symbol": "GOOG", "exchange": None, "notion_name": "GOOG"},
    {"source": "yahoo", "symbol": "XEQT.TO", "notion_name": "XEQT"},
]
 
# Must match your Notion column names exactly.
TICKER_PROP = "Ticker"
PRICE_PROP = "Current price"
VOLUME_PROP = "Volume"
 
NOTION_VERSION = "2022-06-28"
TWELVE_DATA_BASE_URL = "https://api.twelvedata.com/quote"
YAHOO_BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
NOTION_BASE_URL = "https://api.notion.com/v1"
 
YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0"}
 
 
def get_quote_twelvedata(symbol: str, exchange: str | None) -> dict:
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
 
 
def get_quote_yahoo(symbol: str) -> dict:
    url = f"{YAHOO_BASE_URL}/{symbol}"
    resp = requests.get(url, headers=YAHOO_HEADERS, params={"interval": "1d", "range": "1d"}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
 
    result = data.get("chart", {}).get("result")
    if not result:
        error = data.get("chart", {}).get("error")
        raise ValueError(error.get("description") if error else "No data returned")
 
    meta = result[0]["meta"]
    price = meta.get("regularMarketPrice")
 
    # Volume: take the most recent value from the day's volume series, if present
    volume = None
    try:
        volumes = result[0]["indicators"]["quote"][0]["volume"]
        volume = next((v for v in reversed(volumes) if v is not None), None)
    except (KeyError, IndexError):
        pass
 
    return {
        "price": float(price) if price is not None else None,
        "volume": float(volume) if volume is not None else None,
    }
 
 
def find_notion_page(display_ticker: str) -> str | None:
    url = f"{NOTION_BASE_URL}/databases/{DATABASE_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    payload = {"filter": {"property": TICKER_PROP, "title": {"equals": display_ticker}}}
    resp = requests.post(url, headers=headers, json=payload, timeout=10)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    return results[0]["id"] if results else None
 
 
def update_notion_page(page_id: str, price: float, volume: float | None) -> None:
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
        display_ticker = entry["notion_name"]
        source = entry["source"]
 
        try:
            if source == "twelvedata":
                quote = get_quote_twelvedata(entry["symbol"], entry.get("exchange"))
            elif source == "yahoo":
                quote = get_quote_yahoo(entry["symbol"])
            else:
                print(f"[error] {display_ticker}: unknown source '{source}'")
                continue
 
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
 
        # Twelve Data free tier: 8 requests/minute. Yahoo has no strict published
        # limit, but a small delay is polite and avoids accidental rate limiting.
        time.sleep(8)
 
 
if __name__ == "__main__":
    main()
 
