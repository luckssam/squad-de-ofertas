"""Gerenciador de tokens OAuth do Mercado Livre."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

from core.config import Settings

logger = logging.getLogger("squad.meli")


class MeliTokenManager:
    """Gerencia access_token e refresh_token do Mercado Livre."""

    TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
    TOKEN_EXPIRY_BUFFER = 300  # 5 min antes de expirar

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        from core.config import BASE_DIR

        token_path = Path(settings.meli_token_file)
        if not token_path.is_absolute():
            token_path = BASE_DIR / token_path
        self.token_file = token_path
        self.token_file.parent.mkdir(parents=True, exist_ok=True)

    def _load_token_data(self) -> dict[str, Any] | None:
        if not self.token_file.exists():
            return None
        try:
            return json.loads(self.token_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _save_token_data(self, data: dict[str, Any]) -> None:
        # Atomic write
        tmp = self.token_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.token_file)

    def has_refresh_token(self) -> bool:
        data = self._load_token_data()
        return bool(data and data.get("refresh_token"))

    def get_valid_access_token(self) -> str | None:
        """
        Retorna um access_token válido, renovando se necessário.
        """
        data = self._load_token_data()
        if not data:
            return None

        access_token = data.get("access_token")
        expires_at = data.get("expires_at", 0)
        now = time.time()

        # Token ainda válido?
        if access_token and now < (expires_at - self.TOKEN_EXPIRY_BUFFER):
            return access_token

        # Precisa renovar
        refresh_token = data.get("refresh_token")
        if not refresh_token:
            return None

        new_data = self._refresh_token(refresh_token)
        if new_data:
            return new_data.get("access_token")
        return None

    def _refresh_token(self, refresh_token: str) -> dict[str, Any] | None:
        """Troca refresh_token por novo access_token + refresh_token."""
        if not self.settings.meli_client_id or not self.settings.meli_client_secret:
            return None

        payload = {
            "grant_type": "refresh_token",
            "client_id": self.settings.meli_client_id,
            "client_secret": self.settings.meli_client_secret,
            "refresh_token": refresh_token,
        }

        try:
            with httpx.Client(timeout=self.settings.request_timeout) as client:
                response = client.post(self.TOKEN_URL, data=payload)
        except httpx.HTTPError:
            return None

        if response.status_code != 200:
            return None

        try:
            token_data = response.json()
        except ValueError:
            return None

        # Mercado Livre retorna novo refresh_token (single-use)
        new_refresh = token_data.get("refresh_token")
        if not new_refresh:
            return None

        now = time.time()
        expires_in = token_data.get("expires_in", 21600)  # default 6h
        new_data = {
            "access_token": token_data["access_token"],
            "refresh_token": new_refresh,
            "expires_at": now + expires_in,
            "token_type": token_data.get("token_type", "bearer"),
            "scope": token_data.get("scope", ""),
        }
        self._save_token_data(new_data)
        return new_data

    def exchange_code(self, code: str, code_verifier: str = "") -> dict[str, Any] | None:
        """Troca authorization code por tokens iniciais."""
        if not self.settings.meli_client_id or not self.settings.meli_client_secret:
            return None

        payload = {
            "grant_type": "authorization_code",
            "client_id": self.settings.meli_client_id,
            "client_secret": self.settings.meli_client_secret,
            "code": code,
            "redirect_uri": self.settings.meli_redirect_uri,
        }
        if code_verifier:
            payload["code_verifier"] = code_verifier

        try:
            with httpx.Client(timeout=self.settings.request_timeout) as client:
                response = client.post(self.TOKEN_URL, data=payload)
        except httpx.HTTPError as exc:
            logger.error("MELI exchange_code: erro de rede: %s", exc)
            return None

        if response.status_code != 200:
            logger.error(
                "MELI exchange_code: HTTP %s | body: %s | payload(redacted): %s",
                response.status_code,
                response.text[:1000],
                {
                    "grant_type": payload.get("grant_type"),
                    "client_id": payload.get("client_id"),
                    "redirect_uri": payload.get("redirect_uri"),
                    "code_len": len(str(payload.get("code", ""))),
                },
            )
            return None

        try:
            token_data = response.json()
        except ValueError:
            logger.error("MELI exchange_code: resposta não-JSON: %s", response.text[:500])
            return None

        refresh_token = token_data.get("refresh_token")
        if not refresh_token:
            return None

        now = time.time()
        expires_in = token_data.get("expires_in", 21600)
        new_data = {
            "access_token": token_data["access_token"],
            "refresh_token": refresh_token,
            "expires_at": now + expires_in,
            "token_type": token_data.get("token_type", "bearer"),
            "scope": token_data.get("scope", ""),
        }
        self._save_token_data(new_data)
        return new_data

    def get_status(self) -> dict[str, Any]:
        """Retorna status atual do token para exibição."""
        data = self._load_token_data()
        if not data:
            return {"has_token": False, "message": "Nenhum token salvo"}

        now = time.time()
        expires_at = data.get("expires_at", 0)
        has_refresh = bool(data.get("refresh_token"))

        if now >= expires_at:
            status = "expirado"
        elif now >= (expires_at - self.TOKEN_EXPIRY_BUFFER):
            status = "expirando_soon"
        else:
            status = "valido"

        return {
            "has_token": True,
            "has_refresh_token": has_refresh,
            "status": status,
            "expires_in": max(0, int(expires_at - now)),
            "message": f"Token {status} ({max(0, int(expires_at - now))}s restantes)" if has_refresh else "Sem refresh token",
        }

    def clear_tokens(self) -> None:
        """Remove tokens salvos (logout)."""
        if self.token_file.exists():
            self.token_file.unlink()


def create_token_manager(settings: Settings) -> MeliTokenManager:
    """Factory para criar o gerenciador de tokens."""
    return MeliTokenManager(settings)