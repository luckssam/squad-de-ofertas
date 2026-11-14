(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  const BRL = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
  const COMPACT = new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 });

  const EXAMPLES = [
    "notebook i5 com 16GB e SSD 512GB até R$ 4.000",
    "fone bluetooth com cancelamento de ruído até R$ 500",
    "air fryer 5L de 1500W",
    "tênis para corrida até R$ 400",
    "smartwatch com GPS e bateria de 14 dias",
  ];

  const SOURCE_INITIALS = {
    amazon: "AM",
    mercadolivre: "ML",
    google_shopping: "GS",
    shopping: "BG",
    shopee: "SH",
    aliexpress: "AE",
    demo: "DE",
  };

  const AGENT_RUNNING = {
    intent: "Lendo seu pedido e extraindo a intenção…",
    search: "Consultando as fontes em paralelo…",
    curator: "Deduplicando, filtrando e pontuando…",
    analyst: "Comparando ofertas e escrevendo o veredito…",
  };

  const state = {
    config: null,
    offers: [],
    analysis: null,
    result: null,
    loading: false,
    sources: new Map(),
    bestPickId: null,
  };

  const form = $("#search-form");
  const input = $("#query");
  const submitBtn = $("#submit-btn");
  const resultsShell = $("#results-shell");
  const resultsHead = $("#results-head");
  const resultsTitle = $("#results-title");
  const resultsSub = $("#results-sub");
  const statsRow = $("#stats-row");
  const offersEl = $("#offers");
  const emptyState = $("#empty-state");
  const skeletons = $("#skeletons");
  const errorBanner = $("#error-banner");
  const errorText = $("#error-text");
  const analysisPanel = $("#analysis-panel");
  const sourcesPanel = $("#sources-panel");
  const sourceList = $("#source-list");
  const intentStrip = $("#intent-strip");
  const sortSelect = $("#sort");
  const filtersHint = $("#filters-hint");
  const liveBadge = $("#live-badge");
  const emptyTitle = $("h3", emptyState);
  const emptyText = $("p", emptyState);
  const emptyStateDefaults = { title: emptyTitle.textContent, text: emptyText.textContent };

  /* ---------- helpers ---------- */
  const esc = (value) =>
    String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[char]));

  const money = (value) =>
    typeof value === "number" && Number.isFinite(value) ? BRL.format(value) : "—";

  const ratingText = (value) =>
    typeof value === "number" ? value.toFixed(1).replace(".", ",") : null;

  const compactNumber = (value) =>
    typeof value === "number" ? COMPACT.format(value) : null;

  const formatMs = (ms) => (!ms ? "" : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`);

  function safeUrl(url) {
    try {
      const parsed = new URL(url, window.location.href);
      if (parsed.protocol === "http:" || parsed.protocol === "https:") return parsed.href;
    } catch (_) {
      /* ignore */
    }
    return "#";
  }

  function parseBudget(raw) {
    const text = String(raw || "").trim();
    if (!text) return null;
    let normalized = text.replace(/[^\d,.-]/g, "");
    if (!normalized) return null;
    if (normalized.includes(",")) {
      normalized = normalized.replace(/\./g, "").replace(",", ".");
    } else if ((normalized.match(/\./g) || []).length > 1) {
      normalized = normalized.replace(/\./g, "");
    } else if (/\.\d{3}$/.test(normalized)) {
      normalized = normalized.replace(/\./g, "");
    }
    const value = Number(normalized);
    return Number.isFinite(value) && value >= 0 ? value : null;
  }

  function computeStats(offers) {
    if (!offers.length) return null;
    const prices = offers.map((offer) => offer.price).filter((price) => Number.isFinite(price));
    prices.sort((a, b) => a - b);
    const middle = Math.floor(prices.length / 2);
    const median = prices.length % 2 ? prices[middle] : (prices[middle - 1] + prices[middle]) / 2;
    return {
      count: offers.length,
      min_price: prices[0],
      median_price: median,
      max_price: prices[prices.length - 1],
      free_shipping_count: offers.filter((offer) => offer.shipping_free === true).length,
    };
  }

  /* ---------- initial render ---------- */
  function init() {
    renderExamples();
    bindEvents();

    fetch("/api/config")
      .then((response) => response.json())
      .then((config) => {
        state.config = config;
        renderConfig(config);
        const params = new URLSearchParams(window.location.search);
        const initialQuery = (params.get("q") || "").trim();
        if (initialQuery.length >= 2) {
          input.value = initialQuery;
          runSearch(initialQuery, { scroll: false });
        }
      })
      .catch(() => {
        $("#llm-label").textContent = "servidor offline";
        $("#llm-pill").classList.add("is-off");
        $("#mode-label").textContent = "verifique o servidor";
        $("#mode-pill").classList.add("is-off");
      });

    updateFiltersHint();
  }

  function renderExamples() {
    const container = $("#examples");
    container.innerHTML = EXAMPLES.map(
      (example) => `<button type="button" class="example-chip">${esc(example)}</button>`
    ).join("");
    container.addEventListener("click", (event) => {
      const chip = event.target.closest(".example-chip");
      if (!chip) return;
      input.value = chip.textContent;
      submitSearch();
    });
  }

  function renderConfig(config) {
    const llmPill = $("#llm-pill");
    const llmLabel = $("#llm-label");
    const modePill = $("#mode-pill");
    const modeLabel = $("#mode-label");

    if (config.llm_enabled) {
      llmPill.classList.add("is-on");
      llmLabel.textContent = "IA ativa";
      llmPill.title = `Interpretação e análise com ${config.llm_model || "LLM"}`;
    } else {
      llmPill.classList.add("is-off");
      llmLabel.textContent = "IA off · regras locais";
      llmPill.title = "Defina OPENAI_API_KEY no .env para ativar a interpretação e análise com IA.";
    }

    if (config.demo_mode) {
      modePill.classList.add("is-demo");
      modeLabel.textContent = "modo demo";
      modePill.title = "Ofertas simuladas. Defina DEMO_MODE=false no .env para usar apenas fontes reais.";
    } else {
      modeLabel.textContent = "fontes reais";
      modePill.title = "Somente fontes reais configuradas.";
    }

    // Mercado Livre OAuth status
    const meliOAuth = config.meli_oauth;
    const meliSource = (config.sources || []).find(s => s.id === "mercadolivre");
    if (meliSource && meliOAuth) {
      const container = $("#source-chips");
      // Encontra o chip do Mercado Livre e adiciona botão de conexão
      const meliChip = container.querySelector('label[title*="Mercado Livre"]');
      if (meliChip && meliOAuth.configured) {
        const connectBtn = document.createElement("button");
        connectBtn.type = "button";
        connectBtn.className = "meli-connect-btn btn-ghost";
        connectBtn.style.marginLeft = "8px";
        connectBtn.style.fontSize = "12px";
        connectBtn.textContent = meliSource.configured ? "Desconectar ML" : "Conectar Mercado Livre";
        connectBtn.addEventListener("click", () => handleMeliAuth(meliSource.configured));
        meliChip.appendChild(connectBtn);
      }
    }

    const container = $("#source-chips");
    container.innerHTML = (config.sources || [])
      .map(
        (source) => `
        <label class="source-chip ${source.configured ? "" : "is-locked"}" title="${esc(source.note || source.label)}">
          <input type="checkbox" value="${esc(source.id)}" ${source.configured ? "" : "disabled"} />
          <span class="dot"></span>${esc(source.label)}${source.experimental ? " *" : ""}
        </label>`
      )
      .join("");

    container.addEventListener("change", updateFiltersHint);
  }

  async function handleMeliAuth(isConnected) {
    if (isConnected) {
      // Desconectar
      try {
        const resp = await fetch("/api/meli/disconnect", { method: "POST" });
        const data = await resp.json();
        if (data.success) {
          showToast("Mercado Livre desconectado.");
          // Recarregar config para atualizar UI
          const config = await fetch("/api/config").then(r => r.json());
          renderConfig(config);
        }
      } catch (e) {
        showToast("Erro ao desconectar.");
      }
    } else {
      // Conectar - abre nova aba para OAuth
      window.open("/auth/meli/start", "_blank", "width=600,height=700");
    }
  }

  function showToast(message) {
    // Cria toast simples
    const toast = document.createElement("div");
    toast.className = "toast";
    toast.textContent = message;
    toast.style.cssText = `
      position: fixed; bottom: 20px; right: 20px; z-index: 9999;
      background: var(--card); border: 1px solid var(--border);
      padding: 12px 16px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.3);
      animation: slideIn 0.3s ease;
    `;
    document.body.appendChild(toast);
    setTimeout(() => {
      toast.style.animation = "slideOut 0.3s ease";
      setTimeout(() => toast.remove(), 300);
    }, 3000);
  }

  /* ---------- events ---------- */
  function bindEvents() {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      submitSearch();
    });

    $("#clear-filters").addEventListener("click", () => {
      $("#budget-min").value = "";
      $("#budget-max").value = "";
      $$("#source-chips input[type=checkbox]").forEach((checkbox) => {
        checkbox.checked = false;
      });
      sortSelect.value = "score";
      updateFiltersHint();
      if (state.offers.length) renderOffers();
    });

    filtersHint && $("#filters").addEventListener("toggle", updateFiltersHint);

    sortSelect.addEventListener("change", () => {
      if (state.offers.length) renderOffers();
    });

    $("#error-close").addEventListener("click", () => {
      errorBanner.hidden = true;
    });

    $("#see-pick").addEventListener("click", () => {
      if (!state.bestPickId) return;
      const card = document.querySelector(`[data-offer-id="${cssEscape(state.bestPickId)}"]`);
      if (!card) return;
      card.scrollIntoView({ behavior: "smooth", block: "center" });
      card.classList.remove("flash");
      void card.offsetWidth;
      card.classList.add("flash");
    });

    document.addEventListener("keydown", (event) => {
      const tag = (event.target.tagName || "").toLowerCase();
      const typing = tag === "input" || tag === "textarea" || tag === "select" || event.target.isContentEditable;
      if (event.key === "/" && !typing) {
        event.preventDefault();
        input.focus();
      }
    });
  }

  function cssEscape(value) {
    if (window.CSS && typeof window.CSS.escape === "function") return window.CSS.escape(String(value));
    return String(value).replace(/["\\]/g, "\\$&");
  }

  function updateFiltersHint() {
    const selected = $$("#source-chips input:checked").map((checkbox) => checkbox.value);
    const min = $("#budget-min").value.trim();
    const max = $("#budget-max").value.trim();
    const bits = [];
    if (min || max) bits.push(`orçamento ${min ? `de ${min}` : ""}${max ? ` até ${max}` : " sem teto"}`);
    if (selected.length) bits.push(`${selected.length} fonte(s) fixa(s)`);
    filtersHint.textContent = bits.length ? bits.join(" · ") : "orçamento · fontes · ordenação";
  }

  /* ---------- search flow ---------- */
  function submitSearch() {
    if (state.loading) return;
    const query = input.value.trim();
    if (query.length < 2) {
      $("#search-box").classList.add("is-invalid");
      input.focus();
      window.setTimeout(() => $("#search-box").classList.remove("is-invalid"), 500);
      return;
    }
    runSearch(query);
  }

  async function runSearch(query, options = {}) {
    const shouldScroll = options.scroll !== false;
    state.loading = true;
    state.offers = [];
    state.analysis = null;
    state.result = null;
    state.bestPickId = null;
    state.sources.clear();

    showBusy();
    if (shouldScroll && window.innerWidth <= 1020) {
      resultsShell.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    const selectedSources = $$("#source-chips input:checked").map((checkbox) => checkbox.value);
    const payload = {
      query,
      budget_min: parseBudget($("#budget-min").value),
      budget_max: parseBudget($("#budget-max").value),
      sources: selectedSources.length ? selectedSources : undefined,
      limit: 30,
      sort: sortSelect.value,
    };

    try {
      const response = await fetch("/api/search/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        let message = `A busca falhou (HTTP ${response.status}).`;
        try {
          const data = await response.json();
          if (typeof data.detail === "string") message = data.detail;
          else if (Array.isArray(data.detail) && data.detail[0]?.msg) message = data.detail[0].msg;
        } catch (_) {
          /* keep default */
        }
        throw new Error(message);
      }

      await consumeStream(response, handleEvent);
    } catch (error) {
      failSearch(error instanceof Error ? error : new Error("Falha inesperada na busca."));
    } finally {
      state.loading = false;
      setBusy(false);
    }
  }

  async function consumeStream(response, onEvent) {
    if (!response.body) throw new Error("Seu navegador não suporta streaming. Tente Chrome, Edge ou Firefox.");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const raw = buffer.slice(0, boundary).replace(/\r/g, "");
        buffer = buffer.slice(boundary + 2);
        if (raw.trim()) dispatchSse(raw, onEvent);
        boundary = buffer.indexOf("\n\n");
      }
    }
  }

  function dispatchSse(raw, onEvent) {
    let eventName = "message";
    const dataLines = [];
    raw.split("\n").forEach((line) => {
      if (line.startsWith("event:")) eventName = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
    });
    if (!dataLines.length) return;
    try {
      onEvent(eventName, JSON.parse(dataLines.join("\n")));
    } catch (error) {
      console.warn("Evento inválido do servidor", error);
    }
  }

  function handleEvent(type, data) {
    switch (type) {
      case "trace":
        updateAgent(data);
        break;
      case "intent":
        renderIntent(data.intent);
        break;
      case "source":
        addSource(data.source);
        break;
      case "offers":
        state.offers = data.offers || [];
        renderOffers();
        renderStats(state.analysis?.stats || computeStats(state.offers));
        resultsHead.hidden = false;
        updateResultsHead(state.offers.length);
        break;
      case "analysis":
        state.analysis = data.analysis;
        renderAnalysis(data.analysis);
        if (data.analysis?.stats) renderStats(data.analysis.stats);
        renderOffers();
        break;
      case "done":
        finishSearch(data.result);
        break;
      case "error":
        failSearch(new Error(data.message || "Erro inesperado no squad."));
        break;
      default:
        break;
    }
  }

  function showBusy() {
    resultsShell.classList.remove("is-idle");
    resultsHead.hidden = true;
    statsRow.hidden = true;
    statsRow.innerHTML = "";
    offersEl.innerHTML = "";
    emptyState.hidden = true;
    skeletons.hidden = false;
    analysisPanel.hidden = true;
    sourcesPanel.hidden = true;
    sourceList.innerHTML = "";
    intentStrip.hidden = true;
    errorBanner.hidden = true;
    emptyTitle.textContent = emptyStateDefaults.title;
    emptyText.textContent = emptyStateDefaults.text;
    resetAgents();
    setLive("running");
    setBusy(true);
  }

  function finishSearch(result) {
    state.result = result;
    state.offers = result.offers || [];
    state.analysis = result.analysis;
    state.bestPickId = result.analysis?.best_pick_id || null;

    const params = new URLSearchParams(window.location.search);
    params.set("q", result.intent?.raw_query || input.value.trim());
    window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);

    skeletons.hidden = true;
    resultsHead.hidden = false;
    updateResultsHead(state.offers.length, result);
    renderStats(result.analysis?.stats || computeStats(state.offers));
    renderOffers();
    renderAnalysis(result.analysis);
    renderSources(result.sources || []);
    renderIntent(result.intent);
    setLive("done");
    setBusy(false);
    state.loading = false;

    if (!state.offers.length) {
      emptyState.hidden = false;
      emptyTitle.textContent = "Nenhuma oferta com esses filtros.";
      emptyText.textContent =
        "Tente remover uma especificação, ampliar o orçamento ou habilitar mais fontes de busca.";
    } else {
      emptyState.hidden = true;
    }
  }

  function failSearch(error) {
    state.loading = false;
    setBusy(false);
    skeletons.hidden = true;
    errorText.textContent = error.message || "Tente novamente em instantes.";
    errorBanner.hidden = false;
    setLive("error");

    const running = $(".agent.is-running");
    if (running) {
      running.className = "agent is-error";
      const message = $(".agent-msg", running);
      if (message) message.textContent = "Etapa interrompida.";
    }
    if (!state.offers.length && resultsHead.hidden) {
      emptyState.hidden = false;
      emptyTitle.textContent = "A busca não terminou.";
      emptyText.textContent = "Confira se o servidor está rodando e tente novamente.";
    }
  }

  function setBusy(busy) {
    form.classList.toggle("is-busy", busy);
    submitBtn.disabled = busy;
    $(".btn-label", submitBtn).textContent = busy ? "Buscando…" : "Buscar ofertas";
  }

  function updateResultsHead(count, result = null) {
    resultsTitle.textContent = count === 1 ? "1 oferta encontrada" : `${count} ofertas encontradas`;
    const bits = [];
    if (result) {
      const intent = result.intent || {};
      bits.push(`“${intent.product || intent.raw_query}”`);
      const sourceCount = (result.sources || []).filter((source) => source.status === "ok").length;
      if (sourceCount) bits.push(`${sourceCount} fonte${sourceCount > 1 ? "s" : ""}`);
      if (result.elapsed_ms) bits.push(formatMs(result.elapsed_ms));
      if (result.mode === "demo") bits.push("dados simulados");
      if (result.mode === "hybrid") bits.push("reais + simulação");
    }
    resultsSub.textContent = bits.join(" · ");
  }

  function setLive(status) {
    liveBadge.classList.remove("is-running", "is-done", "is-error");
    if (status === "running") {
      liveBadge.classList.add("is-running");
      liveBadge.innerHTML = '<span class="dot"></span> trabalhando';
    } else if (status === "done") {
      liveBadge.classList.add("is-done");
      liveBadge.innerHTML = '<span class="dot"></span> concluído';
    } else if (status === "error") {
      liveBadge.classList.add("is-error");
      liveBadge.innerHTML = '<span class="dot"></span> falhou';
    } else {
      liveBadge.innerHTML = '<span class="dot"></span> pronta';
    }
  }

  /* ---------- agents ---------- */
  function resetAgents() {
    $$("#agents .agent").forEach((agent) => {
      agent.className = "agent";
      $(".agent-ms", agent).textContent = "";
      $(".agent-msg", agent).textContent = "Aguardando o agente anterior.";
    });
  }

  function updateAgent(data) {
    const agent = document.querySelector(`.agent[data-agent="${cssEscape(data.agent)}"]`);
    if (!agent) return;
    agent.className = `agent is-${data.status}`;
    if (data.ms) $(".agent-ms", agent).textContent = formatMs(data.ms);
    const message = $(".agent-msg", agent);
    if (data.message) message.textContent = data.message;
    else if (data.status === "running" && AGENT_RUNNING[data.agent]) message.textContent = AGENT_RUNNING[data.agent];
  }

  /* ---------- intent ---------- */
  function renderIntent(intent) {
    if (!intent) return;
    const chips = [];
    chips.push(`<span class="intent-chip"><strong>produto</strong> ${esc(intent.product)}</span>`);
    if (intent.category) chips.push(`<span class="intent-chip"><strong>categoria</strong> ${esc(intent.category)}</span>`);
    if (intent.budget_min || intent.budget_max) {
      let budget = "";
      if (intent.budget_min && intent.budget_max) budget = `${money(intent.budget_min)} – ${money(intent.budget_max)}`;
      else if (intent.budget_max) budget = `até ${money(intent.budget_max)}`;
      else budget = `a partir de ${money(intent.budget_min)}`;
      chips.push(`<span class="intent-chip"><strong>orçamento</strong> ${esc(budget)}</span>`);
    }
    if (intent.specs?.length) {
      chips.push(`<span class="intent-chip"><strong>specs</strong> ${esc(intent.specs.join(" · "))}</span>`);
    }
    if (intent.exclude?.length) {
      chips.push(`<span class="intent-chip"><strong>sem</strong> ${esc(intent.exclude.join(" · "))}</span>`);
    }
    chips.push(
      `<span class="intent-chip"><strong>motor</strong> ${intent.source === "llm" ? "IA + regras" : "regras locais"}</span>`
    );
    if (intent.notes) chips.push(`<span class="intent-chip" title="${esc(intent.notes)}">${esc(intent.notes)}</span>`);

    intentStrip.innerHTML = chips.join("");
    intentStrip.hidden = false;
  }

  /* ---------- sources ---------- */
  function addSource(source) {
    if (!source) return;
    state.sources.set(source.id, source);
    sourcesPanel.hidden = false;
    renderSources(Array.from(state.sources.values()));
  }

  function renderSources(sources) {
    if (!sources?.length) {
      sourcesPanel.hidden = true;
      return;
    }
    sourcesPanel.hidden = false;
    sourceList.innerHTML = sources
      .map((source) => {
        const status = source.status || "disabled";
        let detail = "";
        if (status === "ok") detail = source.message || `${source.count} ofertas em ${formatMs(source.ms) || "-"}`;
        else if (status === "restricted") detail = source.message || "Fonte restrita pelo provedor";
        else if (status === "error") detail = source.message || "Falha na consulta";
        else detail = source.message || "Sem credenciais configuradas";
        const count = status === "ok" ? `${source.count}` : status === "error" ? "erro" : status === "restricted" ? "restrito" : "-";
        return `
          <div class="source-row" title="${esc(detail)}">
            <span class="dot ${esc(status)}"></span>
            <div>
              <div class="source-name">${esc(source.label)}</div>
              <div class="source-detail">${esc(detail)}</div>
            </div>
            <span class="source-count">${esc(count)}</span>
          </div>`;
      })
      .join("");
  }

  /* ---------- stats ---------- */
  function renderStats(stats) {
    if (!stats || !stats.count) {
      statsRow.hidden = true;
      return;
    }
    const meta = state.result || {};
    const cards = [
      { label: "menor preço", value: money(stats.min_price), note: "entre as ofertas" },
      { label: "mediana", value: money(stats.median_price), note: "referência de preço" },
      {
        label: "ofertas",
        value: String(stats.count),
        note: meta.total_found ? `${meta.total_found} coletadas` : "após curadoria",
      },
      {
        label: "frete grátis",
        value: String(stats.free_shipping_count ?? 0),
        note: "com frete confirmado",
      },
    ];
    statsRow.innerHTML = cards
      .map(
        (card) => `
        <div class="stat">
          <span>${esc(card.label)}</span>
          <strong>${esc(card.value)}</strong>
          <em>${esc(card.note)}</em>
        </div>`
      )
      .join("");
    statsRow.hidden = false;
  }

  /* ---------- offers ---------- */
  function sortOffers(offers) {
    const list = [...offers];
    switch (sortSelect.value) {
      case "price_asc":
        return list.sort((a, b) => a.price - b.price);
      case "price_desc":
        return list.sort((a, b) => b.price - a.price);
      case "rating":
        return list.sort((a, b) => (b.rating ?? -1) - (a.rating ?? -1) || (b.reviews ?? 0) - (a.reviews ?? 0));
      default:
        return list.sort((a, b) => b.score - a.score);
    }
  }

  function badgeClass(label) {
    if (label === "Frete grátis") return "ship";
    if (label === "Acima do orçamento") return "warn";
    if (label === "Poucas avaliações") return "muted";
    if (label === "Specs completas") return "specs";
    return "price";
  }

  function renderOffers() {
    const offers = sortOffers(state.offers || []);
    if (!offers.length) {
      offersEl.innerHTML = "";
      return;
    }

    offersEl.innerHTML = offers
      .map((offer, index) => {
        const isBest = state.analysis?.best_pick_id === offer.id;
        const initials = SOURCE_INITIALS[offer.source] || (offer.source_label || "?").slice(0, 2).toUpperCase();
        const image = offer.image
          ? `<img src="${esc(safeUrl(offer.image))}" alt="" loading="lazy" referrerpolicy="no-referrer" />`
          : "";
        const rating = ratingText(offer.rating);
        const reviews = compactNumber(offer.reviews);
        const metaBits = [];
        if (rating) {
          metaBits.push(`<span class="rating"><span class="star">★</span>${esc(rating)}</span>`);
          if (reviews) metaBits.push(`<span class="reviews">(${esc(reviews)})</span>`);
        } else {
          metaBits.push('<span class="reviews">sem nota</span>');
        }
        if (offer.seller) metaBits.push('<span class="meta-sep">·</span>');
        if (offer.seller) metaBits.push(`<span class="seller">${esc(offer.seller)}</span>`);

        const specs = [];
        (offer.matched_specs || []).slice(0, 4).forEach((spec) => {
          specs.push(`<span class="spec ok" title="Especificação encontrada no título">✓ ${esc(spec)}</span>`);
        });
        (offer.missing_specs || []).slice(0, 2).forEach((spec) => {
          specs.push(`<span class="spec missing" title="Não confirmada no título">? ${esc(spec)}</span>`);
        });

        const badges = [];
        if (isBest) badges.push('<span class="badge best">Escolha do squad</span>');
        (offer.badges || []).forEach((badge) => {
          if (isBest && badge === "Melhor custo-benefício") return;
          badges.push(`<span class="badge ${badgeClass(badge)}">${esc(badge)}</span>`);
        });

        const priceNoteBits = [];
        if (offer.installments) priceNoteBits.push(offer.installments);
        else priceNoteBits.push("à vista");
        if (offer.shipping_free === true) priceNoteBits.push("frete grátis");
        const note = priceNoteBits.join(" · ");
        const url = safeUrl(offer.affiliate_url || offer.url);
        const cta =
          url === "#"
            ? '<span class="cta" aria-disabled="true">Sem link</span>'
            : `<a class="cta" href="${esc(url)}" target="_blank" rel="noopener nofollow">Ver oferta ↗</a>`;
        const dealNote =
          typeof offer.price_vs_median === "number" && offer.price_vs_median <= -5
            ? `<div class="deal-note">${Math.round(Math.abs(offer.price_vs_median))}% abaixo da mediana</div>`
            : "";

        return `
          <article class="offer ${isBest ? "is-best" : ""} ${offer.over_budget ? "is-over-budget" : ""}"
                   data-offer-id="${esc(offer.id)}" style="--i:${Math.min(index, 8)}">
            <div class="offer-media">
              <span class="placeholder">${esc(initials)}</span>
              ${image}
            </div>
            <div class="offer-body">
              <div class="offer-topline">
                <span class="source-tag" data-source="${esc(offer.source)}">${esc(offer.source_label)}</span>
                ${badges.join("")}
              </div>
              <h3 class="offer-title">${esc(offer.title)}</h3>
              <div class="offer-meta">${metaBits.join("")}</div>
              ${specs.length ? `<div class="specs">${specs.join("")}</div>` : ""}
              <div class="offer-bottom">
                <div class="price-block">
                  <span class="price">${money(offer.price)}</span>
                  <span class="price-note" title="${esc(note)}">${esc(note)}</span>
                  ${dealNote}
                </div>
                <div class="offer-actions">
                  <div class="score ${offer.score < 55 ? "low" : ""}" style="--score:${Math.max(0, Math.min(100, offer.score || 0))}" title="Score do squad: ${esc(offer.score)}/100">
                    <span>${Math.round(offer.score || 0)}</span>
                  </div>
                  ${cta}
                </div>
              </div>
            </div>
          </article>`;
      })
      .join("");

    $$("img", offersEl).forEach((img) => {
      img.addEventListener("error", () => {
        img.style.display = "none";
      });
    });
  }

  /* ---------- analysis ---------- */
  function renderAnalysis(analysis) {
    if (!analysis) {
      analysisPanel.hidden = true;
      return;
    }
    analysisPanel.hidden = false;
    $("#analysis-headline").textContent = analysis.headline || "";
    $("#analysis-summary").textContent = analysis.summary || "";
    $("#ai-tag").hidden = !analysis.ai;

    const pros = (analysis.pros || []).slice(0, 4);
    const cons = (analysis.cons || []).slice(0, 3);
    $("#analysis-pros").innerHTML = pros.length
      ? pros.map((item) => `<li>${esc(item)}</li>`).join("")
      : '<li class="is-empty">Sem destaques objetivos.</li>';
    $("#analysis-cons").innerHTML = cons.length
      ? cons.map((item) => `<li>${esc(item)}</li>`).join("")
      : '<li class="is-empty">Nenhum ponto crítico identificado.</li>';

    const warning = $("#analysis-warning");
    warning.hidden = !analysis.warning;
    warning.textContent = analysis.warning || "";

    const tips = analysis.tips || [];
    $("#analysis-tips").hidden = !tips.length;
    $("#analysis-tips-list").innerHTML = tips.map((tip) => `<li>${esc(tip)}</li>`).join("");

    state.bestPickId = analysis.best_pick_id || null;
    $("#see-pick").hidden = !state.bestPickId;
  }

  init();
})();
