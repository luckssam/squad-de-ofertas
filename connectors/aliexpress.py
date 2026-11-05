"""Conector do AliExpress via Affiliate API (experimental).

Requer chaves do programa de afiliados AliExpress. A assinatura segue o padrão
do Open Platform (SHA256 sobre os parâmetros ordenados + app secret).
"""
from __future__ import annotations

import hashlib
import os
import time

import httpx

from connectors.base import Connector, ConnectorError, build_terms
from core.config import Settings
from core.models import Intent, Offer
from core.utils import parse_price, safe_url

ENDPOINT = os.environ.get(
    "ALIEXPRESS_ENDPOINT", "https://api-seller.aliexpress.com/openapi/router/rest"
)


class AliExpressConnector(Connector):
    id = "aliexpress"
    label = "AliExpress"
    experimental = True

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return self.settings.aliexpress_configured

    @property
    def setup_hint(self) -> str:
        return (
            "Defina ALIEXPRESS_APP_KEY, ALIEXPRESS_SECRET e ALIEXPRESS_TRACKING_ID "
            "(programa de afiliados AliExpress)."
        )

    async def search(self, intent: Intent, limit: int) -> list[Offer]:
        if not self.configured:
            raise ConnectorError(self.setup_hint)

        params: dict[str, str] = {
            "app_key": self.settings.aliexpress_app_key,
            "method": "aliexpress.affiliate.product.query",
            "timestamp": str(int(time.time() * 1000)),
            "sign_method": "sha256",
            "format": "json",
            "v": "2.0",
            "simplified": "true",
            "keywords": build_terms(intent),
            "page_no": "1",
            "page_size": str(min(max(limit, 1), 50)),
            "target_currency": "BRL",
            "target_language": "PT",
            "ship_to_country": "BR",
            "tracking_id": self.settings.aliexpress_tracking_id,
        }
        sign_base = "".join(f"{key}{params[key]}" for key in sorted(params))
        signature = hashlib.sha256(
            f"{self.settings.aliexpress_secret}{sign_base}{self.settings.aliexpress_secret}".encode("utf-8")
        ).hexdigest().upper()
        params["sign"] = signature

        try:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout) as client:
                response = await client.get(ENDPOINT, params=params)
        except httpx.HTTPError as exc:
            raise ConnectorError(f"Falha de rede no AliExpress: {exc.__class__.__name__}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise ConnectorError("Resposta inválida do AliExpress.") from exc

        if response.status_code >= 400:
            raise ConnectorError(f"AliExpress respondeu HTTP {response.status_code}.")

        error_response = data.get("error_response") or {}
        if error_response:
            message = error_response.get("msg") or error_response.get("sub_msg") or "erro na consulta"
            raise ConnectorError(f"AliExpress: {message}")

        root = data.get("aliexpress_affiliate_product_query_response") or {}
        result = ((root.get("resp_result") or {}).get("result")) or {}
        products = ((result.get("products") or {}).get("product")) or []
        if isinstance(products, dict):
            products = [products]

        offers: list[Offer] = []
        for product in products:
            price = parse_price(product.get("target_sale_price"))
            if not price:
                continue
            rating = product.get("evaluate_rate")
            sales = product.get("lastest_volume")
            try:
                rating_value = float(str(rating).replace("%", "")) / 20 if rating else None
            except ValueError:
                rating_value = None
            try:
                reviews_value = int(sales) if sales is not None else None
            except (TypeError, ValueError):
                reviews_value = None

            offers.append(
                Offer(
                    id=f"aliexpress-{product.get('product_id')}",
                    source=self.id,
                    source_label=self.label,
                    title=product.get("product_title") or "Oferta sem título",
                    price=price,
                    currency="BRL",
                    url=safe_url(product.get("promotion_link")),
                    image=safe_url(product.get("product_main_image_url")),
                    rating=rating_value,
                    reviews=reviews_value,
                    seller=product.get("shop_url"),
                    shipping_free=None,
                    condition="novo",
                )
            )
        return offers[:limit]
