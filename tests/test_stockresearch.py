from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from StocksExercise.stockresearch.graph import build_graph, run_research
from StocksExercise.stockresearch.intent import parse_intent_offline
from StocksExercise.stockresearch.models import Freshness, ResearchTask, Security
from StocksExercise.stockresearch.providers import MockMarketDataProvider, YFinanceProvider, create_provider
from StocksExercise.stockresearch.ui_helpers import build_message, chart_range, history_rows, percent_change

MOCK = MockMarketDataProvider()


class StockResearchTests(unittest.TestCase):
    def test_quote_request_uses_fictional_timestamped_data(self) -> None:
        result = run_research("What is the latest quote for ACME?", provider=MOCK)
        self.assertIn("ACME", result.answer)
        self.assertIn("simulated", result.answer)
        self.assertIn("fictional_local_fixture", result.answer)
        self.assertTrue(result.observations)

    def test_history_return_uses_requested_fixture_range(self) -> None:
        result = run_research("Show ACME performance from 2025-01-02 to 2025-01-06", provider=MOCK)
        self.assertIn("Historical price return: +1.25%", result.answer)
        self.assertIn("excluding dividends", result.answer)
        self.assertEqual(len(result.observations), 3)

    def test_company_profile_route(self) -> None:
        result = run_research("Show the profile for NOVA", provider=MOCK)
        self.assertIsNotNone(result.profile)
        self.assertIn("Technology", result.answer)

    def test_news_route_contains_source_link_and_date(self) -> None:
        result = run_research("Summarize the latest news for ACME", provider=MOCK)
        self.assertEqual(len(result.articles), 1)
        self.assertIn("https://example.invalid/news/acme-update", result.answer)
        self.assertIn("2025-01-06", result.answer)

    def test_ambiguous_company_name_asks_clarification(self) -> None:
        result = run_research("Show a quote for Orbit Example Holdings", provider=MOCK)
        self.assertIsNone(result.security)
        self.assertIn("multiple matches", result.answer)
        self.assertIn("ORB.L", result.answer)

    def test_unknown_ticker_not_guessed(self) -> None:
        result = run_research("What is the quote for XYZQ?", provider=MOCK)
        self.assertIsNone(result.security)
        self.assertIn("couldn't match", result.answer)

    def test_personalized_trade_request_is_out_of_scope(self) -> None:
        result = run_research("Should I buy shares of ACME?", provider=MOCK)
        self.assertTrue(result.intent.unsupported_financial_advice)
        self.assertIn("can't make personalized buy/sell decisions", result.answer)

    def test_report_is_saved_without_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_research(
                "Save report: quote ACME",
                provider=MOCK,
                report_dir=Path(tmp),
            )
            self.assertIsNotNone(result.report_path)
            assert result.report_path is not None
            self.assertTrue(Path(result.report_path).exists())
            self.assertIn("Report saved to", result.answer)

    def test_notification_is_not_sent_by_default(self) -> None:
        result = run_research("Notify me with a quote for ACME", provider=MOCK)
        self.assertEqual(result.notification_status, "Not configured; no notification was sent.")
        self.assertIn("no notification was sent", result.answer)

    def test_provider_failure_keeps_chat_response(self) -> None:
        class FailingProvider(MockMarketDataProvider):
            def get_quote(self, security):
                raise RuntimeError("fixture provider unavailable")

        result = run_research("What is the quote for ACME?", provider=FailingProvider())
        self.assertIn("Research summary", result.answer)
        self.assertTrue(any("fixture provider unavailable" in error for error in result.errors))

    def test_offline_parser_does_not_treat_question_word_as_ticker(self) -> None:
        intent = parse_intent_offline("What is the stock price?")
        self.assertIsNone(intent.ticker_or_company)

    def test_explicit_date_range_intent(self) -> None:
        intent = parse_intent_offline("Show ACME performance from 2025-01-02 to 2025-01-06")
        self.assertIn(ResearchTask.HISTORY, intent.tasks)
        assert intent.start_date is not None
        assert intent.end_date is not None
        self.assertEqual(intent.start_date.isoformat(), "2025-01-02")
        self.assertEqual(intent.end_date.isoformat(), "2025-01-06")

    def test_graph_compiles(self) -> None:
        graph = build_graph(provider=MOCK)
        self.assertIsNotNone(graph)

    def test_offline_parser_extracts_real_world_symbols(self) -> None:
        cases = {
            "quote MSFT": "MSFT",
            "history of BRK-B last 3 months": "BRK-B",
            "profile 7203.T": "7203.T",
            "$TSLA news": "TSLA",
            "What is the quote for XYZQ?": "XYZQ",
            "show ticker sap.de profile": "SAP.DE",
            "quote appel": "appel",
            "latest news about berkshire hathaway": "berkshire hathaway",
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                self.assertEqual(parse_intent_offline(message).ticker_or_company, expected)

    def test_clarifications_include_ticker_hints(self) -> None:
        missing = run_research("What is the stock price?", provider=MOCK)
        self.assertIn("How to enter a ticker", missing.answer)
        unknown = run_research("What is the quote for XYZQ?", provider=MOCK)
        self.assertIn("BRK-B", unknown.answer)

    def test_not_found_includes_did_you_mean(self) -> None:
        class SuggestingProvider(MockMarketDataProvider):
            def suggest(self, query):
                return [Security(ticker="AAPL", exchange="NASDAQ", company_name="Apple Inc.", currency="N/A")]

        result = run_research("What is the quote for XYZQ?", provider=SuggestingProvider())
        self.assertIn("Did you mean: AAPL (NASDAQ) - Apple Inc.", result.answer)


class UiHelperTests(unittest.TestCase):
    def test_build_message_round_trips_through_parser(self) -> None:
        message = build_message(
            "BRK-B", [ResearchTask.QUOTE, ResearchTask.HISTORY, ResearchTask.NEWS],
            date(2025, 1, 2), date(2025, 6, 30), save_report=True,
        )
        intent = parse_intent_offline(message)
        self.assertEqual(intent.ticker_or_company, "BRK-B")
        self.assertEqual(set(intent.tasks), {ResearchTask.QUOTE, ResearchTask.HISTORY, ResearchTask.NEWS})
        self.assertEqual((intent.start_date, intent.end_date), (date(2025, 1, 2), date(2025, 6, 30)))
        self.assertTrue(intent.save_report)

    def test_build_message_keeps_company_names_verbatim(self) -> None:
        intent = parse_intent_offline(build_message("toyota motor", [ResearchTask.PROFILE]))
        self.assertEqual(intent.ticker_or_company, "toyota motor")
        self.assertEqual(intent.tasks, [ResearchTask.PROFILE])

    def test_history_rows_sorted_and_requires_two_points(self) -> None:
        result = run_research("Show ACME performance from 2025-01-02 to 2025-01-06", provider=MOCK)
        rows = history_rows(result)
        self.assertEqual([row["price"] for row in rows], [100.0, 102.5, 101.25])
        single = run_research("Show ACME performance from 2025-01-02 to 2025-01-02", provider=MOCK)
        self.assertEqual(history_rows(single), [])

    def test_chart_range_and_percent_change(self) -> None:
        self.assertEqual(chart_range("1M", date(2026, 10, 26)), (date(2026, 9, 26), date(2026, 10, 26)))
        self.assertAlmostEqual(percent_change([{"date": 1, "price": 100.0}, {"date": 2, "price": 110.0}]), 10.0)
        self.assertIsNone(percent_change([{"date": 1, "price": 100.0}]))

    def test_ambiguous_name_exposes_candidates(self) -> None:
        result = run_research("Show a quote for Orbit Example Holdings", provider=MOCK)
        self.assertEqual({item.ticker for item in result.candidates}, {"ORB", "ORB.L"})

    def test_streamlit_app_smoke(self) -> None:
        from streamlit.testing.v1 import AppTest

        app_path = str(Path(__file__).resolve().parent.parent / "ui_app.py")
        app = AppTest.from_file(app_path, default_timeout=30)
        app.run()
        self.assertFalse(app.exception)
        app.sidebar.radio[0].set_value("mock (fictional)")
        app.sidebar.text_input[0].set_value("ACME")
        app.sidebar.multiselect[0].set_value([ResearchTask.QUOTE, ResearchTask.HISTORY])
        app.sidebar.button[0].click()
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any("Acme Example Corporation" in md.value for md in app.markdown))
        self.assertTrue(any("price history" in sub.value for sub in app.subheader))  # chart shown for quote-only request


class FakeFrame:
    """Minimal stand-in for a pandas DataFrame with a Close column."""

    def __init__(self, rows):
        self._rows = rows
        self.empty = not rows

    def __getitem__(self, key):
        return FakeSeries(self._rows)


class FakeSeries:
    def __init__(self, rows):
        self._rows = rows

    def items(self):
        return iter(self._rows)


class FakeStamp:
    def __init__(self, dt):
        self._dt = dt

    def to_pydatetime(self):
        return self._dt


class FakeTicker:
    news: list = []
    info: dict = {}
    history_calls: list = []
    history_rows: list = []

    def __init__(self, symbol):
        self.symbol = symbol
        if symbol == "NOPE":
            self.fast_info = {"last_price": None, "currency": None, "exchange": None}
        else:
            self.fast_info = {"last_price": 123.45, "currency": "USD", "exchange": "NMS"}

    def history(self, **kwargs):
        FakeTicker.history_calls.append(kwargs)
        return FakeFrame(FakeTicker.history_rows)


class FakeSearch:
    news: list = []

    def __init__(self, query, max_results=5, news_count=0):
        self.news = FakeSearch.news
        self.quotes = [
            {"symbol": "AAPL", "quoteType": "EQUITY", "longname": "Apple Inc.", "exchDisp": "NASDAQ"},
            {"symbol": "SAAPL=F", "quoteType": "FUTURE", "longname": "Apple futures", "exchDisp": "CME"},
        ]


class FakeYF:
    Ticker = FakeTicker
    Search = FakeSearch


class YFinanceProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeTicker.history_calls = []
        FakeTicker.history_rows = []
        FakeTicker.news = []
        FakeTicker.info = {}
        self.provider = YFinanceProvider(yf_module=FakeYF)
        self.security = Security(ticker="AAPL", exchange="NASDAQ", company_name="Apple Inc.", currency="USD")

    def test_resolve_valid_symbol(self) -> None:
        (security,) = self.provider.resolve("aapl")
        self.assertEqual((security.ticker, security.exchange, security.company_name, security.currency),
                         ("AAPL", "NASDAQ", "Apple Inc.", "USD"))

    def test_resolve_company_name_uses_search_and_filters_non_equities(self) -> None:
        results = self.provider.resolve("Apple Inc")
        self.assertEqual([item.ticker for item in results], ["AAPL"])
        self.assertEqual(results[0].currency, "USD")

    def test_unknown_symbol_falls_back_to_search(self) -> None:
        self.assertEqual([item.ticker for item in self.provider.resolve("NOPE")], ["AAPL"])

    def test_quote_is_labeled_delayed(self) -> None:
        quote = self.provider.get_quote(self.security)
        assert quote is not None
        self.assertEqual(quote.freshness, Freshness.DELAYED)
        self.assertEqual(quote.price, 123.45)

    def test_history_end_is_inclusive_and_unadjusted(self) -> None:
        FakeTicker.history_rows = [(FakeStamp(datetime(2025, 1, 2, tzinfo=timezone.utc)), 100.0),
                                   (FakeStamp(datetime(2025, 1, 3, tzinfo=timezone.utc)), float("nan"))]
        result = self.provider.get_history(self.security, date(2025, 1, 2), date(2025, 1, 6))
        call = FakeTicker.history_calls[0]
        self.assertEqual((call["start"], call["end"], call["auto_adjust"]), ("2025-01-02", "2025-01-07", False))
        self.assertEqual(len(result), 1)  # NaN close skipped
        self.assertEqual(result[0].freshness, Freshness.HISTORICAL)

    def test_history_defaults_to_one_month_and_handles_empty(self) -> None:
        self.assertEqual(self.provider.get_history(self.security, None, None), [])
        self.assertEqual(FakeTicker.history_calls[0]["period"], "1mo")

    def test_news_handles_nested_and_flat_shapes(self) -> None:
        FakeTicker.news = [
            {"content": {"title": "Nested", "provider": {"displayName": "Wire"},
                         "pubDate": "2025-01-06T12:00:00Z", "canonicalUrl": {"url": "https://example.com/n"}}},
            {"title": "Flat", "publisher": "Old", "link": "https://example.com/f", "providerPublishTime": 1736164800},
            {"content": {"title": "No url", "pubDate": "2025-01-06T12:00:00Z"}},
        ]
        articles = self.provider.get_news(self.security)
        self.assertEqual([a.title for a in articles], ["Nested", "Flat"])
        self.assertEqual(articles[0].publisher, "Wire")

    def test_news_falls_back_to_search_when_ticker_news_empty(self) -> None:
        FakeSearch.news = [{"title": "Via search", "publisher": "Yahoo Finance", "link": "https://example.com/s",
                            "providerPublishTime": 1736164800}]
        try:
            articles = self.provider.get_news(self.security)
        finally:
            FakeSearch.news = []
        self.assertEqual([a.title for a in articles], ["Via search"])

    def test_profile_from_info(self) -> None:
        FakeTicker.info = {"sector": "Technology", "longBusinessSummary": "Makes things.", "longName": "Apple Inc."}
        profile = self.provider.get_profile(self.security)
        assert profile is not None
        self.assertEqual(profile.sector, "Technology")

    def test_graph_end_to_end_with_yfinance_labels(self) -> None:
        result = run_research("quote AAPL", provider=self.provider)
        self.assertIn("delayed", result.answer)
        self.assertIn("yfinance", result.answer)
        self.assertNotIn("fictional", result.answer)

    def test_create_provider_env_switch(self) -> None:
        with patch.dict(os.environ, {"STOCK_PROVIDER": "mock"}):
            self.assertIsInstance(create_provider(), MockMarketDataProvider)
        with patch.dict(os.environ, {"STOCK_PROVIDER": "bogus"}):
            with self.assertRaises(ValueError):
                create_provider()


if __name__ == "__main__":
    unittest.main()
