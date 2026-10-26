# Stock Research Assistant

A small stock research app built with Python, LangGraph, Pydantic, and a CLI. By default it pulls market data, company profiles, and news from Yahoo Finance through the [`yfinance`](https://ranaroussi.github.io/yfinance/) library. A fictional offline provider is available for tests and demos. It does not analyze portfolios, make personalized investment recommendations, or execute trades.

> yfinance is an unofficial wrapper around Yahoo's public endpoints. Quotes can be delayed (~15 min), data can be incomplete, and use is subject to Yahoo's terms. Output is labelled `delayed` / `historical` accordingly.

## Requirements

Python 3.11+ with the dependencies in the repository-level `requirements.txt` (`langgraph`, `pydantic`, `python-dotenv`, `yfinance`, and optionally `langchain-openai` / `langchain-groq`). Network access is needed for live data.

From the repository root, run a question:

```powershell
c:/python312/python.exe -m StocksExercise "quote MSFT"
```

Or start the interactive CLI (prints the ticker hints below):

```powershell
c:/python312/python.exe -m StocksExercise
```

## Web UI (Streamlit)

```powershell
c:/python312/python.exe -m streamlit run StocksExercise/ui_app.py
```

The sidebar has a lookup form (ticker or company, tasks, history range, save report, data-source toggle) and there is a chat box for free-text questions. History requests show a price chart, and when a company name matches several listings (e.g. Toyota) you can click the listing you mean.

## Entering a ticker

| You want | Type | Example |
| --- | --- | --- |
| US stock | plain symbol | `MSFT`, `AAPL`, `NVDA` |
| Share class | dash | `BRK-B`, `BF-B` |
| Other exchange | symbol + suffix | `7203.T` (Tokyo), `ORB.L` (London), `SAP.DE` (Xetra), `RY.TO` (Toronto) |
| Index | `^` prefix | `^GSPC` |
| Crypto | `-USD` suffix | `BTC-USD` |
| By name | company name | `Microsoft`, `Toyota` |

- Names are searched on Yahoo Finance; if several listings match you are asked to reply with the exact ticker.
- If nothing matches you get "Did you mean…" suggestions (when Yahoo's search has any) plus these hints.
- Research one ticker per question and say what you want: `quote`, `performance last 3 months` (or an explicit `from YYYY-MM-DD to YYYY-MM-DD`), `profile`, or `news`.

The same text lives in `stockresearch/hints.py` and is shown in `--help`, the interactive banner, and clarification messages.

Examples:

- `quote MSFT`
- `performance of AAPL last 3 months`
- `show BRK-B performance from 2025-01-02 to 2025-06-30`
- `show the profile for Microsoft`
- `news for NVDA`
- `save report: show AAPL performance last 1 month`
- `what should I buy?` (returns the informational-use boundary)

## Data providers

`STOCK_PROVIDER` selects the source (set it in `.env`):

- `yfinance` (default): live Yahoo Finance data via `YFinanceProvider`.
- `mock`: deterministic fictional fixtures (ACME, NOVA, and two "Orbit Example Holdings" listings ORB / ORB.L to demonstrate ambiguity handling). Output is labelled simulated. Example: `quote ACME`, `show ACME performance from 2025-01-02 to 2025-01-06`.

Historical returns use unadjusted daily closes, so they exclude dividends.

## Optional LLM

The app runs without credentials using deterministic intent parsing and factual response formatting. To enable an LLM, copy `.env.example` to `.env`, choose `openai` or `groq` for `STOCK_LLM_PROVIDER`, and set the corresponding API key. Never commit `.env` or real secrets. If the model is unavailable, the app falls back to offline behavior.

The LLM may assist with intent extraction and phrasing, but the provider adapter supplies the source data. The response is constrained to those retrieved facts and must preserve their timestamps, provenance, and freshness labels.

## Graph and providers

`stockresearch/graph.py` builds an explicit compiled StateGraph. `stockresearch/models.py` defines validated data models and shared state types. `stockresearch/providers.py` contains the provider protocol, `YFinanceProvider`, the fictional `MockMarketDataProvider`, and `create_provider()`. To integrate another licensed provider, implement the `MarketDataProvider` protocol (optionally a `suggest(query)` method for "Did you mean…"). Mock news URLs use the reserved `.invalid` domain intentionally.

A report request saves Markdown under `StocksExercise/reports/`. Notification delivery is deliberately disabled by default; requests state that no notification was sent. A future notification integration should be an explicit adapter, opt-in, and must not prevent the chat response on failure.

## Tests

Tests run offline (mock provider and a fake yfinance module). From the repository root:

```powershell
c:/python312/python.exe -m unittest discover -s StocksExercise/tests -t . -v
```
