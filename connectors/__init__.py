"""Registro de conectores disponíveis."""
from __future__ import annotations

from connectors.aliexpress import AliExpressConnector
from connectors.amazon_serpapi import AmazonSerpApiConnector
from connectors.base import Connector
from connectors.demo import DemoConnector
from connectors.google_shopping import GoogleShoppingConnector
from connectors.mercadolivre import MercadoLivreConnector
from connectors.shopee import ShopeeConnector
from core.config import Settings


def build_connectors(settings: Settings) -> list[Connector]:
    return [
        DemoConnector(),
        MercadoLivreConnector(settings),
        AmazonSerpApiConnector(settings),
        GoogleShoppingConnector(settings),
        ShopeeConnector(settings),
        AliExpressConnector(settings),
    ]
