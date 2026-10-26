from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

from .models import MarketObservation, ResearchResult, ResearchTask

_TASK_WORDS = {
    ResearchTask.QUOTE: "quote",
    ResearchTask.HISTORY: "performance",
    ResearchTask.PROFILE: "profile",
    ResearchTask.NEWS: "news",
}


def build_message(
    ticker: str,
    tasks: Iterable[ResearchTask],
    start_date: date | None = None,
    end_date: date | None = None,
    save_report: bool = False,
) -> str:
    """Turn structured UI fields into a request the intent parser understands.

    The ticker is quoted so names like "Toyota" or symbols like BRK-B are taken verbatim.
    """
    chosen = [task for task in _TASK_WORDS if task in set(tasks)] or [ResearchTask.QUOTE]
    words = [_TASK_WORDS[task] for task in chosen]
    message = f'{", ".join(words)} for "{ticker.strip()}"'
    if ResearchTask.HISTORY in chosen and start_date and end_date:
        message += f" from {start_date.isoformat()} to {end_date.isoformat()}"
    return f"save report: {message}" if save_report else message


CHART_RANGES = {"1M": 30, "3M": 91, "6M": 182, "1Y": 365, "5Y": 1826}


def chart_range(label: str, today: date | None = None) -> tuple[date, date]:
    end = today or date.today()
    return end - timedelta(days=CHART_RANGES[label]), end


def close_rows(observations: Iterable[MarketObservation]) -> list[dict[str, object]]:
    """Daily closes as chart rows; empty unless there are at least two points."""
    closes = sorted(
        (obs for obs in observations if obs.observation_type == "daily_close"),
        key=lambda obs: obs.observed_at,
    )
    if len(closes) < 2:
        return []
    return [{"date": obs.observed_at.date(), "price": obs.price} for obs in closes]


def history_rows(result: ResearchResult) -> list[dict[str, object]]:
    return close_rows(result.observations)


def percent_change(rows: list[dict[str, object]]) -> float | None:
    if len(rows) < 2 or not rows[0]["price"]:
        return None
    return (rows[-1]["price"] - rows[0]["price"]) / rows[0]["price"] * 100  # type: ignore[operator]
