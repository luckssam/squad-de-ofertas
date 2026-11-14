"""Orquestrador do squad: encadeia intenção → busca → curadoria → análise."""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

from agents.analyst import analyze
from agents.curator import curate
from agents.intent import heuristic_intent, parse_intent
from connectors import build_connectors
from connectors.base import Connector, ConnectorError
from core.config import Settings
from core.models import (
    Intent,
    Offer,
    SearchRequest,
    SearchResult,
    SourceStatus,
    TraceEvent,
)
from core.utils import format_brl
from core.affiliate import aplicar_links_afiliado


class Squad:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.connectors: list[Connector] = build_connectors(settings)
        self._cache: dict[tuple[str, str, int, float | None, float | None], tuple[float, list[Offer], SourceStatus]] = {}

    async def _search_one(
        self, connector: Connector, intent: Intent, limit: int
    ) -> tuple[Connector, list[Offer], SourceStatus]:
        start = time.perf_counter()
        
        # Chave de cache baseada nos parâmetros da busca
        from connectors.base import build_terms
        terms = build_terms(intent)
        cache_key = (connector.id, terms, limit, intent.budget_min, intent.budget_max)
        
        if cache_key in self._cache:
            ts, offers, status = self._cache[cache_key]
            if (time.perf_counter() - ts) < self.settings.cache_ttl:
                # Retorna cópia para evitar mutação e atualiza mensagem de cache
                status_cached = status.model_copy(update={"message": f"Resultado em cache ({int(self.settings.cache_ttl/60)} min)"})
                return connector, offers, status_cached

        if not connector.configured:
            return connector, [], SourceStatus(
                id=connector.id,
                label=connector.label,
                status="disabled",
                message=connector.setup_hint or "Conector sem credenciais.",
            )

        try:
            offers = await asyncio.wait_for(
                connector.search(intent, limit), timeout=self.settings.request_timeout + 3
            )
            elapsed = int((time.perf_counter() - start) * 1000)
            message = None if offers else "Nenhuma oferta retornada para esta busca."
            status = SourceStatus(
                id=connector.id,
                label=connector.label,
                status="ok",
                count=len(offers),
                message=message,
                ms=elapsed,
            )
            # Cacheia apenas sucessos com resultados
            if offers:
                self._cache[cache_key] = (time.perf_counter(), offers, status)
                
            return connector, offers, status
        except asyncio.TimeoutError:
            elapsed = int((time.perf_counter() - start) * 1000)
            return connector, [], SourceStatus(
                id=connector.id,
                label=connector.label,
                status="error",
                message="Tempo esgotado ao consultar a fonte.",
                ms=elapsed,
            )
        except ConnectorError as exc:
            elapsed = int((time.perf_counter() - start) * 1000)
            return connector, [], SourceStatus(
                id=connector.id,
                label=connector.label,
                status="restricted" if getattr(exc, "restricted", False) else "error",
                message=str(exc),
                ms=elapsed,
            )
        except Exception as exc:  # noqa: BLE001 - o squad nunca deve cair por uma fonte
            elapsed = int((time.perf_counter() - start) * 1000)
            return connector, [], SourceStatus(
                id=connector.id,
                label=connector.label,
                status="error",
                message=f"Erro inesperado ({exc.__class__.__name__}).",
                ms=elapsed,
            )

    def _select_connectors(self, request: SearchRequest) -> list[Connector]:
        selected_ids = set(request.sources or [])
        real = [connector for connector in self.connectors if connector.id != "demo"]
        demo = next(connector for connector in self.connectors if connector.id == "demo")

        if selected_ids:
            chosen = [c for c in self.connectors if c.id in selected_ids]
            if not chosen:
                chosen = [demo]
            return chosen

        chosen = [connector for connector in real if connector.configured]
        if self.settings.demo_mode or not chosen:
            chosen.insert(0, demo)
        return chosen

    async def run(self, request: SearchRequest) -> AsyncIterator[dict[str, Any]]:
        started = time.perf_counter()
        trace: list[TraceEvent] = []

        def event_trace(agent: str, label: str, status: str, message: str = "", ms: int = 0) -> None:
            trace.append(
                TraceEvent(agent=agent, label=label, status=status, message=message, ms=ms)
            )

        stage_start = time.perf_counter()
        yield {"type": "trace", "agent": "intent", "label": "Agente de Intenção", "status": "running"}

        try:
            intent = await parse_intent(request, self.settings)
        except Exception:  # noqa: BLE001
            intent = heuristic_intent(request)
            intent.notes = "Falha na IA; interpretação local aplicada."

        intent_ms = int((time.perf_counter() - stage_start) * 1000)
        summary_bits = [intent.product]
        if intent.budget_max:
            summary_bits.append(f"até {format_brl(intent.budget_max)}")
        if intent.budget_min:
            summary_bits.append(f"a partir de {format_brl(intent.budget_min)}")
        if intent.specs:
            summary_bits.append("specs: " + ", ".join(intent.specs[:3]))
        intent_message = " · ".join(bit for bit in summary_bits if bit)
        event_trace("intent", "Agente de Intenção", "ok", intent_message, intent_ms)
        yield {"type": "intent", "intent": intent.model_dump()}
        yield {
            "type": "trace",
            "agent": "intent",
            "label": "Agente de Intenção",
            "status": "ok",
            "message": intent_message,
            "ms": intent_ms,
        }

        stage_start = time.perf_counter()
        chosen = self._select_connectors(request)
        yield {
            "type": "trace",
            "agent": "search",
            "label": "Agente de Busca",
            "status": "running",
            "message": "Consultando " + ", ".join(connector.label for connector in chosen),
        }

        per_source_limit = max(12, min(self.settings.max_offers_per_source, 40))
        results = await asyncio.gather(
            *(self._search_one(connector, intent, per_source_limit) for connector in chosen)
        )

        offers: list[Offer] = []
        statuses: list[SourceStatus] = []
        for _connector, source_offers, status in results:
            offers.extend(source_offers)
            statuses.append(status)
            yield {"type": "source", "source": status.model_dump()}

        search_ms = int((time.perf_counter() - stage_start) * 1000)
        ok_count = sum(1 for status in statuses if status.status == "ok")
        error_count = sum(1 for status in statuses if status.status == "error")
        restricted_count = sum(1 for status in statuses if status.status == "restricted")
        has_demo_offers = any(offer.is_demo for offer in offers)
        has_real_offers = any(not offer.is_demo for offer in offers)
        if has_demo_offers and has_real_offers:
            mode = "hybrid"
        elif has_demo_offers:
            mode = "demo"
        else:
            mode = "real"

        search_message = f"{len(offers)} ofertas de {ok_count} fonte(s)"
        if restricted_count:
            search_message += f" - {restricted_count} fonte(s) restrita(s)"
        if error_count:
            search_message += f" - {error_count} fonte(s) com erro"
        event_trace(
            "search",
            "Agente de Busca",
            "warning" if error_count else "ok",
            search_message,
            search_ms,
        )
        yield {
            "type": "trace",
            "agent": "search",
            "label": "Agente de Busca",
            "status": "warning" if error_count else "ok",
            "message": search_message,
            "ms": search_ms,
        }

        stage_start = time.perf_counter()
        yield {"type": "trace", "agent": "curator", "label": "Agente de Curadoria", "status": "running"}
        curated, meta = curate(offers, intent, request)
        curation_ms = int((time.perf_counter() - stage_start) * 1000)
        curation_message = (
            f"{len(curated)} selecionadas de {meta['total_received']} · "
            f"{meta['duplicates_removed']} duplicadas removidas"
        )
        if meta["over_budget"]:
            curation_message += f" · {meta['over_budget']} acima do orçamento"
        if meta.get("invalid_titles"):
            curation_message += f" · {meta['invalid_titles']} título inválido"
        if meta.get("attribute_filtered"):
            curation_message += f" · {meta['attribute_filtered']} fora de cor/material"
        if meta.get("brand_filtered"):
            curation_message += f" · {meta['brand_filtered']} de outra marca"
        if meta["relaxed"]:
            curation_message += " · filtro de orçamento relaxado"
        event_trace("curator", "Agente de Curadoria", "ok", curation_message, curation_ms)
        yield {"type": "offers", "offers": [offer.model_dump() for offer in curated], "meta": meta}
        yield {
            "type": "trace",
            "agent": "curator",
            "label": "Agente de Curadoria",
            "status": "ok",
            "message": curation_message,
            "ms": curation_ms,
        }

        stage_start = time.perf_counter()
        yield {"type": "trace", "agent": "analyst", "label": "Agente Analista", "status": "running"}
        source_notes = [
            f"{status.label}: {status.message}"
            for status in statuses
            if status.status == "error" and status.message
        ]
        analysis = await analyze(
            curated,
            intent,
            self.settings,
            source_notes=source_notes,
            mode=mode,
            meta=meta,
        )
        analysis_ms = int((time.perf_counter() - stage_start) * 1000)
        event_trace("analyst", "Agente Analista", "ok", analysis.headline, analysis_ms)
        yield {"type": "analysis", "analysis": analysis.model_dump()}
        yield {
            "type": "trace",
            "agent": "analyst",
            "label": "Agente Analista",
            "status": "ok",
            "message": analysis.headline,
            "ms": analysis_ms,
        }

        result = SearchResult(
            intent=intent,
            offers=aplicar_links_afiliado(curated, self.settings),
            sources=statuses,
            analysis=analysis,
            trace=trace,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            mode=mode,
            demoted_budget=meta["over_budget"],
            total_found=meta["total_received"],
        )
        yield {"type": "done", "result": result.model_dump()}
