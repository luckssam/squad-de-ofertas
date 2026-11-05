"""Contrato base dos conectores de ofertas."""
from __future__ import annotations

from abc import ABC, abstractmethod

from core.models import Intent, Offer


class ConnectorError(Exception):
    """Erro amigável exibido na tela sem derrubar o squad."""


def build_terms(intent: Intent) -> str:
    """Monta o termo de busca a partir do produto + especificações."""
    parts: list[str] = []
    product = (intent.product or intent.raw_query).strip()
    if product:
        parts.append(product)
    lowered = product.lower()
    for spec in intent.specs[:4]:
        if spec and spec.lower() not in lowered:
            parts.append(spec)
    for item in intent.must_have[:2]:
        if item and item.lower() not in " ".join(parts).lower():
            parts.append(item)
    return " ".join(parts)[:180]


class Connector(ABC):
    id: str = "base"
    label: str = "Conector"
    experimental: bool = False

    @property
    @abstractmethod
    def configured(self) -> bool:
        """True quando as credenciais necessárias existem."""

    @property
    def setup_hint(self) -> str:
        return ""

    @abstractmethod
    async def search(self, intent: Intent, limit: int) -> list[Offer]:
        """Retorna ofertas normalizadas. Pode lançar ConnectorError."""
