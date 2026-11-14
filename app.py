"""Squad de Ofertas — API local (FastAPI) e servidor da interface."""
from __future__ import annotations

import json
import logging
import secrets
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from core.config import BASE_DIR, settings
from core.models import SearchRequest, SearchResult
from core.orchestrator import Squad
from connectors.browser import close_all_browsers
from connectors.meli_oauth import create_token_manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
# O httpx registra a URL completa em INFO; isso vazaria a SERPAPI_KEY no log.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("squad")

app = FastAPI(title="Squad de Ofertas", version="1.0.0")
squad = Squad(settings)
meli_token_mgr = create_token_manager(settings)


@app.on_event("shutdown")
async def _shutdown_connectors() -> None:
    """Fecha os conectores e o navegador compartilhado ao encerrar o app."""
    for connector in squad.connectors:
        closer = getattr(connector, "aclose", None)
        if closer is None:
            continue
        try:
            await closer()
        except Exception:  # noqa: BLE001
            pass
    await close_all_browsers()

# Armazena states temporarios para validar callback OAuth (state -> code_verifier PKCE)
_oauth_states: dict[str, str] = {}


def _generate_pkce() -> tuple[str, str]:
    """Gera code_verifier e code_challenge (S256) para PKCE."""
    import base64
    import hashlib

    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge

WEB_DIR = BASE_DIR / "web"


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "llm": settings.llm_enabled, "demo": settings.demo_mode}


@app.get("/api/config")
async def config() -> dict:
    return settings.public_config()


@app.post("/api/search", response_model=SearchResult)
async def search(request: SearchRequest) -> SearchResult:
    final: SearchResult | None = None
    async for event in squad.run(request):
        if event["type"] == "done":
            final = SearchResult.model_validate(event["result"])
    if final is None:
        return JSONResponse(status_code=500, content={"detail": "O squad nao retornou resultado."})
    return final


@app.post("/api/search/stream")
async def search_stream(request: SearchRequest) -> StreamingResponse:
    async def generator() -> AsyncIterator[str]:
        try:
            async for event in squad.run(request):
                payload = json.dumps(event, ensure_ascii=False)
                yield f"event: {event['type']}\ndata: {payload}\n\n"
        except Exception as exc:  # noqa: BLE001
            logger.exception("Falha no squad")
            payload = json.dumps(
                {"type": "error", "message": f"Erro inesperado no squad: {exc.__class__.__name__}"},
                ensure_ascii=False,
            )
            yield f"event: error\ndata: {payload}\n\n"

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --- Mercado Livre OAuth ---

@app.get("/auth/meli/start")
async def meli_oauth_start() -> RedirectResponse:
    """Inicia o fluxo OAuth redirecionando para o Mercado Livre."""
    if not settings.meli_oauth_configured:
        return JSONResponse(
            status_code=400,
            content={"detail": "OAuth do Mercado Livre nao configurado. Defina MELI_CLIENT_ID e MELI_CLIENT_SECRET."},
        )
    state = secrets.token_urlsafe(16)
    verifier, challenge = _generate_pkce()
    _oauth_states[state] = verifier
    auth_url = settings.meli_auth_url(state, code_challenge=challenge)
    return RedirectResponse(url=auth_url)


@app.get("/auth/meli/callback")
async def meli_oauth_callback(code: str = Query(...), state: str = Query(...)) -> JSONResponse:
    """Callback do Mercado Livre: troca code por tokens e salva."""
    if state not in _oauth_states:
        return JSONResponse(
            status_code=400,
            content={"detail": "State invalido ou expirado. Tente iniciar o fluxo novamente."},
        )
    code_verifier = _oauth_states.pop(state)

    token_data = meli_token_mgr.exchange_code(code, code_verifier=code_verifier)
    if not token_data:
        return JSONResponse(
            status_code=400,
            content={"detail": "Falha ao trocar codigo por tokens. Verifique Client ID/Secret e Redirect URI."},
        )

    return JSONResponse(
        content={
            "success": True,
            "message": "Mercado Livre conectado com sucesso! Token salvo e renovacao automatica ativada.",
            "expires_in": token_data.get("expires_in"),
        }
    )


@app.get("/api/meli/status")
async def meli_status() -> dict:
    """Retorna status do token do Mercado Livre."""
    return meli_token_mgr.get_status()


@app.post("/api/meli/disconnect")
async def meli_disconnect() -> dict:
    """Remove tokens salvos (logout)."""
    meli_token_mgr.clear_tokens()
    return {"success": True, "message": "Tokens do Mercado Livre removidos."}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


if __name__ == "__main__":
    import os
    import threading
    import webbrowser

    import uvicorn

    url = f"http://127.0.0.1:{settings.port}"
    logger.info("Squad de Ofertas em %s", url)
    if os.environ.get("OPEN_BROWSER", "1") != "0":
        threading.Timer(1.3, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=settings.port)