from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .hints import TICKER_HINTS, format_suggestions
from .intent import IntentParser
from .models import CompanyProfile, Freshness, Intent, MarketObservation, NewsArticle, ResearchResult, Security
from .providers import MarketDataProvider, create_provider


class ResearchState(TypedDict):
    message: str
    intent: Intent
    security: Security | None
    observations: list[MarketObservation]
    profile: CompanyProfile | None
    articles: list[NewsArticle]
    answer: str
    clarification: str | None
    candidates: list[Security]
    errors: list[str]
    report_path: str | None
    notification_status: str | None
    final: ResearchResult | None


class ResponseWriter:
    def __init__(self) -> None:
        self._model = None
        provider = os.getenv("STOCK_LLM_PROVIDER", "").strip().lower()
        try:
            if provider == "openai" and os.getenv("OPENAI_API_KEY"):
                from langchain_openai import ChatOpenAI

                self._model = ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), temperature=0)
            elif provider == "groq" and os.getenv("GROQ_API_KEY"):
                from langchain_groq import ChatGroq

                self._model = ChatGroq(model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"), temperature=0)
        except Exception:
            self._model = None

    def write(self, state: ResearchState) -> str:
        factual = _format_factual_answer(state)
        if self._model is None:
            return factual
        try:
            response = self._model.invoke([
                ("system", "Write a concise factual stock-research summary using only the supplied data. Preserve all dates, timestamps, currencies, freshness labels, sources, and URLs. Do not give personalized investment advice, buy/sell recommendations, or forecasts. If data is simulated, state it prominently."),
                ("human", f"User request: {state['message']}\n\nVerified data:\n{factual}"),
            ])
            return str(response.content).strip() or factual
        except Exception:
            return factual


def build_graph(
    provider: MarketDataProvider | None = None,
    parser: IntentParser | None = None,
    response_writer: ResponseWriter | None = None,
    report_dir: Path | None = None,
) -> Any:
    market = provider or create_provider()
    intent_parser = parser or IntentParser()
    writer = response_writer or ResponseWriter()
    reports = report_dir or Path(__file__).resolve().parent.parent / "reports"

    def parse_request(state: ResearchState) -> dict[str, Any]:
        return {"intent": intent_parser.parse(state["message"]), "errors": []}

    def reject_or_clarify(state: ResearchState) -> dict[str, Any]:
        intent = state["intent"]
        if state.get("clarification"):
            clarification = state["clarification"]
        elif intent.unsupported_financial_advice:
            clarification = "I can provide factual stock information and historical data, but I can't make personalized buy/sell decisions or place trades."
        elif not intent.tasks:
            clarification = f"I can look up a quote, historical performance, company profile, or recent news. What would you like to research? Please include a company name or ticker.\n\n{TICKER_HINTS}"
        elif not intent.ticker_or_company:
            clarification = f"Which company or ticker symbol should I research?\n\n{TICKER_HINTS}"
        else:
            clarification = None
        return {"clarification": clarification}

    def resolve_security(state: ResearchState) -> dict[str, Any]:
        query = state["intent"].ticker_or_company or ""
        try:
            candidates = market.resolve(query)
        except Exception as exc:
            return {"security": None, "clarification": f"I couldn't look up '{query}' because the data provider failed: {exc}. Please try again shortly."}
        if len(candidates) == 1:
            return {"security": candidates[0], "clarification": None}
        if len(candidates) > 1:
            options = ", ".join(f"{item.ticker} ({item.exchange})" for item in candidates)
            return {"security": None, "candidates": candidates, "clarification": f"I found multiple matches for that name: {options}. Which listing do you mean? Reply with the exact ticker (e.g. {candidates[0].ticker})."}
        message = f"I couldn't match '{query}' to a company or ticker in the configured data source. Please check the symbol or provide the exact company name."
        suggest = getattr(market, "suggest", None)
        if suggest is not None:
            try:
                suggestions = suggest(query)
            except Exception:
                suggestions = []
            if suggestions:
                message += f"\n\nDid you mean: {format_suggestions(suggestions)}?"
        return {"security": None, "clarification": f"{message}\n\n{TICKER_HINTS}"}

    def retrieve_market(state: ResearchState) -> dict[str, Any]:
        security = state["security"]
        intent = state["intent"]
        if security is None:
            return {}
        observations: list[MarketObservation] = []
        errors = list(state.get("errors", []))
        if "quote" in intent.tasks:
            try:
                quote = market.get_quote(security)
                if quote:
                    observations.append(quote)
                else:
                    errors.append("No quote is available from the configured provider.")
            except Exception as exc:
                errors.append(f"Quote provider failed: {exc}")
        if "history" in intent.tasks:
            try:
                history = market.get_history(security, intent.start_date, intent.end_date)
                observations.extend(history)
                if len(history) < 2:
                    errors.append("At least two observations are needed to calculate historical price return.")
            except Exception as exc:
                errors.append(f"Historical data provider failed: {exc}")
        return {"observations": observations, "errors": errors}

    def retrieve_profile(state: ResearchState) -> dict[str, Any]:
        security = state["security"]
        if security is None:
            return {}
        errors = list(state.get("errors", []))
        try:
            profile = market.get_profile(security)
        except Exception as exc:
            profile = None
            errors.append(f"Company profile provider failed: {exc}")
        if profile is None:
            if not any(error.startswith("Company profile provider failed:") for error in errors):
                errors.append("No company profile is available from the configured provider.")
        return {"profile": profile, "errors": errors}

    def retrieve_news(state: ResearchState) -> dict[str, Any]:
        security = state["security"]
        if security is None:
            return {}
        errors = list(state.get("errors", []))
        try:
            articles = market.get_news(security)
        except Exception as exc:
            articles = []
            errors.append(f"News provider failed: {exc}")
        if not articles:
            if not any(error.startswith("News provider failed:") for error in errors):
                errors.append("No news articles are available from the configured provider.")
        return {"articles": articles, "errors": errors}

    def compose(state: ResearchState) -> dict[str, Any]:
        return {"answer": writer.write(state)}

    def save_report(state: ResearchState) -> dict[str, Any]:
        reports.mkdir(parents=True, exist_ok=True)
        security = state["security"]
        ticker = security.ticker if security else "research"
        safe_ticker = re.sub(r"[^A-Za-z0-9.-]+", "_", ticker)
        path = reports / f"{safe_ticker}-{date.today().isoformat()}.md"
        try:
            path.write_text(state["answer"], encoding="utf-8")
            return {"report_path": str(path), "errors": list(state.get("errors", []))}
        except OSError as exc:
            errors = list(state.get("errors", []))
            errors.append(f"Could not save report: {exc}")
            return {"errors": errors}

    def notify(state: ResearchState) -> dict[str, Any]:
        # Safe default: no outbound message is sent unless a real adapter is explicitly added.
        return {"notification_status": "Not configured; no notification was sent."}

    def route_notification(state: ResearchState) -> dict[str, Any]:
        return {}

    def finish(state: ResearchState) -> dict[str, Any]:
        answer = state.get("answer") or state.get("clarification") or "I couldn't complete that research request."
        if state.get("report_path"):
            answer += f"\n\nReport saved to: {state['report_path']}"
        if state.get("notification_status"):
            answer += f"\n\nNotification: {state['notification_status']}"
        final = ResearchResult(
            answer=answer,
            intent=state["intent"],
            security=state.get("security"),
            observations=state.get("observations", []),
            profile=state.get("profile"),
            articles=state.get("articles", []),
            clarification=state.get("clarification"),
            candidates=state.get("candidates", []),
            errors=state.get("errors", []),
            report_path=state.get("report_path"),
            notification_status=state.get("notification_status"),
        )
        return {"final": final}

    def after_parse(state: ResearchState) -> str:
        intent = state["intent"]
        if intent.unsupported_financial_advice or not intent.tasks or not intent.ticker_or_company:
            return "clarify"
        return "resolve"

    def after_resolve(state: ResearchState) -> str:
        return "clarify" if state.get("clarification") else "market_route"

    def after_market(state: ResearchState) -> str:
        return "profile" if "profile" in state["intent"].tasks else "news_route"

    def after_profile(state: ResearchState) -> str:
        return "news_route"

    def news_route(state: ResearchState) -> str:
        return "news" if "news" in state["intent"].tasks else "compose"

    def route_news(state: ResearchState) -> dict[str, Any]:
        return {}

    def after_news(state: ResearchState) -> str:
        return "compose"

    def after_compose(state: ResearchState) -> str:
        return "save" if state["intent"].save_report else "notify_route"

    def notify_route(state: ResearchState) -> str:
        return "notify" if state["intent"].notify else "finish"

    def after_save(state: ResearchState) -> str:
        return "notify" if state["intent"].notify else "finish"

    graph = StateGraph(ResearchState)
    graph.add_node("parse_request", parse_request)
    graph.add_node("clarify", reject_or_clarify)
    graph.add_node("resolve_security", resolve_security)
    graph.add_node("retrieve_market", retrieve_market)
    graph.add_node("retrieve_profile", retrieve_profile)
    graph.add_node("news_route", route_news)
    graph.add_node("retrieve_news", retrieve_news)
    graph.add_node("compose", compose)
    graph.add_node("save_report", save_report)
    graph.add_node("notify_route", route_notification)
    graph.add_node("notify", notify)
    graph.add_node("finish", finish)

    graph.add_edge(START, "parse_request")
    graph.add_conditional_edges("parse_request", after_parse, {"clarify": "clarify", "resolve": "resolve_security"})
    graph.add_conditional_edges("resolve_security", after_resolve, {"clarify": "clarify", "market_route": "retrieve_market"})
    graph.add_conditional_edges("retrieve_market", after_market, {"profile": "retrieve_profile", "news_route": "news_route"})
    graph.add_conditional_edges("retrieve_profile", after_profile, {"news_route": "news_route"})
    graph.add_conditional_edges("news_route", news_route, {"news": "retrieve_news", "compose": "compose"})
    graph.add_conditional_edges("retrieve_news", after_news, {"compose": "compose"})
    graph.add_conditional_edges("compose", after_compose, {"save": "save_report", "notify_route": "notify_route"})
    graph.add_conditional_edges("save_report", after_save, {"notify": "notify", "finish": "finish"})
    graph.add_conditional_edges("notify_route", notify_route, {"notify": "notify", "finish": "finish"})
    graph.add_edge("clarify", "finish")
    graph.add_edge("notify", "finish")
    graph.add_edge("finish", END)
    return graph.compile()


def run_research(message: str, **graph_options: Any) -> ResearchResult:
    graph = build_graph(**graph_options)
    state = graph.invoke({
        "message": message,
        "intent": Intent(),
        "security": None,
        "observations": [],
        "profile": None,
        "articles": [],
        "answer": "",
        "clarification": None,
        "candidates": [],
        "errors": [],
        "report_path": None,
        "notification_status": None,
        "final": None,
    })
    result = state["final"]
    if result is None:
        raise RuntimeError("Stock research graph did not produce a result")
    return result


def _format_factual_answer(state: ResearchState) -> str:
    security = state.get("security")
    if security is None:
        return state.get("clarification") or "No matching security was resolved."
    blocks = [f"Research summary: {security.company_name} ({security.ticker}, {security.exchange})"]
    observations = state.get("observations", [])
    articles = state.get("articles", [])
    simulated = any(obs.freshness == Freshness.SIMULATED for obs in observations) or any(
        article.source == "mock_news_fixture" for article in articles
    ) or (state.get("profile") is not None and state["profile"].source == "fictional_local_fixture")
    quote = next((obs for obs in observations if obs.observation_type == "quote"), None)
    history = sorted((obs for obs in observations if obs.observation_type == "daily_close"), key=lambda obs: obs.observed_at)
    if quote:
        blocks.append(f"Latest available quote: {quote.currency} {quote.price:.2f} as of {quote.observed_at.isoformat()} ({quote.freshness.value}; source: {quote.source}).")
    if "history" in state["intent"].tasks:
        if len(history) >= 2:
            first, last = history[0], history[-1]
            change = (last.price - first.price) / first.price * 100 if first.price else 0.0
            blocks.append(f"Historical price return: {change:+.2f}% from {first.observed_at.date()} ({first.currency} {first.price:.2f}) to {last.observed_at.date()} ({last.currency} {last.price:.2f}); based on available daily closes, excluding dividends. {'Data is simulated' if simulated else 'Historical data'} (source: {last.source}).")
        else:
            blocks.append("Historical price return could not be calculated: fewer than two observations matched the requested range.")
    profile = state.get("profile")
    if profile:
        blocks.append(f"Company profile (as of {profile.as_of}; source: {profile.source}): sector {profile.sector}. {profile.description}")
    if articles:
        news_text = ["Recent news (mock fixture; fictional articles):" if simulated else f"Recent news (source: {articles[0].source}):"]
        for article in articles:
            news_text.append(f"- {article.title} — {article.publisher}, {article.published_at.isoformat()} — {article.url}")
        blocks.append("\n".join(news_text))
    errors = state.get("errors", [])
    if errors:
        blocks.append("Data notes: " + " ".join(errors))
    if simulated:
        blocks.append("This application uses fictional test data, not live market data. This is informational research, not personalized investment advice.")
    else:
        blocks.append("Market data comes from Yahoo Finance via the unofficial yfinance library and may be delayed or incomplete. This is informational research, not personalized investment advice.")
    return "\n\n".join(blocks)
