"""Navegador off-screen reutilizavel para conectores que fazem scraping.

Varios sites (Mercado Livre, Amazon, Bing Shopping) bloqueiam clientes HTTP
simples e o modo headless "puro". A solucao que funciona e abrir o Edge/Chrome
instalado no computador com uma janela real, porem fora da tela e minimizada.

Todos os conectores compartilham **um unico navegador** (mesmo perfil em
`data/browser_profile`). Cada site usa sua propria aba, reaproveitada entre
buscas: assim o app nao fica abrindo varias janelas do Edge.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from core.config import BASE_DIR, Settings

logger = logging.getLogger("squad.browser")

# Esconde os sinais mais obvios de automacao.
STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR', 'pt', 'en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
window.chrome = window.chrome || { runtime: {} };
const origQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (params) =>
  params.name === 'notifications'
    ? Promise.resolve({ state: Notification.permission })
    : origQuery(params);
"""

BROWSER_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--window-position=-32000,-32000",
    "--start-minimized",
    "--disable-notifications",
]


class BrowserError(Exception):
    """Falha ao abrir o navegador ou carregar a pagina."""


class OffscreenBrowser:
    """Um navegador persistente, invisivel para o usuario."""

    def __init__(
        self,
        settings: Settings,
        profile: str,
        label: str = "site",
        channel: str | None = None,
    ) -> None:
        self.settings = settings
        self._profile = profile
        self.label = label
        self._channel = channel
        self._playwright: Any = None
        self._context: Any = None
        self._create_lock = asyncio.Lock()
        self._create_page_lock = asyncio.Lock()

    def _profile_path(self) -> Path:
        path = Path(self._profile)
        if not path.is_absolute():
            path = BASE_DIR / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def _ensure(self) -> Any:
        if self._context is not None:
            return self._context

        async with self._create_lock:
            if self._context is not None:
                return self._context

            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            kwargs = dict(
                headless=False,  # headless e detectado; a janela fica fora da tela
                locale="pt-BR",
                viewport={"width": 1366, "height": 900},
                args=BROWSER_ARGS,
                ignore_default_args=["--enable-automation"],
            )
            channel = self._channel or getattr(self.settings, "browser_channel", "") or "msedge"
            try:
                context = await self._playwright.chromium.launch_persistent_context(
                    str(self._profile_path()), channel=channel, **kwargs
                )
            except Exception:  # Edge/Chrome nao encontrado: tenta o Chromium do Playwright
                context = await self._playwright.chromium.launch_persistent_context(
                    str(self._profile_path()), **kwargs
                )

            await context.add_init_script(STEALTH_JS)
            self._context = context
            return context

    async def extract(
        self,
        url: str,
        extract_js: str,
        wait_selector: str | None = None,
        goto_timeout: int = 30000,
        selector_timeout: int = 20000,
        key: str | None = None,
    ) -> tuple[Any, str, str]:
        """Abre `url`, espera o seletor e roda o JS extrator.

        Retorna (dados, html, url_final). O HTML e a URL final sao uteis para
        diagnosticar bloqueios e redirecionamentos.

        A aba e fechada no fim para o navegador nao acumular memoria; a janela
        (unica) continua aberta para a proxima busca.
        """
        try:
            context = await self._ensure()
        except Exception as exc:  # noqa: BLE001
            raise BrowserError(
                "Nao foi possivel abrir o navegador. Instale com 'pip install playwright'."
            ) from exc

        async with self._create_page_lock:
            page = await context.new_page()
        try:
            await page.goto(url, timeout=goto_timeout, wait_until="domcontentloaded")
            if wait_selector:
                try:
                    await page.wait_for_selector(wait_selector, timeout=selector_timeout)
                except Exception:  # noqa: BLE001
                    logger.info(
                        "%s: seletor %s nao apareceu em %s", self.label, wait_selector, url
                    )
                    await page.wait_for_timeout(3000)
            data = await page.evaluate(extract_js)
            html = await page.content()
            return data, html, page.url
        except BrowserError:
            raise
        except Exception as exc:  # noqa: BLE001
            message = str(exc).lower()
            if any(
                token in message
                for token in ("closed", "disconnected", "target page", "browser has been")
            ):
                # A janela foi fechada (pelo usuario ou por falha): descarta o
                # contexto para que a proxima busca suba um navegador novo.
                await self.aclose()
                raise BrowserError(
                    "A janela do navegador foi fechada. Vou reabrir na proxima busca."
                ) from exc
            raise BrowserError(
                f"Falha ao carregar {self.label}: {exc.__class__.__name__}"
            ) from exc
        finally:
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                pass

    async def cookies(self) -> dict[str, str]:
        """Cookies do contexto, usados para resolver redirects via HTTP."""
        context = await self._ensure()
        try:
            return {item["name"]: item["value"] for item in await context.cookies()}
        except Exception:  # noqa: BLE001
            return {}

    async def aclose(self) -> None:
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:  # noqa: BLE001
                pass
            self._context = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:  # noqa: BLE001
                pass
            self._playwright = None


_SHARED: dict[str, OffscreenBrowser] = {}


def shared_browser(
    settings: Settings,
    profile: str,
    label: str = "site",
    channel: str | None = None,
) -> OffscreenBrowser:
    """Um navegador por perfil, compartilhado entre conectores (economiza RAM)."""
    path = Path(profile)
    if not path.is_absolute():
        path = BASE_DIR / path
    key = str(path.resolve())
    browser = _SHARED.get(key)
    if browser is None:
        browser = OffscreenBrowser(settings, profile, label, channel=channel)
        _SHARED[key] = browser
    return browser


async def close_all_browsers() -> None:
    """Fecha todos os navegadores compartilhados (encerramento do app)."""
    for key, browser in list(_SHARED.items()):
        try:
            await browser.aclose()
        except Exception:  # noqa: BLE001
            pass
        _SHARED.pop(key, None)
