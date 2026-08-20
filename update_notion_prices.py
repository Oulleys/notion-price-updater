"""
Update live stock prices in a Notion Investment Tracker database.
 
DATA SOURCES (hybrid approach)
---------------------------------
- US-listed stocks -> Twelve Data, using ONE BATCHED request for all symbols
  at once (comma-separated), instead of one request per ticker. This is
  critical once you're tracking many stocks: Twelve Data's free tier allows
  8 requests/minute and 800 requests/day. One request per ticker per run
  quickly blows through both limits as your list grows. Batching keeps this
  at 1 request per run no matter how many US tickers you add.
- TSX-listed ETFs (XEQT, XDIV, etc.) -> Yahoo Finance's free public endpoint
  (no key needed, one request per TSX ticker — fine since Yahoo has no
  documented tight rate limit for casual use).
 
ADDING A NEW STOCK
--------------------
US-listed: just add its symbol to TWELVEDATA_TICKERS below, e.g.:
    {"symbol": "TSM", "notion_name": "TSM"}
TSX-listed (or other non-US exchange Twelve Data won't serve for free):
    add to YAHOO_TICKERS, e.g. {"symbol": "XDIV.TO", "notion_name": "XDIV"}
 
Either way, ALSO add a matching row in your Notion Portfolio database with
the exact same title as "notion_name" — the script only updates rows that
already exist, it doesn't create new ones.
 
SETUP
------
Same three GitHub secrets as before: TWELVE_DATA_API_KEY, NOTION_API_KEY,
NOTION_DATABASE_ID. Nothing new needed for this version.
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
 
# US-listed stocks — all fetched in a single batched Twelve Data call.
TWELVEDATA_TICKERS = [
    {"symbol": "AAPL", "notion_name": "AAPL"},
    {"symbol": "NOW", "notion_name": "NOW"},
    {"symbol": "NVDA", "notion_name": "NVDA"},
    {"symbol": "TSM", "notion_name": "TSM"},
    {"symbol": "META", "notion_name": "META"},
    {"symbol": "MSFT", "notion_name": "MSFT"},
    {"symbol": "BE", "notion_name": "BE"},
    {"symbol": "NBIS", "notion_name": "NBIS"},
    {"symbol": "AAOI", "notion_name": "AAOI"},
    {"symbol": "GOOG", "notion_name": "GOOG"},
]
 
# Non-US tickers — fetched individually from Yahoo (one request each).
YAHOO_TICKERS = [
    {"symbol": "XEQT.TO", "notion_name": "XEQT"},
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
 
 
def get_quotes_twelvedata_batch(tickers: list[dict]) -> dict:
    """Fetch ALL US tickers in a single Twelve Data request. Returns a dict
    keyed by symbol, e.g. {"AAPL": {"price": ..., "volume": ...}, ...}."""
    symbols = ",".join(t["symbol"] for t in tickers)
    params = {"symbol": symbols, "apikey": TWELVE_DATA_API_KEY}
 
    resp = requests.get(TWELVE_DATA_BASE_URL, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
 
    results = {}
 
    # Twelve Data returns a flat object (not keyed by symbol) when you only
    # pass ONE symbol, but a dict-of-dicts keyed by symbol for multiple.
    if len(tickers) == 1:
        symbol = tickers[0]["symbol"]
        if data.get("status") == "error":
            results[symbol] = {"error": data.get("message", "Unknown error")}
        else:
            results[symbol] = {
                "price": float(data["close"]) if data.get("close") is not None else None,
                "volume": float(data["volume"]) if data.get("volume") is not None else None,
            }
        return results
 
    for symbol, entry in data.items():
        if isinstance(entry, dict) and entry.get("status") == "error":
            results[symbol] = {"error": entry.get("message", "Unknown error")}
        elif isinstance(entry, dict):
            price = entry.get("close")
            volume = entry.get("volume")
            results[symbol] = {
                "price": float(price) if price is not None else None,
                "volume": float(volume) if volume is not None else None,
            }
    return results
 
 
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
 
 
def apply_quote_to_notion(display_ticker: str, quote: dict) -> None:
    if quote.get("error"):
        print(f"[error] {display_ticker}: {quote['error']}")
        return
    if quote.get("price") is None:
        print(f"[skip] {display_ticker}: no price returned")
        return
 
    page_id = find_notion_page(display_ticker)
    if page_id is None:
        print(f"[skip] {display_ticker}: no matching Notion row found "
              f"(add a row named exactly '{display_ticker}' first)")
        return
 
    update_notion_page(page_id, quote["price"], quote.get("volume"))
    print(f"[ok] {display_ticker}: price={quote['price']} volume={quote.get('volume')}")
 
 
def main() -> None:
    # --- One batched call for all US tickers ---
    if TWELVEDATA_TICKERS:
        try:
            batch_results = get_quotes_twelvedata_batch(TWELVEDATA_TICKERS)
        except requests.HTTPError as e:
            print(f"[error] Twelve Data batch request failed: {e}")
            batch_results = {}
 
        for t in TWELVEDATA_TICKERS:
            quote = batch_results.get(t["symbol"], {"error": "not found in batch response"})
            apply_quote_to_notion(t["notion_name"], quote)
 
    # --- Individual Yahoo calls for non-US tickers ---
    for t in YAHOO_TICKERS:
        try:
            quote = get_quote_yahoo(t["symbol"])
        except (requests.HTTPError, ValueError) as e:
            quote = {"error": str(e)}
        apply_quote_to_notion(t["notion_name"], quote)
        time.sleep(2)  # light courtesy delay between Yahoo calls
 
 
if __name__ == "__main__":
    main()
 
