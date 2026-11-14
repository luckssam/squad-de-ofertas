"""Configuração central do Squad de Ofertas.

As chaves ficam em um arquivo .env na raiz do projeto (nunca versionar).
Tudo é opcional: sem chaves o app roda em modo demonstração.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path | None = None) -> None:
    """Carrega um .env simples sem depender de bibliotecas externas."""
    env_path = path or (BASE_DIR / ".env")
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    value = _env(name)
    if not value:
        return default
    return value.lower() in {"1", "true", "yes", "sim", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name) or default)
    except ValueError:
        return default


@dataclass
class Settings:
    # LLM (opcional) — qualquer endpoint compatível com OpenAI Chat Completions
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    # Fontes
    serpapi_key: str = ""
    meli_access_token: str = ""
    amazon_access_key: str = ""
    amazon_secret_key: str = ""
    amazon_partner_tag: str = ""
    amazon_host: str = "webservices.amazon.com.br"
    amazon_region: str = "us-east-1"
    shopee_app_id: str = ""
    shopee_secret: str = ""
    aliexpress_app_key: str = ""
    aliexpress_secret: str = ""
    aliexpress_tracking_id: str = ""

    # Comportamento
    demo_mode: bool = True
    request_timeout: int = 18
    max_offers_per_source: int = 20
    port: int = 8765
    cache_ttl: int = 900
    amazon_via_serpapi: bool = True

    # Mercado Livre OAuth
    meli_client_id: str = ""
    meli_client_secret: str = ""
    meli_redirect_uri: str = "http://localhost:8765/auth/meli/callback"
    meli_token_file: str = "data/meli_token.json"
    # Mercado Livre Afiliados (etiqueta + ferramenta)
    ml_affiliate_tag: str = ""
    ml_affiliate_tool: str = ""

    # Mercado Livre: modo de busca
    # A API oficial esta bloqueada para apps de terceiros (403); por padrao
    # usamos o site publico via navegador real (sem custo e sem cota).
    meli_use_api: bool = False
    meli_web_enabled: bool = True
    meli_browser_profile: str = "data/browser_profile"
    meli_browser_channel: str = "msedge"

    # Amazon: modo de busca
    # A Creators API exige 10 vendas/30 dias; por padrao usamos o site publico
    # via navegador real. Se falhar, cai para o SerpAPI (quando houver chave).
    amazon_web_enabled: bool = True
    amazon_browser_profile: str = "data/browser_profile"
    amazon_browser_channel: str = "msedge"
    browser_channel: str = "msedge"

    # Shopping: Bing via navegador (gratis) ou Google via SerpAPI (reserva)
    shopping_web_enabled: bool = True
    shopping_browser_profile: str = "data/browser_profile"
    shopping_browser_channel: str = "msedge"
    shopping_resolve_concurrency: int = 6

    # Amazon Associates
    amazon_associate_tag: str = ""

    # Shopee Afiliados
    shopee_app_id: str = ""
    shopee_secret: str = ""

    # AliExpress Afiliados
    aliexpress_app_key: str = ""
    aliexpress_secret: str = ""
    aliexpress_tracking_id: str = ""


    def __post_init__(self) -> None:
        self.openai_api_key = _env("OPENAI_API_KEY")
        self.openai_base_url = (_env("OPENAI_BASE_URL") or self.openai_base_url).rstrip("/")
        self.openai_model = _env("OPENAI_MODEL") or self.openai_model

        self.serpapi_key = _env("SERPAPI_KEY")
        self.meli_access_token = _env("MELI_ACCESS_TOKEN")
        self.amazon_access_key = _env("AMAZON_ACCESS_KEY")
        self.amazon_secret_key = _env("AMAZON_SECRET_KEY")
        self.amazon_partner_tag = _env("AMAZON_PARTNER_TAG")
        self.amazon_host = _env("AMAZON_HOST") or self.amazon_host
        self.amazon_region = _env("AMAZON_REGION") or self.amazon_region
        self.shopee_app_id = _env("SHOPEE_APP_ID")
        self.shopee_secret = _env("SHOPEE_SECRET")
        self.aliexpress_app_key = _env("ALIEXPRESS_APP_KEY")
        self.aliexpress_secret = _env("ALIEXPRESS_SECRET")
        self.aliexpress_tracking_id = _env("ALIEXPRESS_TRACKING_ID")

        self.demo_mode = _env_bool("DEMO_MODE", True)
        self.request_timeout = _env_int("REQUEST_TIMEOUT", 18)
        self.max_offers_per_source = _env_int("MAX_OFFERS_PER_SOURCE", 20)
        self.port = _env_int("PORT", 8765)
        self.cache_ttl = _env_int("CACHE_TTL", 900)
        self.amazon_via_serpapi = _env_bool("AMAZON_VIA_SERPAPI", True)

        self.meli_client_id = _env("MELI_CLIENT_ID")
        self.meli_client_secret = _env("MELI_CLIENT_SECRET")
        self.meli_redirect_uri = _env("MELI_REDIRECT_URI") or self.meli_redirect_uri
        self.meli_token_file = _env("MELI_TOKEN_FILE") or self.meli_token_file
        self.ml_affiliate_tag = _env("ML_AFFILIATE_TAG") or _env("ML_AFFILIATE_ID")
        self.ml_affiliate_tool = _env("ML_AFFILIATE_TOOL")
        self.meli_use_api = _env_bool("MELI_USE_API", False)
        self.meli_web_enabled = _env_bool("MELI_WEB_ENABLED", True)
        self.meli_browser_profile = _env("MELI_BROWSER_PROFILE") or self.meli_browser_profile
        self.meli_browser_channel = _env("MELI_BROWSER_CHANNEL") or self.meli_browser_channel
        self.amazon_web_enabled = _env_bool("AMAZON_WEB_ENABLED", True)
        self.amazon_browser_profile = _env("AMAZON_BROWSER_PROFILE") or self.amazon_browser_profile
        self.amazon_browser_channel = _env("AMAZON_BROWSER_CHANNEL") or self.amazon_browser_channel
        self.browser_channel = _env("BROWSER_CHANNEL") or self.browser_channel
        self.shopping_web_enabled = _env_bool("SHOPPING_WEB_ENABLED", True)
        self.shopping_browser_profile = (
            _env("SHOPPING_BROWSER_PROFILE") or self.shopping_browser_profile
        )
        self.shopping_browser_channel = (
            _env("SHOPPING_BROWSER_CHANNEL") or self.shopping_browser_channel
        )
        self.shopping_resolve_concurrency = _env_int("SHOPPING_RESOLVE_CONCURRENCY", 6)
        self.amazon_associate_tag = _env("AMAZON_ASSOCIATE_TAG")
        self.shopee_app_id = _env("SHOPEE_APP_ID")
        self.shopee_secret = _env("SHOPEE_SECRET")
        self.aliexpress_app_key = _env("ALIEXPRESS_APP_KEY")
        self.aliexpress_secret = _env("ALIEXPRESS_SECRET")
        self.aliexpress_tracking_id = _env("ALIEXPRESS_TRACKING_ID")

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def amazon_configured(self) -> bool:
        return bool(self.amazon_access_key and self.amazon_secret_key and self.amazon_partner_tag)

    @property
    def shopee_configured(self) -> bool:
        return bool(self.shopee_app_id and self.shopee_secret)

    @property
    def aliexpress_configured(self) -> bool:
        return bool(self.aliexpress_app_key and self.aliexpress_secret)

    @property
    def meli_oauth_configured(self) -> bool:
        return bool(self.meli_client_id and self.meli_client_secret)

    @property
    def meli_configured(self) -> bool:
        """True se há token estático no .env OU token OAuth salvo (com refresh_token)."""
        if self.meli_access_token:
            return True
        try:
            from pathlib import Path

            token_path = Path(self.meli_token_file)
            if not token_path.is_absolute():
                token_path = BASE_DIR / token_path
            if token_path.exists():
                import json

                data = json.loads(token_path.read_text(encoding="utf-8"))
                return bool(data.get("refresh_token") or data.get("access_token"))
        except (OSError, ValueError):
            return False
        return False

    def meli_auth_url(self, state: str = "squad_ofertas", code_challenge: str = "") -> str:
        """Gera a URL de autorização do Mercado Livre (com PKCE opcional)."""
        if not self.meli_oauth_configured:
            return ""
        from urllib.parse import quote
        url = (
            "https://auth.mercadolivre.com.br/authorization"
            f"?response_type=code"
            f"&client_id={self.meli_client_id}"
            f"&redirect_uri={quote(self.meli_redirect_uri, safe='')}"
            f"&state={state}"
        )
        if code_challenge:
            url += f"&code_challenge={code_challenge}&code_challenge_method=S256"
        return url

    def public_config(self) -> dict:
        """Somente dados seguros para o navegador."""
        return {
            "demo_mode": self.demo_mode,
            "llm_enabled": self.llm_enabled,
            "llm_model": self.openai_model if self.llm_enabled else None,
            "currency": "BRL",
            "meli_oauth": {
                "configured": self.meli_oauth_configured,
                "auth_url": self.meli_auth_url(),
            },
            "sources": [
                {
                    "id": "demo",
                    "label": "Demonstração",
                    "configured": True,
                    "experimental": False,
                    "note": "Catálogo simulado para testar o fluxo sem chaves.",
                },
                {
                    "id": "mercadolivre",
                    "label": "Mercado Livre",
                    "configured": self.meli_configured,
                    "experimental": False,
                    "note": (
                        "Busca pelo site do ML via navegador (sem custo). "
                        "MELI_USE_API=true usa a API oficial apos certificacao."
                    ),
                },
                {
                    "id": "amazon",
                    "label": "Amazon",
                    "configured": self.amazon_web_enabled
                    or (self.amazon_via_serpapi and bool(self.serpapi_key)),
                    "experimental": False,
                    "note": (
                        "Busca no site da Amazon via navegador (sem custo). "
                        "AMAZON_WEB_ENABLED=false volta para o SerpAPI."
                    ),
                },
                {
                    "id": "shopping",
                    "label": "Shopping",
                    "configured": self.shopping_web_enabled or bool(self.serpapi_key),
                    "experimental": False,
                    "note": (
                        "Bing Shopping via navegador (sem custo). "
                        "SHOPPING_WEB_ENABLED=false usa Google Shopping/SerpAPI."
                    ),
                },
                {
                    "id": "shopee",
                    "label": "Shopee",
                    "configured": self.shopee_configured,
                    "experimental": True,
                    "note": "Open API de afiliados. Requer aprovação e credenciais.",
                },
                {
                    "id": "aliexpress",
                    "label": "AliExpress",
                    "configured": self.aliexpress_configured,
                    "experimental": True,
                    "note": "Affiliate API. Requer chaves do programa de afiliados.",
                },
            ],
        }


load_dotenv()
settings = Settings()
