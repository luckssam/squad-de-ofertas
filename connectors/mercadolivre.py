"""Conector do Mercado Livre.

Estrategia padrao: como a API oficial de busca esta bloqueada para apps de
terceiros (HTTP 403), usamos o site publico atraves de um navegador real
(`connectors/meli_browser.py`). Isso nao custa nada e nao usa cota do SerpAPI.

Se o app for certificado no devcenter, defina MELI_USE_API=true no .env para
voltar a usar a API oficial.
"""
from __future__ import annotations

import logging
import re

import httpx

from connectors.base import Connector, ConnectorError, build_terms
from connectors.meli_browser import MeliBrowser, MeliWebError, slugify
from connectors.meli_oauth import MeliTokenManager, create_token_manager
from core.config import Settings
from core.models import Intent, Offer
from core.utils import safe_url

logger = logging.getLogger("squad.meli")


def _parse_rating(text: str) -> float | None:
    match = re.search(r"(\d+[.,]?\d*)", text or "")
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def _parse_reviews(text: str) -> int | None:
    digits = re.sub(r"\D", "", text or "")
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


class MercadoLivreConnector(Connector):
    id = "mercadolivre"
    label = "Mercado Livre"
    experimental = False

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._token_manager: MeliTokenManager | None = None
        self._browser: MeliBrowser | None = None

    @property
    def _token_mgr(self) -> MeliTokenManager:
        if self._token_manager is None:
            self._token_manager = create_token_manager(self.settings)
        return self._token_manager

    @property
    def _web(self) -> MeliBrowser:
        if self._browser is None:
            self._browser = MeliBrowser(self.settings)
        return self._browser

    @property
    def configured(self) -> bool:
        if self.settings.meli_web_enabled:
            return True
        return bool(self.settings.meli_access_token) or self._token_mgr.has_refresh_token()

    @property
    def setup_hint(self) -> str:
        if self.settings.meli_web_enabled:
            return "Busca pelo site do Mercado Livre via navegador (sem custo)."
        if self.settings.meli_access_token:
            return "Usando MELI_ACCESS_TOKEN do .env (modo estatico)."
        if self.settings.meli_client_id and self.settings.meli_client_secret:
            return "OAuth configurado. Clique em 'Conectar Mercado Livre' para autorizar."
        return "Defina MELI_CLIENT_ID e MELI_CLIENT_SECRET no .env para usar OAuth."

    # ------------------------------------------------------------------ #
    # Busca
    # ------------------------------------------------------------------ #

    async def search(self, intent: Intent, limit: int) -> list[Offer]:
        if self.settings.meli_use_api:
            try:
                return await self._search_api(intent, limit)
            except ConnectorError as exc:
                if not getattr(exc, "restricted", False) or not self.settings.meli_web_enabled:
                    raise
                logger.info("API do Mercado Livre bloqueada; usando o navegador.")

        if not self.settings.meli_web_enabled:
            raise ConnectorError(
                "Mercado Livre: busca desativada. Defina MELI_WEB_ENABLED=true "
                "ou MELI_USE_API=true no .env.",
                restricted=True,
            )

        return await self._search_web(intent, limit)

    async def _search_web(self, intent: Intent, limit: int) -> list[Offer]:
        terms = build_terms(intent)
        try:
            raw_offers = await self._web.search(
                terms,
                limit,
                price_min=intent.budget_min,
                price_max=intent.budget_max,
            )
        except MeliWebError as exc:
            raise ConnectorError(str(exc)) from exc
        except ImportError as exc:
            raise ConnectorError(
                "Navegador do Mercado Livre indisponivel: instale com "
                "'pip install playwright'. (" + exc.__class__.__name__ + ")"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(
                f"Falha ao consultar o site do Mercado Livre ({exc.__class__.__name__})."
            ) from exc

        offers: list[Offer] = []
        for item in raw_offers:
            shipping_text = (item.get("shipping") or "").lower()
            offers.append(
                Offer(
                    id=str(item["id"]),
                    source=self.id,
                    source_label=self.label,
                    title=item["title"],
                    price=float(item["price"]),
                    currency="BRL",
                    url=safe_url(item["url"]),
                    image=safe_url(item["image"]) if item.get("image") else None,
                    seller=item.get("seller"),
                    shipping_free=True if "gratis" in shipping_text or "grátis" in shipping_text else None,
                    installments=item.get("installments"),
                    rating=_parse_rating(item.get("rating", "")),
                    reviews=_parse_reviews(item.get("reviews", "")),
                )
            )
        return offers

    async def _search_api(self, intent: Intent, limit: int) -> list[Offer]:
        access_token = self._get_access_token()
        if not access_token:
            raise ConnectorError(self.setup_hint)

        params = {
            "q": build_terms(intent),
            "limit": min(max(limit, 4), 50),
            "condition": "new",
        }
        if intent.budget_min:
            params["price"] = f"{intent.budget_min}-{intent.budget_max or '*'}"
        elif intent.budget_max:
            params["price"] = f"*-{intent.budget_max}"

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "SquadOfertas/1.0",
        }
        url = "https://api.mercadolibre.com/sites/MLB/search"

        try:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout) as client:
                response = await client.get(url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise ConnectorError(f"Falha de rede ao falar com o Mercado Livre: {exc.__class__.__name__}") from exc

        if response.status_code == 403:
            raise ConnectorError(
                "Mercado Livre restringiu a busca para apps de terceiros. "
                "Solicite producao/certificacao no devcenter para liberar. "
                "O token OAuth esta valido.",
                restricted=True,
            )
        if response.status_code == 401:
            raise ConnectorError(
                "Mercado Livre recusou o token (401). Reconecte o OAuth ou gere "
                "um novo MELI_ACCESS_TOKEN."
            )
        if response.status_code == 429:
            raise ConnectorError("Mercado Livre limitou as requisicoes (429). Tente novamente em instantes.")
        if response.status_code >= 400:
            raise ConnectorError(f"Mercado Livre respondeu HTTP {response.status_code}.")

        try:
            data = response.json()
        except ValueError as exc:
            raise ConnectorError("Resposta invalida do Mercado Livre.") from exc

        offers: list[Offer] = []
        for item in data.get("results", [])[:limit]:
            price = item.get("price")
            if not price:
                continue
            shipping = item.get("shipping") or {}
            installments = item.get("installments") or {}
            seller = item.get("seller") or {}
            address = item.get("address") or {}
            thumbnail = item.get("thumbnail") or ""
            quantity = installments.get("quantity")
            amount = installments.get("amount")
            installment_text = None
            if quantity and amount:
                installment_text = f"em ate {quantity}x de R$ {amount:,.2f}".replace(
                    ",", "X"
                ).replace(".", ",").replace("X", ".")

            location = ", ".join(
                [part for part in [address.get("city_name"), address.get("state_name")] if part]
            ) or None

            offers.append(
                Offer(
                    id=str(item.get("id")),
                    source=self.id,
                    source_label=self.label,
                    title=item.get("title") or "Oferta sem titulo",
                    price=float(price),
                    currency=item.get("currency_id") or "BRL",
                    url=safe_url(item.get("permalink")),
                    image=safe_url(thumbnail) if thumbnail else None,
                    seller=seller.get("nickname"),
                    shipping_free=bool(shipping.get("free_shipping")),
                    installments=installment_text,
                    condition=item.get("condition"),
                    location=location,
                )
            )
        return offers

    def _get_access_token(self) -> str | None:
        if self.settings.meli_access_token:
            return self.settings.meli_access_token
        return self._token_mgr.get_valid_access_token()

    async def aclose(self) -> None:
        if self._browser is not None:
            await self._browser.aclose()
            self._browser = None
