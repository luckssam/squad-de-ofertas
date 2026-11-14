"""Busca no Mercado Livre usando um navegador real (Playwright).

A API oficial de busca do Mercado Livre (`sites/MLB/search`) esta bloqueada
para apps de terceiros (HTTP 403), mesmo com token OAuth valido. Como o site
publico continua acessivel para navegadores, este modulo usa o navegador
compartilhado do app (mesmo Edge do Amazon/Shopping).

Nao usa nenhuma API paga e nao consome creditos do SerpAPI.

O perfil do navegador fica salvo em `data/browser_profile`, entao eventuais
verificacoes sao resolvidas uma unica vez (rode `python meli_setup_browser.py`
se o Mercado Livre pedir confirmacao).
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any

from connectors.browser import BrowserError, shared_browser
from core.config import Settings
from core.utils import is_junk_title

logger = logging.getLogger("squad.meli_web")

EXTRACT_JS = """
() => {
  const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
  const nodes = Array.from(document.querySelectorAll('li.ui-search-layout__item'));
  return nodes.map((el) => {
    const q = (sel) => el.querySelector(sel);
    const priceBox = q('.poly-price__current') || el;
    const frac = clean(q('.poly-price__current .andes-money-amount__fraction')?.textContent)
      || clean(priceBox.querySelector('.andes-money-amount__fraction')?.textContent);
    const cents = clean(q('.poly-price__current .andes-money-amount__cents')?.textContent)
      || clean(priceBox.querySelector('.andes-money-amount__cents')?.textContent);
    const prev = q('.andes-money-amount--previous');
    const link = q('a.poly-component__title') || q('a.ui-search-link') || q('a');
    return {
      title: clean(q('.poly-component__title')?.textContent),
      href: link ? link.href : '',
      price_int: frac,
      price_cents: cents,
      old_int: clean(prev?.querySelector('.andes-money-amount__fraction')?.textContent),
      seller: clean(q('.poly-component__seller')?.textContent),
      shipping: clean(q('.poly-component__shipping')?.textContent),
      installments: clean(q('.poly-price__installments')?.textContent),
      rating: clean(q('.poly-reviews__rating')?.textContent),
      reviews: clean(q('.poly-reviews__total')?.textContent),
      image: q('img.poly-component__picture')?.getAttribute('src') || '',
      discount: clean(q('.poly-price__disc_label')?.textContent),
    };
  });
}
"""


class MeliWebError(Exception):
    """Falha ao carregar a pagina do Mercado Livre."""


def slugify(text: str) -> str:
    """Converte o termo de busca no formato de URL do Mercado Livre."""
    normalized = unicodedata.normalize("NFKD", text or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    return slug[:120] or "ofertas"


def _to_float(int_part: str, cents: str) -> float | None:
    digits = re.sub(r"\D", "", int_part or "")
    if not digits:
        return None
    cents_digits = re.sub(r"\D", "", cents or "")[:2].ljust(2, "0")
    try:
        return float(f"{int(digits)}.{cents_digits}")
    except ValueError:
        return None


def _extract_item_id(href: str) -> str | None:
    match = re.search(r"(MLB\d{6,})", href or "")
    return match.group(1) if match else None


class MeliBrowser:
    """Usa o navegador compartilhado do app, reaproveitando a mesma aba."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.browser = shared_browser(
            settings,
            settings.meli_browser_profile,
            "Mercado Livre",
            channel=settings.meli_browser_channel,
        )

    def _build_url(
        self,
        query: str,
        price_min: float | None = None,
        price_max: float | None = None,
    ) -> str:
        slug = slugify(query)
        if price_min or price_max:
            low = int(price_min) if price_min else 0
            high = str(int(price_max)) if price_max else "*"
            return f"https://lista.mercadolivre.com.br/{slug}_PriceRange_{low}-{high}_NoIndex_True"
        return f"https://lista.mercadolivre.com.br/{slug}"

    async def search(
        self,
        query: str,
        limit: int,
        price_min: float | None = None,
        price_max: float | None = None,
    ) -> list[dict[str, Any]]:
        url = self._build_url(query, price_min, price_max)
        try:
            raw_items, html, final_url = await self.browser.extract(
                url,
                EXTRACT_JS,
                wait_selector="li.ui-search-layout__item",
                goto_timeout=30000,
                selector_timeout=15000,
                key="mercadolivre",
            )
        except BrowserError as exc:
            raise MeliWebError(
                "O Mercado Livre nao carregou. Rode 'python meli_setup_browser.py' "
                "para renovar a sessao."
            ) from exc

        if "account-verification" in final_url:
            raise MeliWebError(
                "O Mercado Livre pediu verificacao de seguranca. "
                "Rode 'python meli_setup_browser.py' uma vez para confirmar."
            )

        if not raw_items:
            if "requires JavaScript" in html or "suspicious" in html:
                raise MeliWebError(
                    "O Mercado Livre bloqueou a consulta automatica. "
                    "Rode 'python meli_setup_browser.py' para renovar a sessao."
                )
            return []

        offers: list[dict[str, Any]] = []
        for raw in raw_items or []:
            price = _to_float(raw.get("price_int", ""), raw.get("price_cents", ""))
            if price is None or price <= 0:
                continue
            item_id = _extract_item_id(raw.get("href", ""))
            if not item_id:
                continue
            title = (raw.get("title") or "").strip()
            if not title or is_junk_title(title):
                continue

            if price_min and price < price_min:
                continue
            if price_max and price > price_max:
                continue

            offers.append(
                {
                    "id": item_id,
                    "title": title,
                    "price": price,
                    "url": f"https://produto.mercadolivre.com.br/MLB-{item_id[3:]}",
                    "image": raw.get("image") or None,
                    "seller": (raw.get("seller") or "").strip() or None,
                    "shipping": (raw.get("shipping") or "").strip(),
                    "installments": (raw.get("installments") or "").strip() or None,
                    "rating": raw.get("rating") or "",
                    "reviews": raw.get("reviews") or "",
                }
            )
            if len(offers) >= limit:
                break

        return offers

    async def aclose(self) -> None:
        """Nada a fazer: o navegador e compartilhado e fechado pelo app."""
