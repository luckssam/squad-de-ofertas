"""Conector da Amazon Brasil via navegador (sem custo e sem cota).

A Amazon nao tem API publica gratuita de busca: a Creators API (que substituiu
a PA-API 5.0) exige 10 vendas qualificadas nos ultimos 30 dias. Como o site
publico continua acessivel para navegadores, extraimos as ofertas da pagina de
resultados usando o Edge/Chrome instalado no computador.

Se `AMAZON_WEB_ENABLED=false` (ou se o navegador falhar e houver chave), o
conector cai automaticamente para o SerpAPI.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

from connectors.amazon_serpapi import AmazonSerpApiConnector
from connectors.base import Connector, ConnectorError, build_terms
from connectors.browser import BrowserError, shared_browser
from core.config import Settings
from core.models import Intent, Offer
from core.utils import is_junk_title, safe_url

logger = logging.getLogger("squad.amazon_web")

EXTRACT_JS = """
() => {
  const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
  const cards = Array.from(document.querySelectorAll('div[data-component-type="s-search-result"]'));
  return cards.map((el) => {
    const q = (sel) => el.querySelector(sel);
    const titleEl = q('h2 span') || q('h2');
    const priceEl = q('.a-price .a-offscreen');
    const wholeEl = q('.a-price-whole');
    const fracEl = q('.a-price-fraction');
    const imgEl = q('img.s-image');
    const ratingEl = q('.a-icon-alt');
    const reviewsEl = Array.from(el.querySelectorAll('[aria-label]'))
      .find((n) => /^[\\d.,]+\\s*(mil\\s+)?classifica/i.test(n.getAttribute('aria-label') || ''));
    return {
      asin: el.getAttribute('data-asin') || '',
      title: clean(titleEl?.textContent),
      alt: imgEl ? clean(imgEl.getAttribute('alt')) : '',
      price_offscreen: clean(priceEl?.textContent),
      price_whole: clean(wholeEl?.textContent),
      price_fraction: clean(fracEl?.textContent),
      image: imgEl ? (imgEl.getAttribute('src') || '') : '',
      rating: clean(ratingEl?.textContent),
      reviews: reviewsEl ? (reviewsEl.getAttribute('aria-label') || '') : '',
      sponsored: /Patrocinado/i.test(el.innerText || ''),
    };
  });
}
"""

BLOCK_MARKERS = ("Digite os caracteres", "captcha", "Para continuar, informe", "not a robot")


def _parse_price(raw: dict[str, Any]) -> float | None:
    text = raw.get("price_offscreen") or ""
    match = re.search(r"(\d{1,3}(?:\.\d{3})*),(\d{2})", text)
    if match:
        digits = match.group(1).replace(".", "")
        return float(f"{digits}.{match.group(2)}")
    whole = re.sub(r"\D", "", raw.get("price_whole") or "")
    fraction = re.sub(r"\D", "", raw.get("price_fraction") or "").ljust(2, "0")[:2]
    if whole:
        return float(f"{whole}.{fraction}")
    return None


def _parse_rating(text: str) -> float | None:
    match = re.search(r"(\d(?:[.,]\d)?)", text or "")
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def _parse_reviews(text: str) -> int | None:
    """Converte '45.780 classificações' ou '45,7 mil' em inteiro."""
    match = re.search(r"([\d.,]+)\s*(mil)?", text or "", re.I)
    if not match:
        return None
    raw = match.group(1).strip(".,")
    if not raw:
        return None
    if match.group(2):
        try:
            return int(round(float(raw.replace(".", "").replace(",", ".")) * 1000))
        except ValueError:
            return None
    digits = re.sub(r"\D", "", raw)
    return int(digits) if digits else None


def _clean_alt(alt: str) -> str:
    """Limpa a descrição da imagem ('Anúncio patrocinado – ... | ...')."""
    text = re.sub(r"^\s*an[uú]ncio patrocinado\s*[–-]\s*", "", alt or "", flags=re.I)
    text = text.split("|")[0]
    return " ".join(text.split()).strip()


def _best_title(raw: dict[str, Any]) -> str:
    """Em muitos cards o <h2> traz só a marca ('FILA'); a alt tem o produto."""
    h2 = " ".join((raw.get("title") or "").split())
    alt = _clean_alt(raw.get("alt") or "")
    if is_junk_title(alt):
        alt = ""
    if is_junk_title(h2):
        h2 = ""
    if not alt:
        return h2
    if not h2 or len(h2) < 15:
        return alt if len(alt) >= len(h2) else h2
    return alt if len(alt) > len(h2) * 1.25 else h2


class AmazonBrowser:
    """Extrai ofertas da pagina de resultados da Amazon."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.browser = shared_browser(
            settings,
            settings.amazon_browser_profile,
            "Amazon",
            channel=settings.amazon_browser_channel,
        )

    def _build_url(self, query: str, price_min: float | None, price_max: float | None) -> str:
        url = f"https://www.amazon.com.br/s?k={quote_plus(query)}"
        if price_min:
            url += f"&low-price={int(price_min)}"
        if price_max:
            url += f"&high-price={int(price_max)}"
        return url

    async def search(
        self,
        query: str,
        limit: int,
        price_min: float | None = None,
        price_max: float | None = None,
    ) -> list[dict[str, Any]]:
        url = self._build_url(query, price_min, price_max)
        raw_items, html, _final_url = await self.browser.extract(
            url,
            EXTRACT_JS,
            wait_selector='div[data-component-type="s-search-result"]',
            key="amazon",
        )
        if not raw_items:
            if any(marker.lower() in html.lower() for marker in BLOCK_MARKERS):
                raise BrowserError(
                    "A Amazon pediu verificacao (captcha). Rode 'python amazon_setup_browser.py' "
                    "uma vez para liberar a sessao."
                )
            return []

        offers: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in raw_items:
            asin = (raw.get("asin") or "").strip().upper()
            title = _best_title(raw)
            if not asin or not title or asin in seen:
                continue
            price = _parse_price(raw)
            if price is None or price <= 0:
                continue
            if price_min and price < price_min:
                continue
            if price_max and price > price_max:
                continue
            seen.add(asin)
            offers.append(
                {
                    "id": asin,
                    "title": title,
                    "price": price,
                    "url": f"https://www.amazon.com.br/dp/{asin}",
                    "image": raw.get("image") or None,
                    "rating": raw.get("rating") or "",
                    "reviews": raw.get("reviews") or "",
                    "sponsored": bool(raw.get("sponsored")),
                }
            )
            if len(offers) >= limit:
                break
        return offers

    async def aclose(self) -> None:
        """Nada a fazer: o navegador e compartilhado e fechado pelo app."""


class AmazonConnector(Connector):
    """Amazon pelo navegador (gratis) com SerpAPI como reserva."""

    id = "amazon"
    label = "Amazon"
    experimental = False

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._browser: AmazonBrowser | None = None
        self._serpapi = AmazonSerpApiConnector(settings)

    @property
    def _web(self) -> AmazonBrowser:
        if self._browser is None:
            self._browser = AmazonBrowser(self.settings)
        return self._browser

    @property
    def configured(self) -> bool:
        return bool(self.settings.amazon_web_enabled or self._serpapi.configured)

    @property
    def setup_hint(self) -> str:
        if self.settings.amazon_web_enabled:
            return "Busca no site da Amazon via navegador (sem custo)."
        return self._serpapi.setup_hint

    async def search(self, intent: Intent, limit: int) -> list[Offer]:
        if self.settings.amazon_web_enabled:
            try:
                return await self._search_web(intent, limit)
            except ConnectorError as exc:
                if not self._serpapi.configured:
                    raise
                logger.info("Amazon via navegador falhou (%s); usando SerpAPI.", exc)
        if not self._serpapi.configured:
            raise ConnectorError(
                "Amazon: busca desativada. Defina AMAZON_WEB_ENABLED=true ou SERPAPI_KEY no .env."
            )
        return await self._serpapi.search(intent, limit)

    async def _search_web(self, intent: Intent, limit: int) -> list[Offer]:
        try:
            raw_offers = await self._web.search(
                build_terms(intent),
                limit,
                price_min=intent.budget_min,
                price_max=intent.budget_max,
            )
        except BrowserError as exc:
            raise ConnectorError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(
                f"Falha ao consultar o site da Amazon ({exc.__class__.__name__})."
            ) from exc

        offers: list[Offer] = []
        for item in raw_offers:
            offers.append(
                Offer(
                    id=f"amazon-{item['id']}",
                    source=self.id,
                    source_label=self.label,
                    title=item["title"],
                    price=float(item["price"]),
                    currency="BRL",
                    url=safe_url(item["url"]),
                    image=safe_url(item.get("image")) if item.get("image") else None,
                    seller="Amazon",
                    rating=_parse_rating(item.get("rating", "")),
                    reviews=_parse_reviews(item.get("reviews", "")),
                    condition="novo",
                )
            )
        return offers

    async def aclose(self) -> None:
        if self._browser is not None:
            await self._browser.aclose()
            self._browser = None
