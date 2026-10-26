"""Streamlit UI. Run from the repository root:

    streamlit run StocksExercise/ui_app.py
"""
from __future__ import annotations

from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from stockresearch.graph import run_research
from stockresearch.hints import EXAMPLES, TICKER_HINTS
from stockresearch.models import ResearchResult, ResearchTask, Security
from stockresearch.providers import MockMarketDataProvider, YFinanceProvider
from stockresearch.ui_helpers import CHART_RANGES, build_message, chart_range, close_rows, percent_change

load_dotenv()
st.set_page_config(page_title="Stock Research Assistant", page_icon="📈", layout="wide")

PLACEHOLDER = 'MSFT, BRK-B, 7203.T or "Microsoft"'
TASK_LABELS = {
    ResearchTask.QUOTE: "Quote",
    ResearchTask.HISTORY: "Performance (history)",
    ResearchTask.PROFILE: "Company profile",
    ResearchTask.NEWS: "News",
}


@st.cache_resource
def get_provider(name: str):
    return MockMarketDataProvider() if name == "mock" else YFinanceProvider()


@st.cache_data(ttl=60, show_spinner=False)
def research(message: str, provider_name: str) -> ResearchResult:
    return run_research(message, provider=get_provider(provider_name))


@st.cache_data(ttl=300, show_spinner=False)
def load_history(provider_name: str, ticker: str, exchange: str, name: str, currency: str, start: date, end: date):
    security = Security(ticker=ticker, exchange=exchange, company_name=name, currency=currency)
    if provider_name == "mock":  # fixtures only cover a few days in Jan 2025, so ignore the range
        start = end = None
    return close_rows(get_provider(provider_name).get_history(security, start, end))


def render_chart(security: Security, index: int) -> None:
    st.subheader(f"{security.company_name} ({security.ticker}) price history")
    label = st.radio(
        "Range", list(CHART_RANGES), index=1, horizontal=True, key=f"range-{index}", label_visibility="collapsed"
    )
    start, end = chart_range(label)
    try:
        rows = load_history(
            st.session_state["provider_name"], security.ticker, security.exchange,
            security.company_name, security.currency, start, end,
        )
    except Exception as exc:
        st.warning(f"Could not load price history: {exc}")
        return
    if not rows:
        st.info("No price history available for this range.")
        return
    chart = (
        alt.Chart(pd.DataFrame(rows))
        .mark_line()
        .encode(
            x=alt.X("date:T", title=None),
            y=alt.Y("price:Q", title=f"Close ({security.currency})", scale=alt.Scale(zero=False)),
            tooltip=["date:T", "price:Q"],
        )
    )
    st.altair_chart(chart, width="stretch")
    change = percent_change(rows)
    suffix = f" Change over range: {change:+.2f}%." if change is not None else ""
    st.caption(f"Daily closes ({security.currency}), unadjusted for dividends.{suffix}")


def render_result(result: ResearchResult, index: int) -> None:
    st.markdown(result.answer)
    if result.security is not None:
        render_chart(result.security, index)
    if result.errors:
        with st.expander("Data notes"):
            for error in result.errors:
                st.write(f"- {error}")
    if result.candidates:
        st.write("Pick a listing:")
        for position, security in enumerate(result.candidates):
            st.button(
                f"{security.ticker} — {security.exchange} — {security.company_name}",
                key=f"pick-{index}-{position}",
                on_click=pick_listing,
                args=(result, security.ticker),
            )


def pick_listing(result: ResearchResult, ticker: str) -> None:
    intent = result.intent
    st.session_state["pending"] = build_message(
        ticker, intent.tasks or [ResearchTask.QUOTE], intent.start_date, intent.end_date, intent.save_report
    )


st.title("📈 Stock Research Assistant")
st.session_state.setdefault("messages", [])
pending: str | None = st.session_state.pop("pending", None)

with st.sidebar:
    st.header("Lookup")
    source = st.radio("Data source", ["yfinance (live)", "mock (fictional)"], horizontal=False)
    provider_name = "mock" if source.startswith("mock") else "yfinance"
    st.session_state["provider_name"] = provider_name
    with st.form("lookup"):
        ticker = st.text_input("Ticker or company", placeholder=PLACEHOLDER, help=TICKER_HINTS)
        tasks = st.multiselect(
            "What do you want?", list(TASK_LABELS), default=[ResearchTask.QUOTE], format_func=TASK_LABELS.get
        )
        today = date.today()
        dates = st.date_input("History range", (today - timedelta(days=30), today), max_value=today)
        save = st.checkbox("Save report")
        submitted = st.form_submit_button("Research", type="primary")
    st.caption("Examples")
    for example in EXAMPLES:
        st.code(example, language=None)
    if submitted:
        if not ticker.strip():
            st.warning("Enter a ticker or company name.")
        else:
            start, end = (dates if isinstance(dates, tuple) and len(dates) == 2 else (None, None))
            pending = build_message(ticker, tasks, start, end, save)

chat_text = st.chat_input(f"Ask about a stock, e.g. {EXAMPLES[0]}")
if chat_text:
    pending = chat_text

if pending:
    with st.spinner("Fetching data..."):
        result = research(pending, provider_name)
    st.session_state["messages"].append({"role": "user", "text": pending})
    st.session_state["messages"].append({"role": "assistant", "result": result})

if not st.session_state["messages"]:
    st.info("Use the sidebar form or type a question below.\n\n" + TICKER_HINTS.replace("\n", "  \n"))

last_index = len(st.session_state["messages"]) - 1
for index, message in enumerate(st.session_state["messages"]):
    with st.chat_message(message["role"]):
        if message["role"] == "user":
            st.write(message["text"])
        elif index == last_index:
            render_result(message["result"], index)
        else:  # older turns: answer only, so listing buttons are not offered twice
            st.markdown(message["result"].answer)

st.caption("Informational research only, not investment advice. Live data comes from Yahoo Finance via yfinance and may be delayed.")
