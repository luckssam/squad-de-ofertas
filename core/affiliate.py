"""Geração de links de afiliado para múltiplas plataformas.

Suporta: Mercado Livre, Amazon, Shopee, AliExpress.
Plataformas sem afiliado (ex: Google Shopping via SerpAPI) retornam a URL original.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

import httpx

from core.config import Settings
from core.models import Offer


def _add_query_param(url: str, key: str, value: str) -> str:
    """Adiciona ou substitui um parâmetro de query na URL."""
    return _add_query_params(url, {key: value})


def _add_query_params(url: str, params: dict[str, str]) -> str:
    """Adiciona ou substitui vários parâmetros de query na URL."""
    if not url:
        return url
    parsed = urlparse(url)
    qs = dict(parse_qsl(parsed.query, keep_blank_values=True))
    qs.update({key: value for key, value in params.items() if value})
    new_query = urlencode(qs)
    return urlunparse(parsed._replace(query=new_query))


def _meli_params(settings: Settings) -> dict[str, str]:
    """Identificação do Mercado Livre Afiliados (matt_word + matt_tool).

    Os dois são necessários: sem o matt_tool o Mercado Livre não atribui a
    comissão. Sem os dois, devolvemos vazio e o link fica o original.
    """
    tag = settings.ml_affiliate_tag
    tool = settings.ml_affiliate_tool
    if not tag or not tool:
        return {}
    return {"matt_word": tag, "matt_tool": tool}


def _build_affiliate_url(source: str, url: str, settings: Settings) -> str | None:
    """Gera o link de afiliado com base na fonte da oferta.

    Retorna a URL original quando não há credenciais ou não há programa de afiliado.
    """
    if not url:
        return None

    # --- Mercado Livre: matt_word + matt_tool (Afiliados e Criadores) ---
    if source == "mercadolivre":
        params = _meli_params(settings)
        if params:
            return _add_query_params(url, params)
        return url

    # --- Amazon Associates: parâmetro tag na URL ---
    if source == "amazon":
        tag = settings.amazon_associate_tag
        if tag:
            return _add_query_param(url, "tag", tag)
        return url

    # --- Shopee: API de short link de afiliado ---
    if source == "shopee":
        app_id = settings.shopee_app_id
        secret = settings.shopee_secret
        if app_id and secret:
            try:
                timestamp = int(time.time())
                base_string = f"{app_id}{timestamp}{url}"
                sign = hmac.new(
                    secret.encode("utf-8"),
                    base_string.encode("utf-8"),
                    hashlib.sha256,
                ).hexdigest()
                payload = {
                    "app_id": app_id,
                    "timestamp": timestamp,
                    "original_url": url,
                    "sign": sign,
                }
                with httpx.Client(timeout=10) as client:
                    resp = client.post(
                        "https://openplatform.shopee.com.br/v2/affiliate/short_url/create",
                        json=payload,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("code") == 0:
                            return data.get("data", {}).get("short_url", url)
            except Exception:
                pass
        return url

    # --- AliExpress: API de afiliado (tracking link) ---
    if source == "aliexpress":
        app_key = settings.aliexpress_app_key
        secret = settings.aliexpress_secret
        tracking_id = settings.aliexpress_tracking_id
        if app_key and secret and tracking_id:
            try:
                timestamp = int(time.time() * 1000)
                base_string = f"{app_key}{timestamp}{url}"
                sign = hmac.new(
                    secret.encode("utf-8"),
                    base_string.encode("utf-8"),
                    hashlib.sha256,
                ).hexdigest()
                params = {
                    "app_key": app_key,
                    "timestamp": timestamp,
                    "sign": sign,
                    "tracking_id": tracking_id,
                    "source_url": url,
                }
                # Endpoint genérico da AliExpress Affiliate (pode variar por região)
                with httpx.Client(timeout=10) as client:
                    resp = client.get(
                        "https://api-seller.aliexpress.com/openapi/router/rest",
                        params=params,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        # Ajuste conforme a resposta real da API da AliExpress
                        affiliate_link = (
                            data.get("affiliate_link")
                            or data.get("promotion_link")
                            or url
                        )
                        return affiliate_link
            except Exception:
                pass
        return url

    # --- Shopping agregado (Bing/Google): aplica o afiliado da loja de destino ---
    if source in {"shopping", "google_shopping"}:
        host = (urlparse(url).hostname or "").lower()
        if "amazon." in host and settings.amazon_associate_tag:
            return _add_query_param(url, "tag", settings.amazon_associate_tag)
        if "mercadolivre.com.br" in host:
            params = _meli_params(settings)
            if params:
                return _add_query_params(url, params)
        return url

    # Demo: sem programa de afiliado
    if source == "demo":
        return url

    # Fonte desconhecida: retorna URL original sem modificar
    return url


def aplicar_links_afiliado(offers: list[Offer], settings: Settings) -> list[Offer]:
    """Aplica links de afiliado em todas as ofertas da lista."""
    for offer in offers:
        offer.affiliate_url = _build_affiliate_url(
            offer.source, offer.url, settings
        )
    return offers