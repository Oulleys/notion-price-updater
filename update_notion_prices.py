"""
Update live stock prices in a Notion Investment Tracker database.
 
DATA SOURCES (hybrid approach)
---------------------------------
- US-listed stocks -> Twelve Data, batched in CHUNKS of up to 8 symbols per
  request. Twelve Data's free tier allows 8 credits/minute, and each symbol
  in a batched request consumes one credit simultaneously — so a single
  batch of more than 8 symbols instantly exceeds the limit and 429s, even
  though it's only "one request." Chunking into groups of 8 (with a short
  pause between chunks) keeps every chunk under the per-minute cap.
- TSX-listed ETFs (XEQT, XDIV, etc.) -> Yahoo Finance's free public endpoint.
 
ADDING A NEW STOCK
--------------------
US-listed: add its symbol to TWELVEDATA_TICKERS below. No limit on total
list size — the script automatically splits it into safe chunks of 8.
TSX-listed: add to YAHOO_TICKERS instead, e.g. {"symbol": "XDIV.TO", ...}.
 
Either way, ALSO add a matching row in your Notion Portfolio database with
the exact same title as "notion_name".
 
SETUP
------
Same three GitHub secrets as before: TWELVE_DATA_API_KEY, NOTION_API_KEY,
NOTION_DATABASE_ID.
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
 
YAHOO_TICKERS = [
    {"symbol": "XEQT.TO", "notion_name": "XEQT"},
]
 
# Max symbols per Twelve Data request — matches the free tier's 8 credits/minute cap.
TWELVEDATA_CHUNK_SIZE = 8
# Seconds to wait between chunks, so each lands in a fresh per-minute window.
TWELVEDATA_CHUNK_DELAY = 65
 
# Must match your Notion column names exactly.
TICKER_PROP = "Ticker"
PRICE_PROP = "Current price"
VOLUME_PROP = "Volume"
 
NOTION_VERSION = "2022-06-28"
TWELVE_DATA_BASE_URL = "https://api.twelvedata.com/quote"
YAHOO_BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
NOTION_BASE_URL = "https://api.notion.com/v1"
 
YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0"}
 
 
def chunked(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]
 
 
def get_quotes_twelvedata_batch(tickers: list[dict]) -> dict:
    """Fetch a batch (<= TWELVEDATA_CHUNK_SIZE) of tickers in one request."""
    symbols = ",".join(t["symbol"] for t in tickers)
    params = {"symbol": symbols, "apikey": TWELVE_DATA_API_KEY}
 
    resp = requests.get(TWELVE_DATA_BASE_URL, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
 
    results = {}
 
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
    # --- Twelve Data, chunked into groups of <= TWELVEDATA_CHUNK_SIZE ---
    chunks = list(chunked(TWELVEDATA_TICKERS, TWELVEDATA_CHUNK_SIZE))
    for i, chunk in enumerate(chunks):
        try:
            batch_results = get_quotes_twelvedata_batch(chunk)
        except requests.HTTPError as e:
            print(f"[error] Twelve Data chunk request failed: {e}")
            batch_results = {}
 
        for t in chunk:
            quote = batch_results.get(t["symbol"], {"error": "not found in batch response"})
            apply_quote_to_notion(t["notion_name"], quote)
 
        # Wait between chunks so each starts a fresh per-minute rate window —
        # skip the wait after the very last chunk.
        if i < len(chunks) - 1:
            time.sleep(TWELVEDATA_CHUNK_DELAY)
 
    # --- Yahoo, one request per non-US ticker ---
    for t in YAHOO_TICKERS:
        try:
            quote = get_quote_yahoo(t["symbol"])
        except (requests.HTTPError, ValueError) as e:
            quote = {"error": str(e)}
        apply_quote_to_notion(t["notion_name"], quote)
        time.sleep(2)
 
 
if __name__ == "__main__":
    main()
 
