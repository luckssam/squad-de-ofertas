"""Utilidades de texto, preço e similaridade usadas pelos agentes."""
from __future__ import annotations

import hashlib
import re
import unicodedata

STOPWORDS = {
    "a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "com", "sem",
    "para", "por", "em", "no", "na", "nos", "nas", "um", "uma", "uns", "umas",
    "que", "com", "mais", "ate", "ou", "the", "and", "for", "with",
}


def strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_text(text: str) -> str:
    text = strip_accents(text or "").lower()
    text = re.sub(r"[^a-z0-9\s\+\.\-]", " ", text)
    return " ".join(text.split())


def tokens(text: str) -> list[str]:
    return [t for t in normalize_text(text).split() if t and t not in STOPWORDS]


def token_set(text: str) -> set[str]:
    return set(tokens(text))


def compact(text: str) -> str:
    """Remove espaços para comparar '128 gb' com '128gb'."""
    return normalize_text(text).replace(" ", "")


def parse_price(value) -> float | None:
    """Converte 'R$ 1.299,00', '1.299',00' ou 1299.9 em float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    text = str(value)
    text = text.replace("\xa0", " ").strip()
    match = re.search(r"[\d][\d\.,\s]*", text)
    if not match:
        return None
    number = match.group(0).replace(" ", "")
    if "," in number and "." in number:
        if number.rfind(",") > number.rfind("."):
            number = number.replace(".", "").replace(",", ".")
        else:
            number = number.replace(",", "")
    elif "," in number:
        number = number.replace(".", "").replace(",", ".")
    else:
        parts = number.split(".")
        if len(parts) > 2:
            number = "".join(parts)
        elif len(parts) == 2 and len(parts[1]) == 3:
            number = "".join(parts)
    try:
        parsed = float(number)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def format_brl(value: float | None) -> str:
    if value is None:
        return "—"
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def short_hash(text: str, size: int = 10) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:size]


def jaccard(a: str, b: str) -> float:
    set_a, set_b = token_set(a), token_set(b)
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def normalize_specs(values: list[str]) -> list[str]:
    """Remove repetidas e as que estão contidas em outra ('512GB' em 'SSD 512GB')."""
    cleaned: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in values:
        value = " ".join(str(raw or "").split()).strip(" .;-")
        key = compact(value)
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned.append((value, key))
    return [
        value
        for value, key in cleaned
        if not any(key != other and key in other for _, other in cleaned)
    ]


def safe_url(url: str | None) -> str:
    if not url:
        return "#"
    if url.startswith(("http://", "https://")):
        return url.replace("http://", "https://", 1)
    return "#"


def ensure_currency(value: str | None) -> str:
    return (value or "BRL").upper()
