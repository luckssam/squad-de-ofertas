"""Agente de Intenção: transforma texto livre em uma busca estruturada."""
from __future__ import annotations

import json
import re

import httpx

from core.config import Settings
from core.models import Intent, SearchRequest
from core.utils import normalize_specs, normalize_text, parse_price

CATEGORY_HINTS: dict[str, list[str]] = {
    "Fone de ouvido": ["fone", "headphone", "headset", "earbud", "airpod", "buds"],
    "Notebook": ["notebook", "laptop", "ultrabook", "macbook"],
    "Celular": ["celular", "smartphone", "iphone", "galaxy", "redmi", "moto g", "pixel"],
    "Smartwatch": ["smartwatch", "relogio inteligente", "apple watch", "mi band"],
    "Air fryer": ["air fryer", "airfryer", "fritadeira"],
    "Cafeteira": ["cafeteira", "nespresso", "dolce gusto", "espresso"],
    "Tênis": ["tenis", "sapato", "sneaker"],
    "Monitor": ["monitor", "display"],
    "Teclado": ["teclado", "keyboard"],
    "Mouse": ["mouse"],
    "Cadeira": ["cadeira", "poltrona"],
    "Aspirador": ["aspirador", "robo aspirador"],
    "TV": ["smart tv", "televisao", " tv "],
    "Tablet": ["tablet", "ipad"],
    "Caixa de som": ["caixa de som", "soundbar", "speaker"],
    "Webcam": ["webcam"],
    "Impressora": ["impressora", "multifuncional"],
    "Bicicleta": ["bicicleta", "bike", "mtb"],
}

FILLERS = [
    "quero", "queria", "gostaria", "procuro", "procurar", "procurando", "buscar",
    "buscando", "encontrar", "encontre", "me mostra", "mostre", "preciso", "preciso de",
    "comprar", "compra", "melhor", "melhores", "oferta", "ofertas", "promocao",
    "promoção", "barato", "barata", "preco", "preço", "por favor", "um", "uma",
]

SPEC_PATTERN = re.compile(
    r"\b("
    r"\d+\s?(?:gb|tb|mb|pol|polegadas|hz|w|mah|ml|kg|cm|mm|l|litros)"
    r"|i3|i5|i7|i9|ryzen\s?\d|m1|m2|m3"
    r"|5g|4k|full\s?hd|oled|ips|amoled|bluetooth(?:\s?\d(?:\.\d)?)?|wi-?fi"
    r"|\d+\s?marchas|aro\s?\d+"
    r")\b",
    re.IGNORECASE,
)

BUDGET_MAX_PATTERN = re.compile(
    r"\b(?:at[eé]|no\s+m[aá]ximo|m[aá]ximo|abaixo\s+de|menos\s+de|limit(?:e)?\s+de)\s*"
    r"(?:r\$\s*)?(\d[\d\.]*(?:,\d{2})?(?:\s*mil)?)",
    re.IGNORECASE,
)
BUDGET_MIN_PATTERN = re.compile(
    r"\b(?:acima\s+de|a\s+partir\s+de|m[ií]nimo|min(?:imo)?\s+de)\s*"
    r"(?:r\$\s*)?(\d[\d\.]*(?:,\d{2})?(?:\s*mil)?)",
    re.IGNORECASE,
)
BUDGET_RANGE_PATTERN = re.compile(
    r"\b(?:entre|de)\s*(?:r\$\s*)?(\d[\d\.]*(?:,\d{2})?(?:\s*mil)?)\s*"
    r"(?:e|a|at[eé])\s*(?:r\$\s*)?(\d[\d\.]*(?:,\d{2})?(?:\s*mil)?)",
    re.IGNORECASE,
)


def _money(raw: str) -> float | None:
    text = raw.strip().lower()
    multiplier = 1.0
    if "mil" in text:
        multiplier = 1000.0
        text = text.replace("mil", "").strip()
    value = parse_price(text)
    return round(value * multiplier, 2) if value else None


def _clean_product(text: str, specs: list[str]) -> str:
    product = text
    for spec in sorted(specs, key=len, reverse=True):
        product = re.sub(re.escape(spec), " ", product, flags=re.IGNORECASE)
    lowered = product.lower()
    for filler in sorted(FILLERS, key=len, reverse=True):
        lowered = re.sub(rf"\b{re.escape(filler)}\b", " ", lowered)
    lowered = re.sub(r"\b(?:de|da|do|com|sem|para|por|e|o|a|os|as)\b", " ", lowered)
    lowered = re.sub(r"[^\w\s\+\.\-]", " ", lowered)
    product = " ".join(lowered.split())
    if len(product) < 2:
        product = " ".join(normalize_text(text).split()[:6])
    return product[:90]


def _looks_like_budget(text: str, match: re.Match) -> bool:
    """Evita confundir 'até 40h de bateria' com orçamento de R$ 40."""
    following = text[match.end() : match.end() + 14].strip().lower()
    if re.match(
        r"(?:h|hs|horas?|gb|tb|mah|w|watts|pol|polegadas|ml|litros?|kg|cm|mm|hz|marchas|anos|meses|dias|x)\b",
        following,
    ):
        return False
    raw = match.group(0)
    if "r$" in raw.lower():
        return True
    amount = _money(match.group(1)) if match.lastindex else None
    return bool(amount and amount >= 50)


def _extract_specs(text: str) -> list[str]:
    specs: list[str] = []

    for match in re.finditer(r'"([^"]{2,40})"|\'([^\']{2,40})\'', text):
        value = (match.group(1) or match.group(2) or "").strip()
        if value:
            specs.append(value)

    for match in SPEC_PATTERN.finditer(text):
        value = " ".join(match.group(1).split())
        specs.append(value)

    com_match = re.search(r"\bcom\s+(.+?)(?:\s+(?:at[eé]|abaixo|entre|acima|por)\b|$)", text, re.IGNORECASE)
    if com_match:
        fragment = com_match.group(1)
        for part in re.split(r"\s*(?:,|;|/|\be\b)\s*", fragment):
            part = part.strip(" .")
            if 2 <= len(part) <= 40:
                specs.append(part)

    unique: list[str] = []
    seen: set[str] = set()
    for spec in specs:
        key = normalize_text(spec)
        if key and key not in seen:
            seen.add(key)
            unique.append(spec.strip())
    return unique[:6]


def heuristic_intent(request: SearchRequest) -> Intent:
    text = " ".join(request.query.split())

    budget_min = request.budget_min
    budget_max = request.budget_max
    cleaned = text

    range_match = BUDGET_RANGE_PATTERN.search(cleaned)
    if (
        range_match
        and budget_min is None
        and budget_max is None
        and _looks_like_budget(cleaned, range_match)
    ):
        low, high = _money(range_match.group(1)), _money(range_match.group(2))
        if low and high:
            budget_min, budget_max = min(low, high), max(low, high)
            cleaned = cleaned.replace(range_match.group(0), " ")
    else:
        max_match = BUDGET_MAX_PATTERN.search(cleaned)
        if max_match and budget_max is None and _looks_like_budget(cleaned, max_match):
            budget_max = _money(max_match.group(1))
            cleaned = cleaned.replace(max_match.group(0), " ")
        min_match = BUDGET_MIN_PATTERN.search(cleaned)
        if min_match and budget_min is None and _looks_like_budget(cleaned, min_match):
            budget_min = _money(min_match.group(1))
            cleaned = cleaned.replace(min_match.group(0), " ")

    if budget_min is not None and budget_max is not None and budget_min > budget_max:
        budget_min, budget_max = budget_max, budget_min

    exclude: list[str] = []
    wireless_specs: list[str] = []
    for match in re.finditer(r"\bsem\s+([^,;]{2,40}?)(?=\s+(?:e|com|at[eé]|por)\b|$)", cleaned, re.IGNORECASE):
        value = match.group(1).strip(" .")
        if not value:
            continue
        if normalize_text(value) in {"fio", "fios"}:
            wireless_specs.append("sem fio")
        else:
            exclude.append(value)
        cleaned = cleaned.replace(match.group(0), " ")
    for token in re.findall(r"(?:^|\s)-(\w{2,})", cleaned):
        exclude.append(token)

    specs = normalize_specs(_extract_specs(cleaned) + wireless_specs)
    must_have: list[str] = []
    com_match = re.search(r"\bcom\s+(.+?)(?:\s+(?:at[eé]|abaixo|entre|acima)\b|$)", cleaned, re.IGNORECASE)
    if com_match:
        must_have = [
            part.strip(" .")
            for part in re.split(r"\s*(?:,|;|/|\be\b)\s*", com_match.group(1))
            if part.strip()
        ]
    must_have = normalize_specs(must_have)

    product = _clean_product(cleaned, specs + must_have)
    keywords = list(dict.fromkeys((product + " " + " ".join(specs)).lower().split()))[:12]

    searchable = f" {normalize_text(text)} "
    category = None
    for label, hints in CATEGORY_HINTS.items():
        if any(f" {normalize_text(hint).strip()} " in searchable for hint in hints):
            category = label
            break

    if category:
        generic = {"ram", "ssd", "hdd", "memoria", "armazenamento", "gb", "tb"}
        kept = [word for word in product.split() if word not in generic]
        if kept:
            product = " ".join(kept)

    return Intent(
        raw_query=request.query,
        product=product or request.query,
        keywords=keywords,
        specs=specs,
        category=category,
        budget_min=budget_min,
        budget_max=budget_max,
        must_have=must_have,
        exclude=list(dict.fromkeys(exclude)),
        source="heuristic",
    )


def _parse_llm_json(content: str) -> dict | None:
    content = content.strip()
    content = re.sub(r"^```(?:json)?|```$", "", content, flags=re.MULTILINE).strip()
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return None


async def parse_intent(request: SearchRequest, settings: Settings) -> Intent:
    """Heurística sempre roda; o LLM (se configurado) refina o resultado."""
    base = heuristic_intent(request)
    if not settings.llm_enabled:
        return base

    system = (
        "Você é o Agente de Intenção de um squad de compras. "
        "Leia o pedido do usuário e devolva SOMENTE JSON válido, sem markdown, com as chaves: "
        "product (string curta, o produto principal), keywords (array de strings), "
        "specs (array com especificações técnicas citadas), category (string ou null), "
        "budget_min (número ou null), budget_max (número ou null), "
        "must_have (array), exclude (array), notes (string curta ou null). "
        "Valores em reais. Não invente especificações que não estejam no texto."
    )
    payload = {
        "model": settings.openai_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": request.query},
        ],
        "temperature": 0.1,
        "max_tokens": 500,
    }

    try:
        async with httpx.AsyncClient(timeout=min(settings.request_timeout + 6, 30)) as client:
            response = await client.post(
                f"{settings.openai_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json=payload,
            )
        if response.status_code >= 400:
            base.notes = "IA indisponível; usei a interpretação local."
            return base
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        parsed = _parse_llm_json(content)
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        base.notes = "IA indisponível; usei a interpretação local."
        return base

    if not parsed:
        base.notes = "IA retornou formato inesperado; usei a interpretação local."
        return base

    def _list(value) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()][:8]

    product = str(parsed.get("product") or "").strip()
    specs = list(dict.fromkeys(base.specs + _list(parsed.get("specs"))))[:6]
    keywords = list(dict.fromkeys(base.keywords + _list(parsed.get("keywords"))))[:14]
    category = parsed.get("category")
    llm_min = parsed.get("budget_min")
    llm_max = parsed.get("budget_max")

    def _num(value) -> float | None:
        try:
            number = float(value)  # type: ignore[arg-type]
            return number if number >= 0 else None
        except (TypeError, ValueError):
            return None

    return Intent(
        raw_query=request.query,
        product=product or base.product,
        keywords=keywords,
        specs=specs,
        category=str(category).strip() if category else base.category,
        budget_min=request.budget_min if request.budget_min is not None else (_num(llm_min) or base.budget_min),
        budget_max=request.budget_max if request.budget_max is not None else (_num(llm_max) or base.budget_max),
        must_have=list(dict.fromkeys(base.must_have + _list(parsed.get("must_have"))))[:6],
        exclude=list(dict.fromkeys(base.exclude + _list(parsed.get("exclude"))))[:6],
        source="llm",
        notes=str(parsed.get("notes")).strip() if parsed.get("notes") else None,
    )
