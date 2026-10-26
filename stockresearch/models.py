from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class ResearchTask(StrEnum):
    QUOTE = "quote"
    HISTORY = "history"
    PROFILE = "profile"
    NEWS = "news"


class Freshness(StrEnum):
    LIVE = "live"
    DELAYED = "delayed"
    HISTORICAL = "historical"
    SIMULATED = "simulated"


class Intent(BaseModel):
    ticker_or_company: str | None = None
    tasks: list[ResearchTask] = Field(default_factory=list)
    start_date: date | None = None
    end_date: date | None = None
    save_report: bool = False
    notify: bool = False
    unsupported_financial_advice: bool = False


class Security(BaseModel):
    ticker: str
    exchange: str
    company_name: str
    currency: str = Field(min_length=3, max_length=3)


class MarketObservation(BaseModel):
    ticker: str
    exchange: str
    currency: str
    observed_at: datetime
    price: float = Field(ge=0)
    observation_type: Literal["quote", "daily_close"]
    freshness: Freshness
    source: str
    source_url: str | None = None


class CompanyProfile(BaseModel):
    ticker: str
    company_name: str
    exchange: str
    currency: str
    sector: str
    description: str
    as_of: date
    source: str


class NewsArticle(BaseModel):
    ticker: str
    title: str
    publisher: str
    published_at: datetime
    url: str
    source: str


class ResearchResult(BaseModel):
    answer: str
    intent: Intent
    security: Security | None = None
    observations: list[MarketObservation] = Field(default_factory=list)
    profile: CompanyProfile | None = None
    articles: list[NewsArticle] = Field(default_factory=list)
    clarification: str | None = None
    candidates: list[Security] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    report_path: str | None = None
    notification_status: str | None = None
