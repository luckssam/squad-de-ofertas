"""Conector da Amazon via Product Advertising API 5.0 (SigV4)."""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json

import httpx

from connectors.base import Connector, ConnectorError, build_terms
from core.config import Settings
from core.models import Intent, Offer
from core.utils import safe_url


def _sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


class AmazonConnector(Connector):
    id = "amazon"
    label = "Amazon"
    experimental = False

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return self.settings.amazon_configured

    @property
    def setup_hint(self) -> str:
        return (
            "Defina AMAZON_ACCESS_KEY, AMAZON_SECRET_KEY e AMAZON_PARTNER_TAG "
            "(credenciais do Amazon Associates / PA-API)."
        )

    async def search(self, intent: Intent, limit: int) -> list[Offer]:
        if not self.configured:
            raise ConnectorError(self.setup_hint)

        settings = self.settings
        host = settings.amazon_host
        region = settings.amazon_region
        service = "ProductAdvertisingAPI"
        target = "com.amazon.paapi5.v1.ProductAdvertisingAPIv1.SearchItems"
        path = "/paapi5/searchitems"

        payload = {
            "Keywords": build_terms(intent),
            "SearchIndex": "All",
            "ItemCount": min(max(limit, 1), 10),
            "PartnerTag": settings.amazon_partner_tag,
            "PartnerType": "Associates",
            "Marketplace": "www.amazon.com.br",
            "Resources": [
                "ItemInfo.Title",
                "ItemInfo.ByLineInfo",
                "Images.Primary.Large",
                "Offers.Listings.Price",
                "Offers.Listings.DeliveryInfo.IsFreeShippingEligible",
                "Offers.Listings.MerchantInfo",
                "Offers.Listings.Condition",
                "CustomerReviews.Count",
                "CustomerReviews.StarRating",
            ],
        }
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

        now = dt.datetime.now(dt.timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")

        headers = {
            "content-encoding": "amz-1.0",
            "content-type": "application/json; charset=utf-8",
            "host": host,
            "x-amz-date": amz_date,
            "x-amz-target": target,
        }
        sorted_headers = sorted(headers)
        canonical_headers = "".join(f"{key}:{headers[key]}\n" for key in sorted_headers)
        signed_headers = ";".join(sorted_headers)
        payload_hash = hashlib.sha256(body).hexdigest()
        canonical_request = "\n".join(
            ["POST", path, "", canonical_headers, signed_headers, payload_hash]
        )
        credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        signing_key = _sign(("AWS4" + settings.amazon_secret_key).encode("utf-8"), date_stamp)
        signing_key = _sign(signing_key, region)
        signing_key = _sign(signing_key, service)
        signing_key = _sign(signing_key, "aws4_request")
        signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        headers["Authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={settings.amazon_access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )

        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
                response = await client.post(
                    f"https://{host}{path}", headers=headers, content=body
                )
        except httpx.HTTPError as exc:
            raise ConnectorError(f"Falha de rede na Amazon: {exc.__class__.__name__}") from exc

        try:
            data = response.json()
        except ValueError:
            data = {}

        if response.status_code == 401:
            raise ConnectorError("Amazon recusou as credenciais (401). Confira as chaves da PA-API.")
        if response.status_code == 429:
            raise ConnectorError("Amazon limitou as requisições (429). Tente novamente em instantes.")
        if response.status_code >= 400:
            errors = data.get("Errors") or []
            detail = errors[0].get("Message") if errors else f"HTTP {response.status_code}"
            raise ConnectorError(f"Amazon: {detail}")

        if data.get("Errors"):
            message = data["Errors"][0].get("Message", "erro desconhecido")
            raise ConnectorError(f"Amazon: {message}")

        items = (data.get("SearchResult") or {}).get("Items") or []
        offers: list[Offer] = []
        for item in items:
            asin = item.get("ASIN")
            listings = (item.get("Offers") or {}).get("Listings") or []
            if not asin or not listings:
                continue
            listing = listings[0]
            price = ((listing.get("Price") or {}).get("Amount"))
            if not price:
                continue
            info = item.get("ItemInfo") or {}
            title = ((info.get("Title") or {}).get("DisplayValue")) or "Oferta sem título"
            image = (((item.get("Images") or {}).get("Primary") or {}).get("Large") or {}).get("URL")
            reviews_block = item.get("CustomerReviews") or {}
            rating = ((reviews_block.get("StarRating") or {}).get("Value"))
            reviews = reviews_block.get("Count")
            merchant = (listing.get("MerchantInfo") or {}).get("Name")
            shipping_free = (listing.get("DeliveryInfo") or {}).get("IsFreeShippingEligible")
            condition = (listing.get("Condition") or {}).get("Value")

            offers.append(
                Offer(
                    id=f"amazon-{asin}",
                    source=self.id,
                    source_label=self.label,
                    title=title,
                    price=float(price),
                    currency="BRL",
                    url=safe_url(item.get("DetailPageURL")),
                    image=safe_url(image),
                    rating=float(rating) if rating is not None else None,
                    reviews=int(reviews) if reviews is not None else None,
                    seller=merchant,
                    shipping_free=shipping_free if isinstance(shipping_free, bool) else None,
                    condition=condition,
                )
            )
        return offers[:limit]
