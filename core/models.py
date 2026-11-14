"""Modelos de dados compartilhados entre API, agentes e conectores."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    budget_min: float | None = Field(default=None, ge=0)
    budget_max: float | None = Field(default=None, ge=0)
    sources: list[str] | None = None
    limit: int = Field(default=24, ge=4, le=60)
    sort: Literal["score", "price_asc", "price_desc", "rating"] = "score"

    @field_validator("query")
    @classmethod
    def _clean_query(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 2:
            raise ValueError("Descreva o produto com pelo menos 2 caracteres.")
        return cleaned

    @field_validator("budget_max")
    @classmethod
    def _check_budget(cls, value: float | None) -> float | None:
        return value


class Intent(BaseModel):
    raw_query: str
    product: str
    keywords: list[str] = Field(default_factory=list)
    specs: list[str] = Field(default_factory=list)
    category: str | None = None
    budget_min: float | None = None
    budget_max: float | None = None
    must_have: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    currency: str = "BRL"
    source: Literal["heuristic", "llm"] = "heuristic"
    notes: str | None = None


class Offer(BaseModel):
    id: str
    source: str
    source_label: str
    title: str
    price: float
    currency: str = "BRL"
    url: str
    image: str | None = None
    rating: float | None = None
    reviews: int | None = None
    seller: str | None = None
    shipping_free: bool | None = None
    installments: str | None = None
    condition: str | None = None
    location: str | None = None
    matched_specs: list[str] = Field(default_factory=list)
    missing_specs: list[str] = Field(default_factory=list)
    score: float = 0
    price_vs_median: float | None = None
    over_budget: bool = False
    badges: list[str] = Field(default_factory=list)
    is_demo: bool = False
    affiliate_url: str | None = None

    @property
    def display_price(self) -> str:
        return f"R$ {self.price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class SourceStatus(BaseModel):
    id: str
    label: str
    status: Literal["ok", "error", "disabled", "skipped", "restricted"]
    count: int = 0
    message: str | None = None
    ms: int = 0


class Stats(BaseModel):
    count: int = 0
    min_price: float | None = None
    median_price: float | None = None
    max_price: float | None = None
    free_shipping_count: int = 0
    currency: str = "BRL"


class Analysis(BaseModel):
    headline: str
    summary: str
    best_pick_id: str | None = None
    cheapest_id: str | None = None
    best_rated_id: str | None = None
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    tips: list[str] = Field(default_factory=list)
    warning: str | None = None
    ai: bool = False
    stats: Stats = Field(default_factory=Stats)


class TraceEvent(BaseModel):
    agent: str
    label: str
    status: Literal["running", "ok", "warning", "error"]
    message: str = ""
    ms: int = 0


class SearchResult(BaseModel):
    intent: Intent
    offers: list[Offer]
    sources: list[SourceStatus]
    analysis: Analysis
    trace: list[TraceEvent]
    elapsed_ms: int
    mode: Literal["demo", "real", "hybrid"]
    demoted_budget: int = 0
    total_found: int = 0
