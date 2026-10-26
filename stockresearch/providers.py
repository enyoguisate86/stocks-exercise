from __future__ import annotations

import math
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol

from .models import CompanyProfile, Freshness, MarketObservation, NewsArticle, Security

YFINANCE_SOURCE = "yfinance (Yahoo Finance)"
_SYMBOL_LIKE = re.compile(r"^\^?[A-Za-z0-9]{1,6}(?:[.\-][A-Za-z0-9]{1,6})?$")
_SEARCHABLE_TYPES = {"EQUITY", "ETF", "MUTUALFUND", "INDEX", "CRYPTOCURRENCY", "CURRENCY"}


class MarketDataProvider(Protocol):
    def resolve(self, query: str) -> list[Security]: ...

    def get_quote(self, security: Security) -> MarketObservation | None: ...

    def get_history(
        self, security: Security, start_date: date | None, end_date: date | None
    ) -> list[MarketObservation]: ...

    def get_profile(self, security: Security) -> CompanyProfile | None: ...

    def get_news(self, security: Security) -> list[NewsArticle]: ...


class MockMarketDataProvider:
    """Deterministic, fictional data for local development; never live market data."""

    def __init__(self) -> None:
        self._securities = [
            Security(ticker="ACME", exchange="TEST", company_name="Acme Example Corporation", currency="USD"),
            Security(ticker="NOVA", exchange="TEST", company_name="Nova Example Systems", currency="USD"),
            Security(ticker="ORB", exchange="TEST", company_name="Orbit Example Holdings", currency="USD"),
            Security(ticker="ORB.L", exchange="TEST-L", company_name="Orbit Example Holdings", currency="GBP"),
        ]
        self._history = {
            "ACME": [(date(2025, 1, 2), 100.00), (date(2025, 1, 3), 102.50), (date(2025, 1, 6), 101.25)],
            "NOVA": [(date(2025, 1, 2), 50.00), (date(2025, 1, 3), 51.00), (date(2025, 1, 6), 52.25)],
            "ORB": [(date(2025, 1, 2), 80.00), (date(2025, 1, 3), 81.50), (date(2025, 1, 6), 79.25)],
            "ORB.L": [(date(2025, 1, 2), 62.00), (date(2025, 1, 3), 63.00), (date(2025, 1, 6), 62.50)],
        }
        self._profiles = {
            "ACME": ("Industrials", "Fictional manufacturer used for development and testing."),
            "NOVA": ("Technology", "Fictional software and systems company used for testing."),
            "ORB": ("Consumer", "Fictional consumer-products company used for testing."),
            "ORB.L": ("Consumer", "Fictional consumer-products company used for testing."),
        }
        self._news = {
            "ACME": [NewsArticle(ticker="ACME", title="Acme Example Corporation announces a fictional product update", publisher="Example News", published_at=datetime(2025, 1, 6, 12, tzinfo=timezone.utc), url="https://example.invalid/news/acme-update", source="mock_news_fixture")],
            "NOVA": [NewsArticle(ticker="NOVA", title="Nova Example Systems publishes a fictional engineering note", publisher="Example News", published_at=datetime(2025, 1, 6, 13, tzinfo=timezone.utc), url="https://example.invalid/news/nova-note", source="mock_news_fixture")],
            "ORB": [NewsArticle(ticker="ORB", title="Orbit Example Holdings: fictional market brief", publisher="Example News", published_at=datetime(2025, 1, 6, 14, tzinfo=timezone.utc), url="https://example.invalid/news/orb-brief", source="mock_news_fixture")],
            "ORB.L": [NewsArticle(ticker="ORB.L", title="Orbit Example Holdings: fictional London-market brief", publisher="Example News", published_at=datetime(2025, 1, 6, 14, tzinfo=timezone.utc), url="https://example.invalid/news/orb-l-brief", source="mock_news_fixture")],
        }

    def resolve(self, query: str) -> list[Security]:
        normalized = query.casefold().strip()
        exact = [s for s in self._securities if s.ticker.casefold() == normalized]
        if exact:
            return exact
        return [s for s in self._securities if s.company_name.casefold() == normalized]

    def get_quote(self, security: Security) -> MarketObservation | None:
        series = self._history.get(security.ticker, [])
        if not series:
            return None
        day, price = series[-1]
        return MarketObservation(
            ticker=security.ticker,
            exchange=security.exchange,
            currency=security.currency,
            observed_at=datetime(day.year, day.month, day.day, 21, tzinfo=timezone.utc),
            price=price,
            observation_type="quote",
            freshness=Freshness.SIMULATED,
            source="fictional_local_fixture",
        )

    def get_history(
        self, security: Security, start_date: date | None, end_date: date | None
    ) -> list[MarketObservation]:
        observations = []
        for day, price in self._history.get(security.ticker, []):
            if start_date and day < start_date:
                continue
            if end_date and day > end_date:
                continue
            observations.append(MarketObservation(
                ticker=security.ticker,
                exchange=security.exchange,
                currency=security.currency,
                observed_at=datetime(day.year, day.month, day.day, 21, tzinfo=timezone.utc),
                price=price,
                observation_type="daily_close",
                freshness=Freshness.SIMULATED,
                source="fictional_local_fixture",
            ))
        return observations

    def get_profile(self, security: Security) -> CompanyProfile | None:
        details = self._profiles.get(security.ticker)
        if not details:
            return None
        return CompanyProfile(
            ticker=security.ticker,
            company_name=security.company_name,
            exchange=security.exchange,
            currency=security.currency,
            sector=details[0],
            description=details[1],
            as_of=date(2025, 1, 6),
            source="fictional_local_fixture",
        )

    def get_news(self, security: Security) -> list[NewsArticle]:
        return list(self._news.get(security.ticker, []))


class YFinanceProvider:
    """Market data from Yahoo Finance via the yfinance library (unofficial; quotes may be delayed)."""

    def __init__(self, yf_module: Any | None = None, max_matches: int = 5) -> None:
        if yf_module is None:
            import yfinance as yf_module  # lazy: mock/test runs do not need yfinance installed
        self._yf = yf_module
        self._max_matches = max_matches

    def resolve(self, query: str) -> list[Security]:
        text = query.strip()
        if not text:
            return []
        if _SYMBOL_LIKE.match(text):
            security = self._resolve_symbol(text.upper())
            if security:
                return [security]
        return [self._with_currency(candidate) for candidate in self.suggest(text)]

    def suggest(self, query: str) -> list[Security]:
        """Yahoo search matches for a name or misspelled symbol (currency is not looked up)."""
        try:
            quotes = self._yf.Search(query.strip(), max_results=self._max_matches).quotes
        except Exception:
            return []
        matches: list[Security] = []
        for item in quotes:
            if item.get("quoteType") not in _SEARCHABLE_TYPES or not item.get("symbol"):
                continue
            matches.append(Security(
                ticker=item["symbol"],
                exchange=item.get("exchDisp") or item.get("exchange") or "unknown",
                company_name=item.get("longname") or item.get("shortname") or item["symbol"],
                currency="N/A",
            ))
        return matches

    def get_quote(self, security: Security) -> MarketObservation | None:
        price = _finite(self._yf.Ticker(security.ticker).fast_info["last_price"])
        if price is None:
            return None
        return MarketObservation(
            ticker=security.ticker,
            exchange=security.exchange,
            currency=security.currency,
            observed_at=datetime.now(timezone.utc),
            price=price,
            observation_type="quote",
            freshness=Freshness.DELAYED,  # Yahoo data can lag the exchange by ~15 minutes
            source=YFINANCE_SOURCE,
        )

    def get_history(
        self, security: Security, start_date: date | None, end_date: date | None
    ) -> list[MarketObservation]:
        ticker = self._yf.Ticker(security.ticker)
        if start_date or end_date:
            # yfinance treats `end` as exclusive; auto_adjust=False keeps closes free of dividend adjustments.
            frame = ticker.history(
                start=(start_date or date(1970, 1, 1)).isoformat(),
                end=((end_date or date.today()) + timedelta(days=1)).isoformat(),
                interval="1d",
                auto_adjust=False,
            )
        else:
            frame = ticker.history(period="1mo", interval="1d", auto_adjust=False)
        if frame is None or frame.empty:
            return []
        observations = []
        for stamp, close in frame["Close"].items():
            price = _finite(close)
            if price is None:
                continue
            observed_at = stamp.to_pydatetime()
            if observed_at.tzinfo is None:
                observed_at = observed_at.replace(tzinfo=timezone.utc)
            observations.append(MarketObservation(
                ticker=security.ticker,
                exchange=security.exchange,
                currency=security.currency,
                observed_at=observed_at,
                price=price,
                observation_type="daily_close",
                freshness=Freshness.HISTORICAL,
                source=YFINANCE_SOURCE,
            ))
        return observations

    def get_profile(self, security: Security) -> CompanyProfile | None:
        info = self._yf.Ticker(security.ticker).info or {}
        description = info.get("longBusinessSummary")
        sector = info.get("sector") or info.get("quoteType")
        if not description and not sector:
            return None
        return CompanyProfile(
            ticker=security.ticker,
            company_name=info.get("longName") or info.get("shortName") or security.company_name,
            exchange=security.exchange,
            currency=security.currency,
            sector=sector or "Unknown",
            description=description or "No description available from Yahoo Finance.",
            as_of=date.today(),
            source=YFINANCE_SOURCE,
        )

    def get_news(self, security: Security) -> list[NewsArticle]:
        items = self._yf.Ticker(security.ticker).news
        if not items:
            # Ticker.news is sometimes empty even when Yahoo's search endpoint has headlines.
            items = self._yf.Search(security.ticker, max_results=1, news_count=self._max_matches * 2).news
        articles = []
        for item in items or []:
            content = item.get("content") or item  # current yfinance nests fields under "content"
            title = content.get("title")
            url = (
                (content.get("canonicalUrl") or {}).get("url")
                or (content.get("clickThroughUrl") or {}).get("url")
                or content.get("link")
            )
            published = _parse_news_time(content.get("pubDate") or content.get("providerPublishTime"))
            if not title or not url or published is None:
                continue
            provider = content.get("provider") or {}
            articles.append(NewsArticle(
                ticker=security.ticker,
                title=title,
                publisher=provider.get("displayName") or content.get("publisher") or "Unknown publisher",
                published_at=published,
                url=url,
                source=YFINANCE_SOURCE,
            ))
        return articles

    def _resolve_symbol(self, symbol: str) -> Security | None:
        try:
            fast_info = self._yf.Ticker(symbol).fast_info
            if _finite(fast_info["last_price"]) is None:
                return None
            currency = fast_info["currency"] or "N/A"
            exchange = fast_info["exchange"] or "unknown"
        except Exception:
            return None  # unknown symbol: fall back to name search / suggestions
        name = symbol
        for candidate in self.suggest(symbol):
            if candidate.ticker.upper() == symbol:
                name, exchange = candidate.company_name, candidate.exchange
                break
        return Security(ticker=symbol, exchange=exchange, company_name=name, currency=currency)

    def _with_currency(self, security: Security) -> Security:
        try:
            currency = self._yf.Ticker(security.ticker).fast_info["currency"]
        except Exception:
            currency = None
        return security.model_copy(update={"currency": currency or "N/A"})


def create_provider() -> MarketDataProvider:
    """Pick the data provider: yfinance by default, STOCK_PROVIDER=mock for offline fixtures."""
    choice = os.getenv("STOCK_PROVIDER", "yfinance").strip().lower()
    if choice == "mock":
        return MockMarketDataProvider()
    if choice in {"", "yfinance"}:
        return YFinanceProvider()
    raise ValueError(f"Unknown STOCK_PROVIDER '{choice}'; use 'yfinance' or 'mock'.")


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _parse_news_time(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
