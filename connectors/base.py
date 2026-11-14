"""Contrato base dos conectores de ofertas."""
from __future__ import annotations

from abc import ABC, abstractmethod

from core.attributes import clean_spec
from core.models import Intent, Offer
from core.utils import compact


class ConnectorError(Exception):
    """Erro amigável exibido na tela sem derrubar o squad.

    Use ``restricted=True`` quando a fonte está configurada mas o acesso foi
    limitado por política do provedor (não é falha de credencial nem bug).
    """

    def __init__(self, message: str, restricted: bool = False) -> None:
        super().__init__(message)
        self.restricted = restricted


def build_terms(intent: Intent) -> str:
    """Monta o termo de busca a partir do produto + especificações.

    Especificações já contidas no produto (ex.: "dourado" em "PLA Silk Dourado")
    não são repetidas, e rótulos como "cor:" / "material" são removidos para
    não poluir a consulta enviada às lojas.
    """
    parts: list[str] = []
    product = clean_spec(intent.product or intent.raw_query)
    if product:
        parts.append(product)

    covered = compact(" ".join(parts))
    for raw in [*intent.specs, *intent.must_have]:
        spec = clean_spec(raw)
        key = compact(spec)
        if not key or key in covered:
            continue
        parts.append(spec)
        covered += key

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
