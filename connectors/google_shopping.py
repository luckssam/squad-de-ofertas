"""Conector do Google Shopping via SerpAPI."""
from __future__ import annotations

import httpx

from connectors.base import Connector, ConnectorError, build_terms
from core.config import Settings
from core.models import Intent, Offer
from core.utils import parse_price, safe_url, short_hash


class GoogleShoppingConnector(Connector):
    id = "google_shopping"
    label = "Google Shopping"
    experimental = False

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.serpapi_key)

    @property
    def setup_hint(self) -> str:
        return "Defina SERPAPI_KEY no .env (serpapi.com) para consultar o Google Shopping."

    async def search(self, intent: Intent, limit: int) -> list[Offer]:
        if not self.configured:
            raise ConnectorError(self.setup_hint)

        params = {
            "engine": "google_shopping",
            "q": build_terms(intent),
            "gl": "br",
            "hl": "pt-br",
            "num": min(max(limit, 10), 40),
            "api_key": self.settings.serpapi_key,
        }
        if intent.budget_max:
            params["max_price"] = int(intent.budget_max)
        if intent.budget_min:
            params["min_price"] = int(intent.budget_min)

        try:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout) as client:
                response = await client.get("https://serpapi.com/search.json", params=params)
        except httpx.HTTPError as exc:
            raise ConnectorError(f"Falha de rede no SerpAPI: {exc.__class__.__name__}") from exc

        if response.status_code == 401:
            raise ConnectorError("SerpAPI recusou a chave (401). Confira SERPAPI_KEY.")
        if response.status_code == 429:
            raise ConnectorError("SerpAPI atingiu o limite de consultas (429).")
        if response.status_code >= 400:
            raise ConnectorError(f"SerpAPI respondeu HTTP {response.status_code}.")

        data = response.json()
        if data.get("error"):
            raise ConnectorError(f"SerpAPI: {data['error']}")

        results = data.get("shopping_results") or data.get("inline_shopping_results") or []
        offers: list[Offer] = []
        for item in results:
            price = parse_price(item.get("extracted_price") or item.get("price"))
            if not price:
                continue
            link = item.get("link") or item.get("product_link") or ""
            if link.startswith("/"):
                link = f"https://www.google.com{link}"
            title = item.get("title") or "Oferta sem título"
            source_name = item.get("source") or "Google Shopping"
            delivery = (item.get("delivery") or "").lower()
            shipping_free = True if ("grátis" in delivery or "gratis" in delivery or "free" in delivery) else None
            rating = item.get("rating")
            reviews = item.get("reviews")
            try:
                rating_value = float(str(rating).replace(",", ".")) if rating is not None else None
            except ValueError:
                rating_value = None
            try:
                reviews_value = int(str(reviews).replace(".", "").replace(",", "")) if reviews is not None else None
            except ValueError:
                reviews_value = None

            offers.append(
                Offer(
                    id=f"gshopping-{short_hash(title + str(price) + source_name, 10)}",
                    source=self.id,
                    source_label=self.label,
                    title=title,
                    price=price,
                    currency="BRL",
                    url=safe_url(link),
                    image=safe_url(item.get("thumbnail")),
                    rating=rating_value,
                    reviews=reviews_value,
                    seller=source_name,
                    shipping_free=shipping_free,
                    condition="novo",
                    location=None,
                )
            )
        return offers[:limit]
