"""Registro de conectores disponíveis."""
from __future__ import annotations

from connectors.aliexpress import AliExpressConnector
from connectors.amazon_web import AmazonConnector
from connectors.base import Connector
from connectors.bing_shopping import ShoppingConnector
from connectors.demo import DemoConnector
from connectors.mercadolivre import MercadoLivreConnector
from connectors.shopee import ShopeeConnector
from core.config import Settings


def build_connectors(settings: Settings) -> list[Connector]:
    return [
        DemoConnector(),
        MercadoLivreConnector(settings),
        AmazonConnector(settings),
        ShoppingConnector(settings),
        ShopeeConnector(settings),
        AliExpressConnector(settings),
    ]
