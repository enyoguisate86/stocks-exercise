from __future__ import annotations

import os
import re
from datetime import date, timedelta
from typing import cast

from .models import Intent, ResearchTask


ALIASES = {
    "microsoft": "MSFT",
    "apple": "AAPL",
    "nvidia": "NVDA",
    "acme example corporation": "ACME",
    "nova example systems": "NOVA",
    "alphabet": "GOOGL",
    "google": "GOOGL",
    "amazon": "AMZN",
    "tesla": "TSLA",
    "meta platforms": "META",
}
KNOWN_TICKERS = {"ACME", "NOVA", "ORB", "ORB.L", "MSFT", "AAPL", "NVDA"}

# Real-world symbol shapes: AAPL, BRK-B, 7203.T, SAP.DE, ^GSPC, BTC-USD.
_SYMBOL_TOKEN = re.compile(
    r"(?<![A-Za-z0-9$^])\$?(\^[A-Z]{1,6}|[A-Z]{2,6}-USD|\d{4,5}\.[A-Z]{1,2}|[A-Z]{1,5}(?:[.-][A-Z0-9]{1,3})?)(?![A-Za-z0-9])"
)
_NOT_SYMBOLS = {
    "A", "I", "AN", "AND", "ARE", "ABOUT", "ALL", "ANY", "AT", "BE", "BUY", "BY", "CAN", "DO", "FOR", "FROM",
    "GET", "GIVE", "HOW", "IN", "IS", "IT", "ME", "MY", "NEWS", "NOTIFY", "OF", "ON", "OR", "PRICE", "PROFILE",
    "QUOTE", "REPORT", "SAVE", "SELL", "SHOW", "SO", "STOCK", "TELL", "THE", "TO", "UP", "US", "WAS", "WHAT",
    "WHEN", "WHO", "WHY", "WITH", "YOU", "YTD", "ETF",
}
_FILLER_WORDS = {
    "a", "an", "the", "me", "my", "it", "its", "latest", "recent", "current", "stock", "stocks", "price", "prices",
    "quote", "news", "profile", "performance", "history", "today", "now", "please", "this", "last", "company",
    "share", "shares", "and", "with", "from", "over", "during", "between", "including", "report", "info",
}


class IntentParser:
    """Use a configured LangChain chat model when available; otherwise parse offline."""

    def __init__(self) -> None:
        self._structured_model = None
        self._model = None
        provider = os.getenv("STOCK_LLM_PROVIDER", "").strip().lower()
        try:
            if provider == "openai" and os.getenv("OPENAI_API_KEY"):
                from langchain_openai import ChatOpenAI

                self._model = ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), temperature=0)
            elif provider == "groq" and os.getenv("GROQ_API_KEY"):
                from langchain_groq import ChatGroq

                self._model = ChatGroq(model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"), temperature=0)
            if self._model is not None:
                self._structured_model = self._model.with_structured_output(Intent)
        except Exception:
            # Offline mode is an intentional fallback for missing/unsupported model setup.
            self._structured_model = None
            self._model = None

    def parse(self, message: str) -> Intent:
        if self._structured_model is not None:
            try:
                result = self._structured_model.invoke([
                    ("system", "Extract stock research intent as the requested schema. Only support factual quote, historical performance, company profile, and news research. Set unsupported_financial_advice for personalized investment advice, buy/sell decisions, or trading. Do not invent a ticker; return a company or ticker string only when explicit."),
                    ("human", message),
                ])
                return cast(Intent, result)
            except Exception:
                pass
        return parse_intent_offline(message)


def parse_intent_offline(message: str) -> Intent:
    text = message.strip()
    lowered = text.casefold()
    ticker_or_company = _extract_symbol_or_company(text)

    advice = bool(re.search(r"\b(should i buy|should i sell|buy or sell|tell me what to buy|place (?:a )?trade|execute (?:a )?trade|buy shares|sell shares)\b", lowered))
    tasks: list[ResearchTask] = []
    if any(word in lowered for word in ("quote", "stock price", "share price", "current price", "latest price", "latest quote")):
        tasks.append(ResearchTask.QUOTE)
    if any(word in lowered for word in ("history", "historical", "performance", "return", "change over", "price movement", "last ")):
        tasks.append(ResearchTask.HISTORY)
    if any(word in lowered for word in ("company info", "company information", "profile", "sector", "fundamentals", "what does", "about the company")):
        tasks.append(ResearchTask.PROFILE)
    if any(word in lowered for word in ("news", "headline", "article", "articles")):
        tasks.append(ResearchTask.NEWS)
    if not tasks and not advice and ticker_or_company:
        tasks.append(ResearchTask.QUOTE)

    start_date, end_date = _extract_dates(text, lowered)
    return Intent(
        ticker_or_company=ticker_or_company,
        tasks=list(dict.fromkeys(tasks)),
        start_date=start_date,
        end_date=end_date,
        save_report=any(word in lowered for word in ("save report", "save this", "export report", "write a report")),
        notify=any(word in lowered for word in ("notify me", "send notification", "send me an alert")),
        unsupported_financial_advice=advice,
    )


def _extract_symbol_or_company(text: str) -> str | None:
    for alias, ticker in ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", text, re.IGNORECASE):
            return ticker
    for ticker in sorted(KNOWN_TICKERS, key=len, reverse=True):
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(ticker)}(?![A-Za-z0-9])", text, re.IGNORECASE):
            return ticker
    quoted = re.search(r"[\"']([^\"']+)[\"']", text)
    if quoted:
        return quoted.group(1).strip()
    explicit = re.search(r"(?:\b(?i:ticker|symbol)\s+(?:is\s+)?|\$)([A-Za-z][A-Za-z0-9.\-]{0,9})\b", text)
    if explicit:
        return explicit.group(1).upper()
    for match in _SYMBOL_TOKEN.finditer(text):
        token = match.group(1)
        if token not in _NOT_SYMBOLS:
            return token
    named_subject = re.search(r"\b(?:for|about|on|of)\s+([A-Z][A-Za-z0-9& .'-]{1,60}?)(?=\s+(?:from|between|over|during|today|this|last|and|with|including)\b|[?.!,;:]|$)", text)
    if named_subject:
        subject = named_subject.group(1).strip()
        if subject.casefold() not in {"me", "the company", "stocks", "shares"}:
            return subject
    # Last resort for lowercase or misspelled names ("quote appel"): let the provider's search sort it out.
    trailing = re.search(
        r"\b(?:quote|price|news|profile|performance|history|stocks?|shares?|for|about|of)\s+"
        r"([A-Za-z][A-Za-z0-9&.'-]*(?:\s+[A-Za-z][A-Za-z0-9&.'-]*){0,2})\s*[?.!]*$",
        text,
        re.IGNORECASE,
    )
    if trailing:
        words: list[str] = []
        for word in trailing.group(1).split():
            if not words and word.casefold() in {"for", "about", "of", "on"}:
                continue
            if word.casefold() in _FILLER_WORDS:
                break
            words.append(word)
        if words:
            return " ".join(words)
    return None


def _extract_dates(text: str, lowered: str) -> tuple[date | None, date | None]:
    iso_dates = re.findall(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if len(iso_dates) >= 2:
        try:
            return date.fromisoformat(iso_dates[0]), date.fromisoformat(iso_dates[1])
        except ValueError:
            return None, None
    if len(iso_dates) == 1:
        try:
            return date.fromisoformat(iso_dates[0]), date.fromisoformat(iso_dates[0])
        except ValueError:
            return None, None

    relative = re.search(r"last\s+(\d+)\s+(day|week|month|year)s?", lowered)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2)
        days = amount * {"day": 1, "week": 7, "month": 30, "year": 365}[unit]
        return date.today() - timedelta(days=days), date.today()
    return None, None
