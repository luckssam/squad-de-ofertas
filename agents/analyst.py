"""Agente Analista: compara as ofertas e escreve a recomendação final."""
from __future__ import annotations

import json
import re
import statistics

import httpx

from core.config import Settings
from core.models import Analysis, Intent, Offer, Stats
from core.utils import format_brl


def build_stats(offers: list[Offer]) -> Stats:
    if not offers:
        return Stats()
    prices = [offer.price for offer in offers]
    return Stats(
        count=len(offers),
        min_price=round(min(prices), 2),
        median_price=round(statistics.median(prices), 2),
        max_price=round(max(prices), 2),
        free_shipping_count=sum(1 for offer in offers if offer.shipping_free is True),
        currency="BRL",
    )


def _short(title: str, size: int = 58) -> str:
    return title if len(title) <= size else title[: size - 1].rstrip() + "…"


def _heuristic(
    offers: list[Offer],
    intent: Intent,
    meta: dict,
    source_notes: list[str],
    mode: str,
) -> Analysis:
    stats = build_stats(offers)
    if not offers:
        warning = None
        if meta.get("over_budget") or meta.get("below_budget"):
            warning = "As ofertas encontradas ficaram fora do orçamento informado."
        return Analysis(
            headline="Nenhuma oferta encontrada",
            summary=(
                f"Não encontrei ofertas para “{intent.raw_query}” com os filtros atuais. "
                "Tente remover alguma especificação, ampliar o orçamento ou habilitar mais fontes."
            ),
            warning=warning,
            tips=[
                "Use termos mais gerais, como “notebook i5” em vez do modelo exato.",
                "Amplie a faixa de preço ou deixe o orçamento em branco.",
                "Configure uma fonte real no .env para buscar fora do catálogo de demonstração.",
            ],
            ai=False,
            stats=stats,
        )

    best = max(offers, key=lambda offer: offer.score)
    cheapest = min(offers, key=lambda offer: offer.price)
    rated = [offer for offer in offers if offer.rating]
    best_rated = max(rated, key=lambda offer: (offer.rating or 0, offer.reviews or 0)) if rated else None
    has_demo = any(offer.is_demo for offer in offers)

    summary_parts = []
    if meta.get("relaxed") and intent.budget_max is not None:
        summary_parts.append(
            f"Nenhuma oferta ficou dentro do orçamento de {format_brl(intent.budget_max)}. "
            "As opções abaixo são as mais baratas encontradas acima desse limite."
        )
    summary_parts.append(
        f"Analisei {stats.count} ofertas e a faixa de preço ficou entre "
        f"{format_brl(stats.min_price)} e {format_brl(stats.max_price)} "
        f"(mediana de {format_brl(stats.median_price)})."
    )
    best_line = (
        f"A melhor relação custo-benefício é “{_short(best.title)}”, da {best.source_label}, "
        f"por {format_brl(best.price)}"
    )
    if best.rating:
        best_line += f", nota {best.rating:.1f}/5"
    if best.reviews:
        best_line += f" com {best.reviews} avaliações"
    if best.shipping_free:
        best_line += " e frete grátis"
    best_line += "."
    if best.price_vs_median is not None and best.price_vs_median < -3:
        best_line += f" O preço está {abs(best.price_vs_median):.0f}% abaixo da mediana."
    summary_parts.append(best_line)

    if cheapest.id != best.id:
        summary_parts.append(
            f"O menor preço absoluto é “{_short(cheapest.title)}”, por {format_brl(cheapest.price)}."
        )

    pros: list[str] = []
    if best.shipping_free:
        pros.append("Frete grátis para a oferta principal.")
    if best.rating and best.rating >= 4.5:
        pros.append(f"Nota alta ({best.rating:.1f}/5) com {best.reviews or 0} avaliações.")
    if best.price_vs_median is not None and best.price_vs_median <= -5:
        pros.append(f"Preço {abs(best.price_vs_median):.0f}% abaixo da mediana do resultado.")
    if intent.specs and not best.missing_specs:
        pros.append("Atende todas as especificações informadas.")
    if best.condition:
        pros.append(f"Condição: {best.condition}.")
    if not pros:
        pros.append("Boa pontuação geral entre as ofertas analisadas.")

    cons: list[str] = []
    if best.missing_specs:
        cons.append("Não confirma: " + ", ".join(best.missing_specs[:3]) + ".")
    if best.reviews is not None and best.reviews < 15:
        cons.append("Poucas avaliações — confira a reputação do vendedor.")
    if best.shipping_free is not True:
        cons.append("Frete grátis não confirmado nesta oferta.")
    if meta.get("relaxed") and intent.budget_max is not None:
        cons.append(f"Nenhuma oferta abaixo de {format_brl(intent.budget_max)}.")
    if has_demo:
        cons.append("Inclui ofertas simuladas: valores e lojas são fictícios.")
    if best.over_budget:
        cons.append("Oferta acima do orçamento informado.")

    warning_parts: list[str] = []
    if has_demo:
        warning_parts.append(
            "Este resultado inclui ofertas simuladas. Configure chaves reais no .env "
            "para buscar no Mercado Livre, Amazon ou Google Shopping."
        )
    if meta.get("relaxed") and intent.budget_max is not None:
        warning_parts.append(
            f"Nenhuma oferta dentro de {format_brl(intent.budget_max)}; o filtro de orçamento "
            "foi relaxado para você comparar as opções mais próximas."
        )
    if source_notes:
        warning_parts.append("Algumas fontes falharam: " + " | ".join(source_notes[:2]))
    warning = " ".join(warning_parts) if warning_parts else None

    tips = [
        "Confira a reputação do vendedor e a política de troca antes de comprar.",
        "Compare o preço atual com o histórico dos últimos 30 dias.",
        "Simule o frete para o seu CEP — o valor final pode mudar.",
        "Preços muito abaixo da mediana merecem verificação extra.",
    ]

    return Analysis(
        headline=f"Melhor oferta: {format_brl(best.price)} — {_short(best.title, 46)}",
        summary=" ".join(summary_parts),
        best_pick_id=best.id,
        cheapest_id=cheapest.id,
        best_rated_id=best_rated.id if best_rated else None,
        pros=pros[:4],
        cons=cons[:3],
        tips=tips[:3],
        warning=warning,
        ai=False,
        stats=stats,
    )


def _parse_json(content: str) -> dict | None:
    content = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.MULTILINE).strip()
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return None


async def _llm_analysis(
    offers: list[Offer],
    intent: Intent,
    settings: Settings,
    source_notes: list[str],
    mode: str,
    fallback: Analysis,
) -> Analysis:
    compact_offers = [
        {
            "id": offer.id,
            "titulo": offer.title,
            "preco": offer.price,
            "fonte": offer.source_label,
            "nota": offer.rating,
            "avaliacoes": offer.reviews,
            "frete_gratis": offer.shipping_free,
            "specs_atendidas": offer.matched_specs,
            "specs_faltando": offer.missing_specs,
            "score": offer.score,
        }
        for offer in offers[:10]
    ]
    system = (
        "Você é o Agente Analista de um squad de compras. Compare as ofertas e recomende a melhor "
        "para o pedido do usuário. Responda SOMENTE JSON válido, em português do Brasil, com as chaves: "
        "headline (string curta), summary (2 a 4 frases), best_pick_id (um id da lista), "
        "pros (array de até 4), cons (array de até 3), tips (array de até 3), warning (string ou null). "
        "Use apenas preços e dados fornecidos; nunca invente valores. Considere preço, nota, "
        "quantidade de avaliações, frete, specs atendidas e confiabilidade da fonte."
    )
    user = json.dumps(
        {
            "pedido": intent.raw_query,
            "especificacoes": intent.specs,
            "orcamento_max": intent.budget_max,
            "ofertas": compact_offers,
            "observacoes_fontes": source_notes,
            "modo_demonstracao": any(offer.is_demo for offer in offers),
        },
        ensure_ascii=False,
    )
    payload = {
        "model": settings.openai_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
        "max_tokens": 700,
    }

    try:
        async with httpx.AsyncClient(timeout=min(settings.request_timeout + 8, 32)) as client:
            response = await client.post(
                f"{settings.openai_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json=payload,
            )
        if response.status_code >= 400:
            return fallback
        content = response.json()["choices"][0]["message"]["content"]
        parsed = _parse_json(content)
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        return fallback

    if not parsed:
        return fallback

    valid_ids = {offer.id for offer in offers}
    best_id = parsed.get("best_pick_id")
    if best_id not in valid_ids:
        best_id = fallback.best_pick_id

    def _list(key: str, size: int) -> list[str]:
        value = parsed.get(key)
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()][:size]

    summary = str(parsed.get("summary") or "").strip()
    headline = str(parsed.get("headline") or "").strip()
    if not summary or not headline:
        return fallback

    warning = parsed.get("warning")
    return fallback.model_copy(
        update={
            "headline": headline[:120],
            "summary": summary[:900],
            "best_pick_id": best_id,
            "pros": _list("pros", 4) or fallback.pros,
            "cons": _list("cons", 3),
            "tips": _list("tips", 3) or fallback.tips,
            "warning": str(warning).strip() if warning else fallback.warning,
            "ai": True,
        }
    )


async def analyze(
    offers: list[Offer],
    intent: Intent,
    settings: Settings,
    source_notes: list[str] | None = None,
    mode: str = "real",
    meta: dict | None = None,
) -> Analysis:
    notes = source_notes or []
    fallback = _heuristic(offers, intent, meta or {}, notes, mode)
    if not settings.llm_enabled or not offers:
        return fallback
    return await _llm_analysis(offers, intent, settings, notes, mode, fallback)
