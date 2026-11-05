"""Conector do Mercado Livre (API oficial de busca)."""
from __future__ import annotations

import httpx

from connectors.base import Connector, ConnectorError, build_terms
from connectors.meli_oauth import MeliTokenManager, create_token_manager
from core.config import Settings
from core.models import Intent, Offer
from core.utils import safe_url


class MercadoLivreConnector(Connector):
    id = "mercadolivre"
    label = "Mercado Livre"
    experimental = False

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._token_manager: MeliTokenManager | None = None

    @property
    def _token_mgr(self) -> MeliTokenManager:
        if self._token_manager is None:
            self._token_manager = create_token_manager(self.settings)
        return self._token_manager

    @property
    def configured(self) -> bool:
        # Configurado se tem OAuth OU token estático no .env
        return bool(self.settings.meli_access_token) or self._token_mgr.has_refresh_token()

    @property
    def setup_hint(self) -> str:
        if self.settings.meli_access_token:
            return "Usando MELI_ACCESS_TOKEN do .env (modo estático)."
        if self.settings.meli_client_id and self.settings.meli_client_secret:
            return "OAuth configurado. Clique em 'Conectar Mercado Livre' para autorizar."
        return "Defina MELI_CLIENT_ID e MELI_CLIENT_SECRET no .env para usar OAuth."

    def _get_access_token(self) -> str | None:
        # Prioriza token estático do .env (compatibilidade)
        if self.settings.meli_access_token:
            return self.settings.meli_access_token
        # Caso contrário, usa OAuth com refresh automático
        return self._token_mgr.get_valid_access_token()

    async def search(self, intent: Intent, limit: int) -> list[Offer]:
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

        if response.status_code in (401, 403):
            # Se usando OAuth, o token manager já tenta refresh automaticamente
            # Se chegou aqui, é porque falhou mesmo após refresh ou token estático inválido
            raise ConnectorError(
                "Mercado Livre recusou a requisição (401/403). "
                "Se estiver usando OAuth, tente reconectar. "
                "Se estiver usando token estático, gere um novo MELI_ACCESS_TOKEN."
            )
        if response.status_code == 429:
            raise ConnectorError("Mercado Livre limitou as requisições (429). Tente novamente em instantes.")
        if response.status_code >= 400:
            raise ConnectorError(f"Mercado Livre respondeu HTTP {response.status_code}.")

        try:
            data = response.json()
        except ValueError as exc:
            raise ConnectorError("Resposta inválida do Mercado Livre.") from exc

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
                installment_text = f"em até {quantity}x de R$ {amount:,.2f}".replace(
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
                    title=item.get("title") or "Oferta sem título",
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
