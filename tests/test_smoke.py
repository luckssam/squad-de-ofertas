"""Testes de fumaça do Squad de Ofertas (rodar: python -m unittest discover -s tests)."""
from __future__ import annotations

import re
import unittest

from agents.curator import curate
from agents.intent import heuristic_intent
from connectors.demo import DemoConnector
from core.models import Intent, Offer, SearchRequest
from core.utils import normalize_specs, parse_price


class PriceTests(unittest.TestCase):
    def test_parse_brazilian_prices(self) -> None:
        self.assertEqual(parse_price("R$ 1.299,00"), 1299.0)
        self.assertEqual(parse_price("4.000"), 4000.0)
        self.assertEqual(parse_price("1299.90"), 1299.9)
        self.assertEqual(parse_price("R$ 89"), 89.0)
        self.assertIsNone(parse_price("grátis"))


class IntentTests(unittest.TestCase):
    def test_budget_and_specs(self) -> None:
        intent = heuristic_intent(
            SearchRequest(query="notebook i5 com 16GB e SSD 512GB até R$ 4.000")
        )
        self.assertEqual(intent.budget_max, 4000.0)
        self.assertEqual(intent.category, "Notebook")
        self.assertIn("i5", intent.specs)
        self.assertIn("16GB", intent.specs)
        self.assertEqual(intent.product, "notebook")

    def test_product_drops_orphan_memory_tokens(self) -> None:
        intent = heuristic_intent(
            SearchRequest(query="notebook 16GB RAM SSD 512GB até 4000")
        )
        self.assertEqual(intent.product, "notebook")

    def test_battery_hours_are_not_budget(self) -> None:
        intent = heuristic_intent(
            SearchRequest(query="fone bluetooth com até 40h de bateria")
        )
        self.assertIsNone(intent.budget_max)
        self.assertIn("bluetooth", " ".join(intent.specs).lower())

    def test_thousands_and_range(self) -> None:
        intent = heuristic_intent(SearchRequest(query="celular abaixo de 2 mil"))
        self.assertEqual(intent.budget_max, 2000.0)
        intent = heuristic_intent(
            SearchRequest(query="tênis para corrida entre 200 e 400 sem couro")
        )
        self.assertEqual((intent.budget_min, intent.budget_max), (200.0, 400.0))
        self.assertIn("couro", intent.exclude)

    def test_wireless_is_spec_not_exclusion(self) -> None:
        intent = heuristic_intent(SearchRequest(query="quero um fone sem fio"))
        self.assertEqual(intent.exclude, [])
        self.assertIn("sem fio", intent.specs)

    def test_spec_dedupe(self) -> None:
        self.assertEqual(normalize_specs(["512GB", "SSD 512GB", "16GB", "16GB"]), ["SSD 512GB", "16GB"])


def _offer(**overrides) -> Offer:
    base = dict(
        id="x1",
        source="demo",
        source_label="Demonstração",
        title="Notebook Teste i5 16GB",
        price=3000.0,
        url="https://example.com",
        rating=4.7,
        reviews=120,
        shipping_free=True,
        is_demo=True,
    )
    base.update(overrides)
    return Offer(**base)


class CuratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = SearchRequest(query="notebook i5 até 4000", budget_max=4000)

    def test_filters_budget_and_marks_over_budget_fallback(self) -> None:
        intent = Intent(raw_query="notebook", product="notebook", budget_max=4000)
        offers = [_offer(id="a", price=3500), _offer(id="b", price=6000, title="Notebook Outro i5")]
        result, meta = curate(offers, intent, self.request)
        self.assertEqual([offer.id for offer in result], ["a"])
        self.assertEqual(meta["over_budget"], 1)

        empty, meta2 = curate([_offer(id="b", price=6000)], intent, self.request)
        self.assertEqual(len(empty), 1)
        self.assertTrue(empty[0].over_budget)
        self.assertTrue(meta2["relaxed"])

    def test_deduplicates_similar_titles(self) -> None:
        intent = Intent(raw_query="notebook", product="notebook")
        offers = [
            _offer(id="a", price=3200, title="Notebook Dell Inspiron 15 i5 16GB"),
            _offer(id="b", price=3100, title="Notebook Dell Inspiron 15 i5 16GB"),
            _offer(id="c", price=3300, title="Notebook Lenovo IdeaPad 3 i5 16GB"),
        ]
        result, meta = curate(offers, intent, self.request)
        self.assertEqual(len(result), 2)
        self.assertEqual(meta["duplicates_removed"], 1)


class DemoTests(unittest.IsolatedAsyncioTestCase):
    async def test_demo_returns_offers(self) -> None:
        connector = DemoConnector()
        intent = heuristic_intent(SearchRequest(query="air fryer 5L de 1500W"))
        offers = await connector.search(intent, 12)
        self.assertGreaterEqual(len(offers), 12)
        self.assertTrue(all(offer.is_demo for offer in offers))
        self.assertTrue(all(offer.price > 0 for offer in offers))

    async def test_demo_titles_do_not_repeat_measurements(self) -> None:
        connector = DemoConnector()
        intent = heuristic_intent(
            SearchRequest(query="notebook 16GB RAM SSD 512GB até 4000")
        )
        offers = await connector.search(intent, 20)
        measure = re.compile(r"\d+\s?(?:gb|tb|mb|pol|polegadas|hz|w|mah|ml|kg|cm|mm|mp|fps|dpi)")
        for offer in offers:
            found = [m.replace(" ", "") for m in measure.findall(offer.title.lower())]
            repeated = {m for m in found if found.count(m) > 1}
            self.assertFalse(repeated, f"Medida repetida em: {offer.title}")


if __name__ == "__main__":
    unittest.main()
