"""
Update live stock prices in a Notion Investment Tracker database.

WHAT THIS DOES
---------------
For each ticker in TICKERS, this script:
  1. Fetches the current price and volume from Finnhub (free-tier API)
  2. Finds the matching row in your Notion database (matched by ticker name)
  3. Updates the "Current price" and "Volume" properties on that row

SETUP (one-time)
------------------
1. Get a free Finnhub API key: https://finnhub.io/register
2. Create a Notion internal integration: https://www.notion.so/my-integrations
   - Copy the "Internal Integration Secret"
3. Share your Investment Tracker database with that integration:
   - Open the database in Notion -> "..." menu (top right) -> Connections -> add your integration
4. Get your database ID:
   - Open the database as a full page in your browser
   - Copy the 32-character ID from the URL, e.g.
     https://www.notion.so/myworkspace/DATABASE_ID?v=...
5. Fill in the four values below (FINNHUB_API_KEY, NOTION_API_KEY, DATABASE_ID)
6. Make sure your Notion property names match PRICE_PROP / VOLUME_PROP / TICKER_PROP
   below (edit them if your actual property names differ).

RUNNING IT
-----------
Locally:      pip install requests
              python update_notion_prices.py

On a schedule (recommended): use GitHub Actions with a cron trigger, e.g.
  .github/workflows/update-prices.yml
    on:
      schedule:
        - cron: '*/15 * * * *'   # every 15 minutes
    jobs:
      update:
        runs-on: ubuntu-latest
        steps:
          - uses: actions/checkout@v4
          - uses: actions/setup-python@v5
            with:
              python-version: '3.11'
          - run: pip install requests
          - run: python update_notion_prices.py
            env:
              FINNHUB_API_KEY: ${{ secrets.FINNHUB_API_KEY }}
              NOTION_API_KEY: ${{ secrets.NOTION_API_KEY }}
              NOTION_DATABASE_ID: ${{ secrets.NOTION_DATABASE_ID }}

  (Store your keys as GitHub repo secrets instead of hardcoding them, then
   swap the constants below for os.environ.get(...) calls, as already set up.)
"""

import os
import time
import requests

# ---------------------------------------------------------------------------
# CONFIG — fill these in (or set as environment variables / GitHub secrets)
# ---------------------------------------------------------------------------
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "FINNHUB_API_KEY")
NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "NOTION_API_KEY")
DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "NOTION_DATABASE_ID")

# The tickers you want to track. For ETFs like XEQT (Canadian, TSX-listed),
# Finnhub needs the exchange suffix — use "XEQT.TO".
TICKERS = ["TSM", "NOW", "NVDA", "XEQT.TO", "META", "MSFT"]

# These must match your actual Notion property names exactly.
TICKER_PROP = "Ticker"          # the title property that holds e.g. "AAPL"
PRICE_PROP = "Current price"  # a Number property
VOLUME_PROP = "Volume"        # a Number property

NOTION_VERSION = "2022-06-28"
FINNHUB_BASE_URL = "https://finnhub.io/api/v1/quote"
NOTION_BASE_URL = "https://api.notion.com/v1"


def get_quote(symbol: str) -> dict:
    """Fetch current price and volume for one ticker from Finnhub."""
    resp = requests.get(
        FINNHUB_BASE_URL,
        params={"symbol": symbol, "token": FINNHUB_API_KEY},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    # Finnhub's /quote endpoint returns 'c' (current price).
    # Note: Finnhub's free tier does not return live volume via /quote for
    # every exchange — if "Volume" comes back as 0 or missing for a ticker,
    # you may need a different endpoint/provider for that symbol (e.g. Twelve
    # Data), or leave Volume as a manual/less-frequent update.
    return {
        "price": data.get("c"),
        "volume": data.get("v", None),
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
    for symbol in TICKERS:
        # Strip exchange suffix for matching the Notion row title
        display_ticker = symbol.replace(".TO", "")

        try:
            quote = get_quote(symbol)
            if quote["price"] is None:
                print(f"[skip] {symbol}: no price returned")
                continue

            page_id = find_notion_page(display_ticker)
            if page_id is None:
                print(f"[skip] {display_ticker}: no matching Notion row found "
                      f"(add a row named exactly '{display_ticker}' first)")
                continue

            update_notion_page(page_id, quote["price"], quote["volume"])
            print(f"[ok] {display_ticker}: price={quote['price']} volume={quote['volume']}")

        except requests.HTTPError as e:
            print(f"[error] {symbol}: {e}")

        # Finnhub free tier allows 60 calls/min — small delay keeps you safe
        time.sleep(1.1)


if __name__ == "__main__":
    main()
