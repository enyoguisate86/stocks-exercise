from __future__ import annotations

from .models import Security

TICKER_HINTS = """\
How to enter a ticker or company:
  - US stocks: plain symbol, e.g. MSFT, AAPL, NVDA
  - Share classes use a dash: BRK-B, BF-B
  - Other exchanges add a suffix: 7203.T (Tokyo), ORB.L (London), SAP.DE (Xetra), RY.TO (Toronto)
  - Indices start with ^ (^GSPC) and crypto uses -USD (BTC-USD)
  - Company names work too (e.g. "Microsoft"); I search Yahoo Finance and ask you to pick when several match
  - Research one ticker per question and say what you want: quote, performance last 3 months, profile, or news"""

PROMPT = "you (ticker like MSFT, BRK-B, 7203.T or a company name + quote/performance/profile/news; 'exit' quits)> "

EXAMPLES = (
    "quote MSFT",
    "performance of AAPL last 3 months",
    "show the profile for Microsoft",
    "news for NVDA",
    "show BRK-B performance from 2025-01-02 to 2025-06-30",
)


def format_suggestions(matches: list[Security]) -> str:
    return ", ".join(f"{item.ticker} ({item.exchange}) - {item.company_name}" for item in matches)
