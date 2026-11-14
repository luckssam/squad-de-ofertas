"""Filtros de atributos para manter a busca fiel ao que foi pedido.

Quando o usuário pede "PLA Silk Dourado", as lojas devolvem o mesmo produto em
outras cores (e às vezes outro material). Este módulo identifica cor e material
no título da oferta e permite descartar o que claramente não corresponde.
"""
from __future__ import annotations

import re

from core.models import Intent
from core.utils import normalize_text, tokens

# Grupo -> formas aceitas (sem acento, minúsculas). "ouro velho" etc. contam como dourado.
COLOR_GROUPS: dict[str, tuple[str, ...]] = {
    "dourado": ("dourado", "dourada", "ouro", "gold", "golden", "dorado", "dorada", "ouro velho", "ouro envelhecido"),
    "prata": ("prata", "prateado", "prateada", "silver", "inox", "cromado", "cromo"),
    "preto": ("preto", "preta", "black"),
    "branco": ("branco", "branca", "white"),
    "cinza": ("cinza", "acinzentado", "acinzentada", "gray", "grey", "grafite", "chumbo", "granito"),
    "azul": ("azul", "blue"),
    "vermelho": ("vermelho", "vermelha", "red", "rubi", "vinho", "bordo"),
    "verde": ("verde", "green", "esmeralda"),
    "amarelo": ("amarelo", "amarela", "yellow", "ambar"),
    "rosa": ("rosa", "pink", "rose"),
    "roxo": ("roxo", "roxa", "purple", "violeta", "lilas"),
    "laranja": ("laranja", "orange"),
    "marrom": ("marrom", "brown", "cobre", "bronze", "caramelo"),
    "transparente": ("transparente", "cristal", "clear"),
}

# Marcas de que o produto mistura várias cores (não é uma cor só).
MULTI_COLOR_MARKERS = (
    "multicolor",
    "multicor",
    "tricolor",
    "tri color",
    "bicolor",
    "bi color",
    "duo color",
    "duocolor",
    "colorido",
    "colorida",
    "rainbow",
    "arco iris",
)

MATERIAL_GROUPS: dict[str, tuple[str, ...]] = {
    "pla": ("pla", "pla+", "pla plus"),
    "petg": ("petg",),
    "abs": ("abs",),
    "tpu": ("tpu",),
    "asa": ("asa",),
    "nylon": ("nylon", "pa6", "pa12"),
    "resina": ("resina",),
}

# Categorias conhecidas: o pedido é reconhecido pelo nome e o título da oferta
# pode usar qualquer sinônimo da mesma categoria (air fryer = fritadeira).
CATEGORY_HINTS: dict[str, tuple[str, ...]] = {
    "Fone de ouvido": ("fone", "headphone", "headset", "earbud", "airpod", "buds"),
    "Notebook": ("notebook", "laptop", "ultrabook", "macbook"),
    "Celular": ("celular", "smartphone", "iphone", "galaxy", "redmi", "moto g", "pixel"),
    "Smartwatch": ("smartwatch", "relogio inteligente", "apple watch", "mi band"),
    "Air fryer": ("air fryer", "airfryer", "fritadeira"),
    "Cafeteira": ("cafeteira", "nespresso", "dolce gusto", "espresso"),
    "Tênis": ("tenis", "sapato", "sneaker", "chuteira"),
    "Monitor": ("monitor", "display"),
    "Teclado": ("teclado", "keyboard"),
    "Mouse": ("mouse"),
    "Cadeira": ("cadeira", "poltrona"),
    "Aspirador": ("aspirador", "robo aspirador"),
    "TV": ("smart tv", "televisao", " tv "),
    "Tablet": ("tablet", "ipad"),
    "Caixa de som": ("caixa de som", "soundbar", "speaker"),
    "Webcam": ("webcam",),
    "Impressora": ("impressora", "multifuncional"),
    "Bicicleta": ("bicicleta", "bike", "mtb"),
    "Camiseta": ("camiseta", "camisa", "t-shirt", "tshirt"),
    "Mochila": ("mochila", "backpack"),
    "Panela": ("panela", "frigideira", "jogo de panelas", "cacarola", "caçarola"),
    "Filamento 3D": ("filamento", "filament", "pla", "petg", "abs", "tpu"),
}

# Marcas comuns no varejo brasileiro. Servem só para não deixar passar
# concorrente quando o usuário pediu uma marca específica.
BRANDS: dict[str, tuple[str, ...]] = {
    "philips": ("philips", "walita"),
    "mondial": ("mondial",),
    "oster": ("oster",),
    "philco": ("philco",),
    "cadence": ("cadence",),
    "arno": ("arno",),
    "britania": ("britania",),
    "electrolux": ("electrolux",),
    "consul": ("consul",),
    "brastemp": ("brastemp",),
    "midea": ("midea",),
    "wap": ("wap",),
    "tramontina": ("tramontina",),
    "taurus": ("taurus",),
    "samsung": ("samsung", "galaxy"),
    "lg": ("lg",),
    "xiaomi": ("xiaomi", "redmi", "poco"),
    "motorola": ("motorola", "moto g", "moto e"),
    "apple": ("apple", "iphone", "ipad", "macbook", "airpods"),
    "google": ("google", "pixel", "nest"),
    "jbl": ("jbl",),
    "sony": ("sony",),
    "lenovo": ("lenovo", "thinkpad", "ideapad"),
    "dell": ("dell",),
    "acer": ("acer",),
    "asus": ("asus",),
    "hp": ("hp",),
    "positivo": ("positivo",),
    "multilaser": ("multilaser",),
    "logitech": ("logitech",),
    "redragon": ("redragon",),
    "hyperx": ("hyperx",),
    "razer": ("razer",),
    "corsair": ("corsair",),
    "kingston": ("kingston",),
    "sandisk": ("sandisk",),
    "nike": ("nike",),
    "adidas": ("adidas",),
    "puma": ("puma",),
    "mizuno": ("mizuno",),
    "asics": ("asics",),
    "fila": ("fila",),
    "under armour": ("under armour",),
    "new balance": ("new balance",),
    "olympikus": ("olympikus",),
    "skechers": ("skechers",),
    "vans": ("vans",),
    "hering": ("hering",),
    "insider": ("insider",),
    "creality": ("creality",),
    "anycubic": ("anycubic",),
    "elegoo": ("elegoo",),
    "sunlu": ("sunlu",),
    "voolt3d": ("voolt3d", "voolt"),
    "masterprint": ("masterprint",),
    "cliever": ("cliever",),
    "3dfila": ("3dfila", "3d fila"),
    "gtmax": ("gtmax",),
    "seta3d": ("seta3d", "seta 3d"),
    "flashforge": ("flashforge",),
    "bambu lab": ("bambu lab", "bambu"),
}

# Rótulos que o LLM costuma colar nas specs ("cor: dourado", "material PLA").
SPEC_LABEL_RE = re.compile(
    r"^\s*(?:material|cor|acabamento|marca|modelo|tipo|tamanho|capacidade|"
    r"voltagem|potencia|peso|medida)\s*[:=]?\s+",
    re.IGNORECASE,
)


def clean_spec(value: str) -> str:
    """Remove rótulos como 'cor:' / 'material ' de uma especificação."""
    text = " ".join(str(value or "").split())
    previous = None
    while previous != text:
        previous = text
        text = SPEC_LABEL_RE.sub("", text, count=1).strip()
    return text.strip(" .,;:-")


def _term_in(term: str, text: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) is not None


def _groups_in(text: str, groups: dict[str, tuple[str, ...]]) -> set[str]:
    normalized = normalize_text(text)
    found: set[str] = set()
    for name, terms in groups.items():
        if any(_term_in(term, normalized) for term in terms):
            found.add(name)
    return found


def colors_in(text: str) -> set[str]:
    return _groups_in(text, COLOR_GROUPS)


def materials_in(text: str) -> set[str]:
    return _groups_in(text, MATERIAL_GROUPS)


def _intent_text(intent: Intent) -> str:
    parts = [intent.raw_query, intent.product, *intent.specs, *intent.must_have]
    return " ".join(part for part in parts if part)


def required_colors(intent: Intent) -> set[str]:
    return colors_in(_intent_text(intent))


def required_materials(intent: Intent) -> set[str]:
    return materials_in(_intent_text(intent))


def brands_in(text: str) -> set[str]:
    return _groups_in(text, BRANDS)


def required_brands(intent: Intent) -> set[str]:
    return brands_in(_intent_text(intent))


GENERIC_PRODUCT_TOKENS = {
    "produto", "produtos", "original", "novo", "nova", "kit", "unidade",
    "impressao", "impressora", "para", "com",
}


def _group_terms(groups: dict[str, tuple[str, ...]], names: set[str]) -> set[str]:
    return {term for name in names for term in groups.get(name, ())}


def required_product_tokens(intent: Intent) -> list[str]:
    """Palavras do produto que deveriam aparecer no título (fora as cores).

    Só é usado quando a busca pede um material específico (ex.: PLA), para não
    deixar passar produto de outro tipo que só coincidiu na cor.
    """
    blocked = _group_terms(COLOR_GROUPS, required_colors(intent))
    blocked |= _group_terms(BRANDS, required_brands(intent))
    result: list[str] = []
    for token in tokens(intent.product):
        if len(token) < 3 or token in GENERIC_PRODUCT_TOKENS:
            continue
        if token in blocked:
            continue
        result.append(token)
    return result


def required_type_terms(intent: Intent) -> list[str]:
    """Palavras que identificam o TIPO de produto pedido.

    Junta as palavras do produto com os sinônimos da categoria conhecida
    ("air fryer" aceita "fritadeira"), para não penalizar título legítimo.
    """
    blocked = _group_terms(COLOR_GROUPS, required_colors(intent))
    blocked |= _group_terms(MATERIAL_GROUPS, required_materials(intent))
    blocked |= _group_terms(BRANDS, required_brands(intent))
    blocked |= GENERIC_PRODUCT_TOKENS

    terms: list[str] = []
    for token in tokens(intent.product):
        if len(token) < 3 or token in blocked:
            continue
        terms.append(token)
    if intent.category:
        requested_brand_terms = _group_terms(BRANDS, required_brands(intent))
        all_brand_terms = {term for items in BRANDS.values() for term in items}
        for hint in CATEGORY_HINTS.get(intent.category, ()):
            # "iphone" não serve de tipo para quem pediu "galaxy".
            if hint in all_brand_terms and hint not in requested_brand_terms:
                continue
            terms.append(hint)
    return list(dict.fromkeys(term for term in terms if term))


def type_in(title: str, terms: list[str]) -> bool:
    """O título cita algum sinônimo do tipo pedido (aceita plural)."""
    normalized = normalize_text(title)
    for term in terms:
        if not term:
            continue
        if _term_in(term, normalized):
            return True
        if len(term) >= 4 and (
            _term_in(f"{term}s", normalized) or _term_in(f"{term}es", normalized)
        ):
            return True
    return False


def brand_mismatch(title: str, brands: set[str]) -> bool:
    """True quando o título cita marca(s) e nenhuma delas é a pedida.

    Título que cita a marca pedida junto de outra (acessório compatível) passa.
    """
    if not brands:
        return False
    found = brands_in(title)
    return bool(found) and not (found & brands)


def is_multi_color(text: str) -> bool:
    normalized = normalize_text(text)
    return any(_term_in(marker, normalized) for marker in MULTI_COLOR_MARKERS)


def mismatch_reason(
    title: str,
    colors: set[str],
    materials: set[str],
    product_tokens: list[str] | None = None,
) -> str | None:
    """Devolve o motivo do descarte ("cor" / "material" / "produto") ou None.

    Regras (conservadoras, para não sumir com tudo):
    - sem cor pedida, ou título sem cor -> mantém;
    - cor pedida e o título cita outra(s) cor(s) sem a pedida -> descarta;
    - cor pedida e o título mistura a cor pedida com outras -> descarta;
    - material pedido e o título cita outro material sem o pedido -> descarta;
    - material pedido e o título não cita nem o material nem o produto -> descarta.
    """
    if colors:
        if is_multi_color(title):
            return "cor"
        found = colors_in(title)
        if found:
            if not (found & colors):
                return "cor"
            if found - colors:
                return "cor"

    if materials:
        found_materials = materials_in(title)
        if found_materials:
            if not (found_materials & materials):
                return "material"
            if found_materials - materials:
                return "material"
        elif product_tokens:
            normalized = normalize_text(title)
            if not any(_term_in(token, normalized) for token in product_tokens):
                return "produto"

    return None


def spec_tokens(value: str) -> list[str]:
    return [token for token in tokens(clean_spec(value)) if len(token) >= 2]
