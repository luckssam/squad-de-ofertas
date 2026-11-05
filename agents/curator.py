"""Agente de Curadoria: normaliza, deduplica, filtra e pontua ofertas."""
from __future__ import annotations

import math
import re
import statistics
from difflib import SequenceMatcher

from core.models import Intent, Offer, SearchRequest
from core.utils import clamp, compact, normalize_specs, normalize_text, token_set, tokens

TRUST = {
    "amazon": 92.0,
    "mercadolivre": 84.0,
    "google_shopping": 76.0,
    "shopee": 70.0,
    "aliexpress": 58.0,
    "demo": 45.0,
}

STOP_DEDUPE = {"novo", "original", "lacrado", "frete", "gratis", "promocao", "oferta", "kit"}


def _title_key(title: str) -> str:
    return normalize_text(title)


def _quality(offer: Offer) -> float:
    rating = offer.rating or 3.9
    reviews = offer.reviews or 0
    return rating * math.log10(reviews + 2) / max(offer.price, 1) ** 0.25


def _is_duplicate(a: str, b: str) -> bool:
    set_a = token_set(a) - STOP_DEDUPE
    set_b = token_set(b) - STOP_DEDUPE
    if not set_a or not set_b:
        return False
    overlap = len(set_a & set_b) / len(set_a | set_b)
    if overlap >= 0.78:
        return True
    if abs(len(a) - len(b)) < max(len(a), len(b)) * 0.35:
        return SequenceMatcher(None, a, b).ratio() >= 0.9
    return False


def _spec_present(spec: str, title: str) -> bool:
    spec_compact = compact(spec)
    title_compact = compact(title)
    if spec_compact and spec_compact in title_compact:
        return True
    spec_tokens = [token for token in tokens(spec) if len(token) >= 2 or token.isdigit()]
    if not spec_tokens:
        return False
    hits = sum(1 for token in spec_tokens if compact(token) in title_compact)
    return hits / len(spec_tokens) >= 0.6


def _apply_specs(offer: Offer, specs: list[str]) -> None:
    matched = [spec for spec in specs if _spec_present(spec, offer.title)]
    offer.matched_specs = matched
    offer.missing_specs = [spec for spec in specs if spec not in matched]


def _score(offer: Offer, cheapest: float, specs_total: int) -> float:
    price_component = clamp(100.0 * cheapest / max(offer.price, 0.01))
    rating_component = clamp(((offer.rating - 3.5) / 1.5) * 100) if offer.rating else 55.0
    reviews_component = (
        clamp((math.log10(offer.reviews + 1) / 3.7) * 100) if offer.reviews else 0.0
    )
    if offer.shipping_free is True:
        shipping_component = 100.0
    elif offer.shipping_free is False:
        shipping_component = 45.0
    else:
        shipping_component = 55.0
    trust_component = TRUST.get(offer.source, 65.0)
    spec_component = (
        100.0 * len(offer.matched_specs) / specs_total if specs_total else 60.0
    )
    return round(
        0.34 * price_component
        + 0.20 * rating_component
        + 0.08 * reviews_component
        + 0.10 * shipping_component
        + 0.13 * trust_component
        + 0.15 * spec_component,
        1,
    )


def _sort_offers(offers: list[Offer], sort: str) -> list[Offer]:
    if sort == "price_asc":
        return sorted(offers, key=lambda offer: offer.price)
    if sort == "price_desc":
        return sorted(offers, key=lambda offer: offer.price, reverse=True)
    if sort == "rating":
        return sorted(
            offers,
            key=lambda offer: (offer.rating is None, -(offer.rating or 0), -(offer.reviews or 0)),
        )
    return sorted(offers, key=lambda offer: offer.score, reverse=True)


def _add_badge(offer: Offer, badge: str) -> None:
    if badge not in offer.badges and len(offer.badges) < 3:
        offer.badges.append(badge)


def curate(
    offers: list[Offer], intent: Intent, request: SearchRequest
) -> tuple[list[Offer], dict]:
    total = len(offers)
    cleaned: list[Offer] = []
    for offer in offers:
        if not offer.title or offer.price <= 0:
            continue
        offer.title = re.sub(r"\s+", " ", offer.title).strip()
        cleaned.append(offer)

    # 1. deduplicação por similaridade de título
    ranked = sorted(cleaned, key=_quality, reverse=True)
    unique: list[Offer] = []
    keys: list[str] = []
    for offer in ranked:
        key = _title_key(offer.title)
        if any(_is_duplicate(key, existing) for existing in keys):
            continue
        unique.append(offer)
        keys.append(key)
    duplicates_removed = len(cleaned) - len(unique)

    # 2. exclusões ("sem X")
    excluded = 0
    if intent.exclude:
        kept: list[Offer] = []
        for offer in unique:
            title = normalize_text(offer.title)
            if any(normalize_text(term) in title for term in intent.exclude if len(term) > 1):
                excluded += 1
                continue
            kept.append(offer)
        unique = kept

    # 3. orçamento (com fallback para "quase deu")
    specs = normalize_specs(intent.specs + intent.must_have)
    eligible: list[Offer] = []
    over_budget: list[Offer] = []
    below_budget = 0
    for offer in unique:
        _apply_specs(offer, specs)
        if intent.budget_min is not None and offer.price < intent.budget_min:
            below_budget += 1
            continue
        if intent.budget_max is not None and offer.price > intent.budget_max:
            over_budget.append(offer)
            continue
        eligible.append(offer)

    relaxed = False
    if not eligible and over_budget:
        relaxed = True
        eligible = sorted(over_budget, key=lambda offer: offer.price)[:6]
        for offer in eligible:
            offer.over_budget = True

    # 4. pontuação
    prices = [offer.price for offer in eligible]
    median = statistics.median(prices) if prices else 0.0
    cheapest = min(prices) if prices else 0.0
    for offer in eligible:
        offer.score = _score(offer, cheapest, len(specs))
        if median:
            offer.price_vs_median = round((offer.price / median - 1) * 100, 1)

    ordered = _sort_offers(eligible, request.sort)
    result = ordered[: request.limit]

    # 5. selos
    if result:
        best_value = max(result, key=lambda offer: offer.score)
        cheapest_offer = min(result, key=lambda offer: offer.price)
        rated = [offer for offer in result if offer.rating and (offer.reviews or 0) >= 30]
        best_rated = max(rated, key=lambda offer: (offer.rating or 0, offer.reviews or 0)) if rated else None
        for offer in result:
            if offer.over_budget:
                _add_badge(offer, "Acima do orçamento")
            if offer.id == cheapest_offer.id:
                _add_badge(offer, "Menor preço")
            if offer.id == best_value.id:
                _add_badge(offer, "Melhor custo-benefício")
            if best_rated and offer.id == best_rated.id:
                _add_badge(offer, "Melhor avaliado")
            if offer.shipping_free:
                _add_badge(offer, "Frete grátis")
            if offer.reviews is not None and offer.reviews < 10:
                _add_badge(offer, "Poucas avaliações")
            if specs and not offer.missing_specs:
                _add_badge(offer, "Specs completas")

    meta = {
        "total_received": total,
        "duplicates_removed": duplicates_removed,
        "excluded": excluded,
        "below_budget": below_budget,
        "over_budget": len(over_budget),
        "relaxed": relaxed,
        "median": round(median, 2) if median else None,
        "cheapest": round(cheapest, 2) if cheapest else None,
    }
    return result, meta
