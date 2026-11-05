"""Conector de demonstração.

Gera ofertas plausíveis e determinísticas para qualquer consulta, permitindo
testar todo o fluxo do squad sem depender de chaves de API.
"""
from __future__ import annotations

import random
import re
from datetime import datetime

from connectors.base import Connector
from core.models import Intent, Offer
from core.utils import compact, normalize_text, short_hash, token_set

MEASURE_PATTERN = re.compile(
    r"\d+\s?(?:gb|tb|mb|pol|polegadas|hz|w|mah|ml|litros|kg|cm|mm|mp|fps|dpi|bar|kpa|marchas|aro)"
)
GENERIC_SPEC_WORDS = {"tela", "processador", "capacidade", "memoria", "sistema"}


def _spec_is_covered(title: str, spec: str) -> bool:
    """Evita repetir uma especificação que o título já mostra (ex.: 512GB SSD 512GB)."""
    normalized_spec = normalize_text(spec)
    if not normalized_spec:
        return True
    if normalized_spec in normalize_text(title) or compact(spec) in compact(title):
        return True

    spec_tokens = token_set(spec) - GENERIC_SPEC_WORDS
    title_tokens = token_set(title) - GENERIC_SPEC_WORDS
    if spec_tokens and spec_tokens <= title_tokens:
        return True

    spec_measures = {measure.replace(" ", "") for measure in MEASURE_PATTERN.findall(normalized_spec)}
    title_measures = {
        measure.replace(" ", "") for measure in MEASURE_PATTERN.findall(normalize_text(title))
    }
    return bool(spec_measures & title_measures)

CATEGORIES = [
    {
        "id": "fone",
        "label": "fone de ouvido",
        "match": ["fone", "headphone", "headset", "earbud", "airpod", "buds", "audio"],
        "brands": {
            "JBL": ["Tune 520BT", "Live 460NC", "Wave Buds"],
            "Anker Soundcore": ["P20i", "Life Q30", "Motion 300"],
            "Xiaomi": ["Redmi Buds 5", "Buds 4 Lite"],
            "Edifier": ["W820NB Plus", "X2s"],
            "Sony": ["WH-CH520", "WF-C500"],
            "Logitech": ["Zone Vibe 100", "G335"],
        },
        "base": 259.0,
        "specs": ["Bluetooth 5.3", "cancelamento de ruído", "até 40h de bateria", "microfone integrado"],
    },
    {
        "id": "notebook",
        "label": "notebook",
        "match": ["notebook", "laptop", "ultrabook", "macbook"],
        "brands": {
            "Dell": ["Inspiron 15", "Vostro 14", "G15"],
            "Lenovo": ["IdeaPad 3", "ThinkPad E14", "Legion 5"],
            "Acer": ["Aspire 5", "Nitro V15"],
            "ASUS": ["Vivobook 15", "Zenbook 14"],
            "Samsung": ["Galaxy Book4", "Book4 Pro"],
            "Apple": ["MacBook Air M2", "MacBook Pro M3"],
        },
        "base": 3899.0,
        "specs": ["8GB RAM", "16GB RAM", "SSD 512GB", "tela Full HD", "processador i5", "Windows 11"],
    },
    {
        "id": "celular",
        "label": "celular",
        "match": ["celular", "smartphone", "iphone", "galaxy", "motorola", "xiaomi", "redmi"],
        "brands": {
            "Samsung": ["Galaxy A55", "Galaxy S23 FE"],
            "Xiaomi": ["Redmi Note 13", "Poco X6"],
            "Motorola": ["Moto G84", "Edge 40"],
            "Apple": ["iPhone 13", "iPhone 15"],
            "Realme": ["12 Pro", "C55"],
        },
        "base": 2099.0,
        "specs": ["128GB", "256GB", "8GB RAM", "câmera 50MP", "bateria 5000mAh", "5G"],
    },
    {
        "id": "smartwatch",
        "label": "smartwatch",
        "match": ["smartwatch", "relogio", "watch", "pulseira"],
        "brands": {
            "Xiaomi": ["Redmi Watch 4", "Smart Band 8"],
            "Samsung": ["Galaxy Fit 3", "Galaxy Watch 6"],
            "Huawei": ["Watch Fit 3", "Watch GT 4"],
            "Amazfit": ["Bip 5", "GTS 4"],
            "Apple": ["Watch SE", "Watch Series 9"],
        },
        "base": 449.0,
        "specs": ["GPS integrado", "monitor cardíaco", "à prova d'água", "tela AMOLED", "bateria 14 dias"],
    },
    {
        "id": "airfryer",
        "label": "air fryer",
        "match": ["airfryer", "air fryer", "fritadeira", "fritadeira eletrica"],
        "brands": {
            "Mondial": ["AFN-40-BI", "AFN-50-BI"],
            "Philips Walita": ["Essential Airfryer", "Airfryer XXL"],
            "Electrolux": ["ECE01", "EAF20"],
            "Consul": ["CFO11", "CFF20"],
            "Britânia": ["BFR-15", "BAF40"],
        },
        "base": 429.0,
        "specs": ["capacidade 4L", "capacidade 5L", "temporizador digital", "antiaderente", "1500W"],
    },
    {
        "id": "cafeteira",
        "label": "cafeteira",
        "match": ["cafeteira", "cafe", "nespresso", "dolce gusto", "espresso"],
        "brands": {
            "Nespresso": ["Essenza Mini", "Vertuo Pop"],
            "Dolce Gusto": ["Genio S", "Mini Me"],
            "Philips": ["Daily", "3200 Series"],
            "Oster": ["Xpert", "PrimaLatte"],
            "Electrolux": ["Cream", "Expression"],
        },
        "base": 369.0,
        "specs": ["15 bar", "cápsulas", "reservatório 1L", "desligamento automático", "prepara 2 xícaras"],
    },
    {
        "id": "tenis",
        "label": "tênis",
        "match": ["tenis", "sapato", "chinelo", "sneaker"],
        "brands": {
            "Nike": ["Revolution 7", "Runfalcon 5", "Air Winflo"],
            "Adidas": ["Runfalcon 3.0", "Duramo"],
            "Puma": ["Flyer Runner", "Softride"],
            "Mizuno": ["Wave Light", "Wave Equate"],
            "Olympikus": ["Corre 3", "Corre Max"],
        },
        "base": 359.0,
        "specs": ["amortecimento", "cabo de algodão", "solado em borracha", "leve", "para corrida"],
    },
    {
        "id": "monitor",
        "label": "monitor",
        "match": ["monitor", "tela", "display"],
        "brands": {
            "LG": ["24MR400", "27MP400"],
            "Samsung": ["Odyssey G3", "T350"],
            "AOC": ["24B1H", "27G2"],
            "Dell": ["P2422H", "S2421HN"],
            "Philips": ["241V8", "275V8"],
        },
        "base": 899.0,
        "specs": ["24 polegadas", "27 polegadas", "Full HD", "75Hz", "IPS", "HDMI"],
    },
    {
        "id": "teclado",
        "label": "teclado",
        "match": ["teclado", "keyboard", "mecanico"],
        "brands": {
            "Logitech": ["K120", "MX Keys Mini"],
            "Redragon": ["Kumara K552", "Fizz K617"],
            "Razer": ["BlackWidow V4", "Huntsman Mini"],
            "Keychron": ["K8", "K3"],
            "Corsair": ["K55 RGB", "K70"],
        },
        "base": 259.0,
        "specs": ["mecânico", "ABNT2", "RGB", "switch azul", "wireless"],
    },
    {
        "id": "mouse",
        "label": "mouse",
        "match": ["mouse", "mouses"],
        "brands": {
            "Logitech": ["G203", "M170"],
            "Razer": ["DeathAdder Essential", "Viper Mini"],
            "Redragon": ["Cobra", "Griffin"],
            "HyperX": ["Pulsefire", "Haste"],
            "Multilaser": ["Sem Fio", "Gamer"],
        },
        "base": 149.0,
        "specs": ["16000 DPI", "sem fio", "RGB", "6 botões", "USB"],
    },
    {
        "id": "cadeira",
        "label": "cadeira",
        "match": ["cadeira", "poltrona", "gamer chair"],
        "brands": {
            "ThunderX3": ["TC3", "Core"],
            "DXRacer": ["Racing", "Prince"],
            "Elements": ["Sophie", "Gamer"],
            "Flexform": ["Unite", "Ergoflex"],
            "Husky": ["Gaming 700", "Office"],
        },
        "base": 899.0,
        "specs": ["encosto reclinável", "apoio de braço", "gás pistão", "couro sintético", "até 120kg"],
    },
    {
        "id": "aspirador",
        "label": "aspirador",
        "match": ["aspirador", "aspirador de po", "robo", "vacuo"],
        "brands": {
            "Electrolux": ["Vertical", "Ergorapid"],
            "Philips": ["PowerPro", "Compact"],
            "Mondial": ["Ergo", "Turbo"],
            "Wap": ["Rapid", "Vertical"],
            "Xiaomi": ["Robot Vacuum", "Vacuum Cleaner"],
        },
        "base": 949.0,
        "specs": ["2 em 1", "sem saco", "HEPA", "20kPa", "bateria 40 min", "controle remoto"],
    },
    {
        "id": "tv",
        "label": "tv",
        "match": ["tv", "televisao", "smart tv", "oled"],
        "brands": {
            "Samsung": ["Crystal UHD", "Q60D"],
            "LG": ["OLED evo", "UR8750"],
            "TCL": ["P635", "C655"],
            "Philco": ["Vision", "Roku TV"],
            "Philips": ["Ambilight", "4K"],
        },
        "base": 2499.0,
        "specs": ["55 polegadas", "65 polegadas", "4K", "HDR10+", "Smart TV", "120Hz"],
    },
    {
        "id": "tablet",
        "label": "tablet",
        "match": ["tablet", "ipad"],
        "brands": {
            "Samsung": ["Galaxy Tab S9", "Tab A9+"],
            "Apple": ["iPad 10", "iPad Air"],
            "Lenovo": ["Tab M11", "Tab P12"],
            "Xiaomi": ["Pad 6", "Redmi Pad"],
            "Positivo": ["Twist", "Vision"],
        },
        "base": 1799.0,
        "specs": ["128GB", "8GB RAM", "tela 11 polegadas", "Wi-Fi", "com caneta"],
    },
    {
        "id": "caixa_som",
        "label": "caixa de som",
        "match": ["caixa de som", "speaker", "soundbar", "jbl"],
        "brands": {
            "JBL": ["Go 4", "Charge 5", "Flip 6"],
            "Sony": ["SRS-XB100", "SRS-XG300"],
            "Anker": ["Soundcore 3", "Motion Boom"],
            "Philips": ["TAB5105", "TAB5305"],
            "LG": ["XBOOM", "Party Link"],
        },
        "base": 419.0,
        "specs": ["Bluetooth", "à prova d'água", "até 12h de bateria", "40W", "portátil"],
    },
    {
        "id": "webcam",
        "label": "webcam",
        "match": ["webcam", "camera"],
        "brands": {
            "Logitech": ["C920", "Brio 500"],
            "HP": ["320", "960"],
            "Kaidan": ["Full HD", "Pro"],
            "Multilaser": ["WC045", "Full HD"],
            "Razer": ["Kiyo", "Kiyo Pro"],
        },
        "base": 399.0,
        "specs": ["1080p", "30fps", "microfone embutido", "foco automático", "USB"],
    },
    {
        "id": "impressora",
        "label": "impressora",
        "match": ["impressora", "multifuncional", "printer"],
        "brands": {
            "Epson": ["EcoTank L3250", "EcoTank L4260"],
            "HP": ["Smart Tank 581", "DeskJet 2774"],
            "Brother": ["DCP-L2540DW", "HL-L2352DW"],
            "Canon": ["G3110", "Pixma TS3522"],
            "Samsung": ["Xpress M2020", "ProXpress"],
        },
        "base": 949.0,
        "specs": ["Wi-Fi", "multifuncional", "tanque de tinta", "frente e verso", "impressão colorida"],
    },
    {
        "id": "bike",
        "label": "bicicleta",
        "match": ["bicicleta", "bike", "mtb"],
        "brands": {
            "Caloi": ["Explorer", "Elite"],
            "Oggi": ["Hacker", "Big Wheel"],
            "Sense": ["Move", "Rock"],
            "Mormaii": ["Bora", "29er"],
            "Nathor": ["Big Wheel", "Mountain"],
        },
        "base": 1899.0,
        "specs": ["aro 29", "aro 26", "21 marchas", "freio a disco", "quadro de alumínio"],
    },
]

KNOWN_BRANDS = [
    "Dell", "Lenovo", "Acer", "ASUS", "Samsung", "Apple", "Xiaomi", "Motorola",
    "Realme", "JBL", "Sony", "Edifier", "Logitech", "Razer", "Redragon", "Keychron",
    "Corsair", "HyperX", "Nike", "Adidas", "Puma", "Mizuno", "Olympikus", "LG", "AOC",
    "Philips", "Mondial", "Electrolux", "Consul", "Britânia", "Nespresso",
    "Dolce Gusto", "Oster", "Caloi", "Oggi", "Sense", "Mormaii", "Nathor", "TCL",
    "Philco", "Positivo", "Huawei", "Amazfit", "ThunderX3", "DXRacer", "Flexform",
    "Husky", "Wap", "Epson", "HP", "Brother", "Canon", "Anker", "Multilaser", "Kaidan",
]

BRAND_PREMIUM = {
    "Apple": 1.6, "Samsung": 1.12, "Dell": 1.1, "Lenovo": 1.05, "ASUS": 1.12,
    "Acer": 0.92, "Sony": 1.2, "Anker": 0.95, "Anker Soundcore": 0.95, "Xiaomi": 0.9,
    "Edifier": 0.85, "Razer": 1.25, "Redragon": 0.8, "Keychron": 1.2, "Corsair": 1.2,
    "HyperX": 1.1, "Motorola": 0.95, "Realme": 0.85, "Huawei": 1.1, "Amazfit": 0.9,
    "Nike": 1.15, "Adidas": 1.1, "Puma": 0.95, "Mizuno": 1.05, "Olympikus": 0.8,
    "LG": 1.1, "AOC": 0.85, "Philips": 1.05, "Mondial": 0.8, "Electrolux": 1.05,
    "Consul": 0.85, "Britânia": 0.75, "Nespresso": 1.4, "Dolce Gusto": 1.0, "Oster": 1.0,
    "ThunderX3": 1.1, "DXRacer": 1.3, "Elements": 0.9, "Flexform": 1.0, "Husky": 1.0,
    "Wap": 0.9, "TCL": 0.85, "Philco": 0.8, "Positivo": 0.7, "Caloi": 1.0, "Oggi": 1.0,
    "Sense": 0.95, "Mormaii": 0.9, "Nathor": 0.8, "Epson": 1.1, "HP": 1.05,
    "Brother": 1.1, "Canon": 1.05,
}

STORES = [
    ("Magazine Demo", 0.98),
    ("TechShop", 0.96),
    ("MegaStore", 1.03),
    ("PrimeBuy", 1.01),
    ("Loja Express", 0.94),
]

SUFFIXES = ["", "", " 2025", " Pro", " Plus", " Kit 2 un.", " Edição Especial"]


def _pick_category(query: str) -> dict:
    normalized = f" {normalize_text(query)} "
    for category in CATEGORIES:
        for term in category["match"]:
            if f" {normalize_text(term)} " in normalized:
                return category
    for category in CATEGORIES:
        if category["id"] in normalized:
            return category
    return {}


def _user_brands(query: str) -> list[str]:
    normalized = normalize_text(query)
    found = []
    for brand in KNOWN_BRANDS:
        if normalize_text(brand) in normalized and brand not in found:
            found.append(brand)
    return found


class DemoConnector(Connector):
    id = "demo"
    label = "Demonstração"

    @property
    def configured(self) -> bool:
        return True

    @property
    def setup_hint(self) -> str:
        return "Sempre disponível: catálogo simulado."

    async def search(self, intent: Intent, limit: int) -> list[Offer]:
        query = intent.raw_query
        category = _pick_category(query)
        seed = int(short_hash(normalize_text(query), 16), 16)
        rng = random.Random(seed)
        now = datetime.now()

        base = float(category.get("base", 299.0))
        brand_map: dict[str, list[str]] = category.get("brands") or {
            "Genérico": ["Modelo S", "Modelo X"],
            "NovaTech": ["Series 5", "Edition 2"],
            "MaxLine": ["Compact", "Plus"],
            "Prime": ["Essential", "Pro"],
            "Ultra": ["One", "Max"],
        }
        pool_specs = category.get("specs") or ["original", "garantia 12 meses", "alta qualidade"]

        user_brands = _user_brands(query)
        brands = user_brands + [brand for brand in brand_map if brand not in user_brands]
        if not brands:
            brands = ["Genérico"]

        specs_from_query = [spec for spec in (intent.specs + intent.must_have) if spec][:4]
        display_specs = list(dict.fromkeys(specs_from_query + pool_specs))

        factors = [0.74, 0.82, 0.88, 0.95, 1.0, 1.06, 1.14, 1.24, 1.33]
        total = 20
        offers: list[Offer] = []
        used_titles: set[str] = set()

        for index in range(total):
            brand = brands[index % len(brands)]
            models = brand_map.get(brand) or ["Modelo S", "Modelo X", "Pro"]
            model = models[(index // max(len(brands), 1)) % len(models)]
            suffix = SUFFIXES[(index + rng.randint(0, 2)) % len(SUFFIXES)]
            title = f"{brand} {model}{suffix}"
            if category.get("label") and normalize_text(category["label"]) not in normalize_text(title):
                title = f"{title} — {category['label'].capitalize()}"
            if display_specs:
                title_spec = display_specs[index % len(display_specs)]
                if title_spec and len(title_spec) <= 30 and not _spec_is_covered(title, title_spec):
                    title = f"{title} {title_spec}"
                if index % 3 == 0 and len(display_specs) > 1:
                    extra_spec = display_specs[(index + 3) % len(display_specs)]
                    if (
                        extra_spec
                        and extra_spec != title_spec
                        and len(extra_spec) <= 30
                        and not _spec_is_covered(title, extra_spec)
                    ):
                        title = f"{title} {extra_spec}"
            if title in used_titles:
                title = f"{title} {now.year}"
            used_titles.add(title)

            store, store_factor = STORES[(index + rng.randint(0, 3)) % len(STORES)]
            premium = BRAND_PREMIUM.get(brand, 1.0)
            price = base * premium * factors[index % len(factors)] * store_factor
            price *= rng.uniform(0.94, 1.06)
            price = round(price) - 0.10 if price > 100 else round(price, 2)
            price = max(price, 19.9)

            rating = round(
                rng.choice([4.0, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9]) + rng.uniform(-0.15, 0.1), 1
            )
            rating = min(5.0, max(3.6, rating))
            reviews = int(rng.choice([0, 3, 12, 28, 64, 140, 320, 780, 1500, 2400, 3800]) * rng.uniform(0.7, 1.3))
            free = rng.random() < 0.62
            installments_count = rng.choice([10, 12])
            installment_value = f"{price / installments_count:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            installments = f"em até {installments_count}x de R$ {installment_value}"

            offers.append(
                Offer(
                    id=f"demo-{category.get('id', 'generico')}-{index}-{short_hash(title + store, 6)}",
                    source=self.id,
                    source_label=self.label,
                    title=title,
                    price=price,
                    currency="BRL",
                    url=f"https://example.com/ofertas/{normalize_text(title).replace(' ', '-')[:60]}",
                    image=None,
                    rating=rating,
                    reviews=reviews,
                    seller=store,
                    shipping_free=free,
                    installments=installments,
                    condition="novo",
                    location=rng.choice(["São Paulo, SP", "Rio de Janeiro, RJ", "Curitiba, PR", "Minas Gerais"]),
                    is_demo=True,
                )
            )

        rng.shuffle(offers)
        return offers[: max(limit, 12)]
