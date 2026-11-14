"""Shopping via Bing (navegador) com Google Shopping/SerpAPI como reserva.

O Google Shopping nao expoe o link da loja nos cards (o clique e tratado por
JavaScript), entao scraping direto nao serve para o botao "Ver oferta".

O Bing Shopping expoe cards com titulo, preco, loja e um link de redirect
(`bing.com/aclick`). Resolvendo o redirect com os cookies da propria sessao do
navegador, chegamos a URL real do produto (Amazon com ASIN, Mercado Livre,
Magalu, Netshoes...). Tudo sem custo e sem consumir SerpAPI.

Se `SHOPPING_WEB_ENABLED=false` (ou se o navegador falhar e houver chave), o
conector cai automaticamente para o Google Shopping via SerpAPI.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import httpx

from connectors.base import Connector, ConnectorError, build_terms
from connectors.browser import BrowserError, shared_browser
from connectors.google_shopping import GoogleShoppingConnector
from core.config import Settings
from core.models import Intent, Offer
from core.utils import is_junk_title, safe_url, short_hash

logger = logging.getLogger("squad.shopping")

EXTRACT_JS = """
() => {
  const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
  const cards = Array.from(document.querySelectorAll('[role="listitem"]'))
    .filter((el) => /R\\$/.test(el.innerText || ''));
  return cards.map((el) => {
    const lines = (el.innerText || '').split('\\n').map((s) => s.trim()).filter(Boolean);
    const link = el.querySelector('a[href*="aclick"]') || el.querySelector('a[href]');
    const img = el.querySelector('img');
    const priceIdx = lines.findIndex((line) => /R\\$/.test(line));
    return {
      title: lines[0] || '',
      alt: img ? (img.getAttribute('alt') || '') : '',
      price: priceIdx >= 0 ? lines[priceIdx] : '',
      store: priceIdx >= 0 ? (lines[priceIdx + 1] || '') : '',
      lines: lines.slice(0, 12),
      href: link ? link.href : '',
      image: img ? (img.getAttribute('src') || img.getAttribute('data-src') || '') : '',
      linkTitle: link ? (link.getAttribute('title') || link.getAttribute('aria-label') || '') : '',
    };
  });
}
"""

BLOCK_MARKERS = ("captcha", "unusual traffic", "Verifique se você é humano")

# Hosts intermediarios de anuncio: continuamos seguindo ate chegar na loja.
AD_HOSTS = (
    "doubleclick.net",
    "googleadservices.com",
    "googlesyndication.com",
    "adservice.google.com",
    "awin1.com",
    "criteo",
    "adnxs.com",
    "temu.com/aclk",
)


def _clean_url(url: str) -> str:
    """Normaliza links da Amazon para /dp/ASIN (remove ref/params do Bing)."""
    match = re.search(r"amazon\.com\.br/.*?/dp/([A-Z0-9]{10})", url)
    if match:
        return f"https://www.amazon.com.br/dp/{match.group(1)}"
    return url


def _best_title(raw: dict[str, Any]) -> str:
    """O card do Bing trunca o titulo com '…'; a alt da imagem costuma ter o nome completo."""
    candidates = [
        (raw.get("alt") or "").strip(),
        (raw.get("linkTitle") or "").strip(),
        (raw.get("title") or "").strip(),
    ]
    usable = [item for item in candidates if item and not is_junk_title(item)]
    if not usable:
        return ""
    best = max(usable, key=len)
    return best.rstrip("…").strip()


def _parse_price(text: str) -> float | None:
    match = re.search(r"R\$\s*(\d{1,3}(?:\.\d{3})*),(\d{2})", text or "")
    if not match:
        return None
    try:
        return float(match.group(1).replace(".", "") + "." + match.group(2))
    except ValueError:
        return None


def _price_index(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        if re.search(r"R\$\s*\d", line):
            return index
    return -1


def _pick_store(lines: list[str], price_idx: int) -> str:
    """Escolhe o nome da loja, ignorando precos antigos e rotulos do card."""
    if price_idx < 0:
        return ""
    for line in lines[price_idx + 1 :]:
        text = line.strip()
        if not text or text in {"·", "Oferta", "Patrocinado"}:
            continue
        if text.startswith("R$") or re.fullmatch(r"[\d.,]+", text):
            continue
        if text.lower().startswith(("ícone", "icone", "envio", "frete", "chega")):
            continue
        return text
    return ""


def _parse_rating(lines: list[str]) -> float | None:
    for line in lines:
        match = re.fullmatch(r"(\d(?:[.,]\d)?)", line.strip())
        if match:
            try:
                return float(match.group(1).replace(",", "."))
            except ValueError:
                return None
    return None


def _parse_reviews(lines: list[str]) -> int | None:
    for line in lines:
        digits = re.sub(r"\D", "", line)
        if digits and len(digits) >= 1 and line.strip() == digits:
            return int(digits)
    return None


class BingShoppingBrowser:
    """Extrai ofertas do Bing Shopping e resolve o link final de cada produto."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.browser = shared_browser(
            settings,
            settings.shopping_browser_profile,
            "Shopping",
            channel=settings.shopping_browser_channel,
        )

    def _build_url(self, query: str) -> str:
        return f"https://www.bing.com/shop?q={quote(query)}&setlang=pt-br&cc=BR"

    async def _follow(self, client: httpx.AsyncClient, url: str, max_hops: int = 6) -> str | None:
        """Segue os redirects do Bing ate chegar na loja (sem baixar a pagina final)."""
        current = url
        for _ in range(max_hops):
            if not current:
                return None
            host = urlparse(current).hostname or ""
            is_ad = any(marker in host for marker in AD_HOSTS)
            if host and "bing.com" not in host and not is_ad:
                return current
            try:
                response = await client.get(current, follow_redirects=False)
            except httpx.HTTPError:
                return None
            location = response.headers.get("location")
            if location:
                current = urljoin(current, location)
                continue
            if response.status_code == 200:
                # Alguns cliques vem como HTML com meta refresh / window.location.
                match = re.search(
                    r'(?:https?:)?//[^\s"\'<>]+',
                    response.text[:4000],
                )
                if match:
                    candidate = match.group(0)
                    if candidate.startswith("//"):
                        candidate = "https:" + candidate
                    if "bing.com" not in (urlparse(candidate).hostname or ""):
                        return candidate
            return None
        return None

    async def _resolve_many(self, hrefs: list[str]) -> list[str | None]:
        cookies = await self.browser.cookies()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
            ),
            "Accept-Language": "pt-BR,pt;q=0.9",
            "Referer": "https://www.bing.com/shop",
        }
        limit = max(1, int(self.settings.shopping_resolve_concurrency))
        semaphore = asyncio.Semaphore(limit)

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            headers=headers,
            cookies=cookies,
        ) as client:

            async def one(href: str) -> str | None:
                if not href:
                    return None
                async with semaphore:
                    return await self._follow(client, href)

            return list(await asyncio.gather(*(one(href) for href in hrefs)))

    async def search(
        self,
        query: str,
        limit: int,
        price_min: float | None = None,
        price_max: float | None = None,
    ) -> list[dict[str, Any]]:
        raw_items: list[dict[str, Any]] = []
        html = ""
        for attempt in range(2):
            raw_items, html, _final_url = await self.browser.extract(
                self._build_url(query),
                EXTRACT_JS,
                wait_selector='[role="listitem"]',
                selector_timeout=30000,
                key="shopping",
            )
            if raw_items:
                break
            if any(marker.lower() in html.lower() for marker in BLOCK_MARKERS):
                raise BrowserError("O Bing pediu verificacao (captcha). Tente novamente em instantes.")
            if attempt == 0:
                logger.info("Bing nao retornou cards em %s; tentando de novo.", query)
                await asyncio.sleep(2)

        if not raw_items:
            return []

        parsed: list[dict[str, Any]] = []
        for raw in raw_items:
            price = _parse_price(raw.get("price", ""))
            title = _best_title(raw)
            if not price or price < 1 or not title:
                continue
            if price_min and price < price_min:
                continue
            if price_max and price > price_max:
                continue
            parsed.append(
                {
                    "title": title,
                    "price": price,
                    "store": _pick_store(raw.get("lines") or [], _price_index(raw.get("lines") or [])),
                    "image": raw.get("image") or None,
                    "href": raw.get("href") or "",
                    "rating": _parse_rating(raw.get("lines") or []),
                    "reviews": _parse_reviews(raw.get("lines") or []),
                }
            )
            if len(parsed) >= max(limit * 2, limit):
                break

        if not parsed:
            return []

        resolved = await self._resolve_many([item["href"] for item in parsed])
        offers: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item, url in zip(parsed, resolved):
            if not url or url in seen:
                continue
            url = _clean_url(url)
            host = urlparse(url).hostname or ""
            if any(marker in host for marker in AD_HOSTS):
                continue
            seen.add(url)
            offers.append({**item, "url": url})
            if len(offers) >= limit:
                break
        return offers

    async def aclose(self) -> None:
        """Nada a fazer: o navegador e compartilhado e fechado pelo app."""


class ShoppingConnector(Connector):
    """Shopping gratis (Bing via navegador) com Google/SerpAPI como reserva."""

    id = "shopping"
    label = "Shopping"
    experimental = False

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._browser: BingShoppingBrowser | None = None
        self._google = GoogleShoppingConnector(settings)
        if not settings.shopping_web_enabled:
            self.id = "google_shopping"
            self.label = "Google Shopping"

    @property
    def _web(self) -> BingShoppingBrowser:
        if self._browser is None:
            self._browser = BingShoppingBrowser(self.settings)
        return self._browser

    @property
    def configured(self) -> bool:
        return bool(self.settings.shopping_web_enabled or self._google.configured)

    @property
    def setup_hint(self) -> str:
        if self.settings.shopping_web_enabled:
            return "Shopping pelo Bing via navegador (sem custo)."
        return self._google.setup_hint

    async def search(self, intent: Intent, limit: int) -> list[Offer]:
        if self.settings.shopping_web_enabled:
            try:
                return await self._search_web(intent, limit)
            except ConnectorError as exc:
                if not self._google.configured:
                    raise
                logger.info("Shopping via navegador falhou (%s); usando SerpAPI.", exc)
        if not self._google.configured:
            raise ConnectorError(
                "Shopping: busca desativada. Defina SHOPPING_WEB_ENABLED=true ou SERPAPI_KEY."
            )
        return await self._google.search(intent, limit)

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
                f"Falha ao consultar o Shopping ({exc.__class__.__name__})."
            ) from exc

        if not raw_offers:
            raise ConnectorError("O Shopping nao retornou ofertas com link agora.")

        offers: list[Offer] = []
        for item in raw_offers:
            offers.append(
                Offer(
                    id=f"shop-{short_hash(item['url'] + item['title'], 12)}",
                    source=self.id,
                    source_label=self.label,
                    title=item["title"],
                    price=float(item["price"]),
                    currency="BRL",
                    url=safe_url(item["url"]),
                    image=safe_url(item["image"]) if item.get("image") else None,
                    seller=item.get("store") or None,
                    rating=item.get("rating"),
                    reviews=item.get("reviews"),
                )
            )
        return offers

    async def aclose(self) -> None:
        if self._browser is not None:
            await self._browser.aclose()
            self._browser = None
