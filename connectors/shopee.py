"""Conector da Shopee via Affiliate Open API (experimental).

A API de afiliados exige aprovação no programa. A assinatura usada é
SHA256(app_id + timestamp + payload + secret), conforme a documentação pública.
"""
from __future__ import annotations

import hashlib
import json
import time

import httpx

from connectors.base import Connector, ConnectorError, build_terms
from core.config import Settings
from core.models import Intent, Offer
from core.utils import parse_price, safe_url

QUERY = """
query ProductOffer($keyword: String!, $limit: Int!) {
  productOfferV2(keyword: $keyword, listType: 1, sortType: 2, page: 1, limit: $limit) {
    nodes {
      itemId
      productName
      price
      priceMin
      priceMax
      imageUrl
      offerLink
      productLink
      shopName
      sales
      ratingStar
      commissionRate
    }
  }
}
"""


class ShopeeConnector(Connector):
    id = "shopee"
    label = "Shopee"
    experimental = True

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return self.settings.shopee_configured

    @property
    def setup_hint(self) -> str:
        return "Defina SHOPEE_APP_ID e SHOPEE_SECRET (programa de afiliados Shopee)."

    async def search(self, intent: Intent, limit: int) -> list[Offer]:
        if not self.configured:
            raise ConnectorError(self.setup_hint)

        payload = json.dumps(
            {"query": QUERY, "variables": {"keyword": build_terms(intent), "limit": min(limit, 30)}},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        timestamp = str(int(time.time()))
        base = f"{self.settings.shopee_app_id}{timestamp}{payload}{self.settings.shopee_secret}"
        signature = hashlib.sha256(base.encode("utf-8")).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "Authorization": (
                f"SHA256 Credential={self.settings.shopee_app_id}, "
                f"Timestamp={timestamp}, Signature={signature}"
            ),
        }

        try:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout) as client:
                response = await client.post(
                    "https://open-api.affiliate.shopee.com.br/graphql",
                    headers=headers,
                    content=payload.encode("utf-8"),
                )
        except httpx.HTTPError as exc:
            raise ConnectorError(f"Falha de rede na Shopee: {exc.__class__.__name__}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise ConnectorError("Resposta inválida da Shopee.") from exc

        if response.status_code >= 400:
            detail = data.get("message") or data.get("error") or f"HTTP {response.status_code}"
            raise ConnectorError(f"Shopee: {detail}")

        if data.get("errors"):
            raise ConnectorError(f"Shopee: {data['errors'][0].get('message', 'erro na consulta')}")

        nodes = (((data.get("data") or {}).get("productOfferV2") or {}).get("nodes")) or []
        offers: list[Offer] = []
        for node in nodes:
            price = parse_price(node.get("price")) or parse_price(node.get("priceMin"))
            if not price:
                continue
            link = node.get("offerLink") or node.get("productLink")
            rating = node.get("ratingStar")
            sales = node.get("sales")
            try:
                rating_value = float(rating) if rating is not None else None
            except (TypeError, ValueError):
                rating_value = None
            try:
                reviews_value = int(sales) if sales is not None else None
            except (TypeError, ValueError):
                reviews_value = None

            offers.append(
                Offer(
                    id=f"shopee-{node.get('itemId')}",
                    source=self.id,
                    source_label=self.label,
                    title=node.get("productName") or "Oferta sem título",
                    price=price,
                    currency="BRL",
                    url=safe_url(link),
                    image=safe_url(node.get("imageUrl")),
                    rating=rating_value,
                    reviews=reviews_value,
                    seller=node.get("shopName"),
                    shipping_free=None,
                    condition="novo",
                )
            )
        return offers[:limit]
