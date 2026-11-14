"""Abre o Mercado Livre num navegador visivel para liberar a sessao.

Use este script UMA VEZ se a busca do Mercado Livre comecar a falhar com
"verificacao de seguranca" ou "bloqueou a consulta automatica".

O que fazer:
  1. Feche o app (stop-all.bat) para liberar o perfil do navegador.
  2. Rode:  .venv\\Scripts\\python.exe meli_setup_browser.py
  3. No navegador que abrir, resolva a verificacao e/ou faca login.
  4. Volte ao terminal e pressione ENTER.
  5. Inicie o app novamente (start-all.bat).

A sessao fica salva em data/browser_profile (o mesmo navegador do app).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from core.config import BASE_DIR, settings

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR', 'pt', 'en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
window.chrome = window.chrome || { runtime: {} };
"""


async def main() -> None:
    from playwright.async_api import async_playwright

    profile = Path(settings.meli_browser_profile)
    if not profile.is_absolute():
        profile = BASE_DIR / profile
    profile.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            str(profile),
            channel=settings.meli_browser_channel or "msedge",
            headless=False,
            locale="pt-BR",
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        await context.add_init_script(STEALTH_JS)
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://www.mercadolivre.com.br/", wait_until="domcontentloaded", timeout=60000)

        print("=" * 60)
        print("Navegador aberto no Mercado Livre.")
        print("Resolva a verificacao / faca login, depois volte aqui.")
        print("=" * 60)
        await asyncio.get_event_loop().run_in_executor(None, input, "Pressione ENTER para fechar... ")
        await context.close()
        print("Sessao salva. Pode iniciar o app novamente.")


if __name__ == "__main__":
    asyncio.run(main())
