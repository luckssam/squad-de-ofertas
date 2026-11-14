# Squad de Ofertas

[![CI](https://github.com/luckssmau/squad-de-ofertas/actions/workflows/ci.yml/badge.svg)](https://github.com/luckssmau/squad-de-ofertas/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Aplicação web **local** em Python onde você descreve o que quer comprar — produto, especificações e orçamento — e um **squad de agentes** busca, compara e recomenda a melhor oferta.

> **Sem chaves de API**, o app roda em **modo demonstração** com ofertas simuladas. Basta abrir e usar.

---

## Demonstração rápida

```bat
iniciar.bat
```

O script cria a virtualenv, instala dependências, copia `.env.example` para `.env` (se não existir) e abre `http://127.0.0.1:8765`.

**Manual:**

```bash
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

**Com Docker:**

```bash
docker compose up --build
# ou
docker build -t squad-ofertas .
docker run -p 8765:8765 --env-file .env squad-ofertas
```

---

## O squad

| Agente | Papel | O que faz |
|---|---|---|
| **Intenção** | interpreta | Extrai produto, specs, orçamento, restrições e exclusões. Usa regras locais + LLM (opcional). |
| **Busca** | coleta | Consulta fontes selecionadas em **paralelo**, com timeout por fonte. Falha isolada não derruba o squad. |
| **Curadoria** | filtra | Normaliza, remove duplicatas (similaridade), aplica orçamento/exclusões, confere specs, calcula **score 0–100**. |
| **Análise** | decide | Compara preço, nota, avaliações, frete, specs → aponta **prós/contras** e escreve a **recomendação**. |

Fluxo: `texto livre → intenção → busca paralela → curadoria → análise → recomendação`  
A tela mostra o squad trabalhando em tempo real via **SSE** (`/api/search/stream`).

### Score (0–100)

| Peso | Critério |
|---:|---|
| 34% | preço relativo ao menor preço do resultado |
| 20% | nota do produto (quando disponível) |
| 15% | specs atendidas |
| 13% | confiabilidade da fonte |
| 10% | frete grátis |
| 8% | volume de avaliações |

> O score é uma heurística transparente, não uma promessa de melhor compra. Preço e disponibilidade mudam — confirme sempre na loja.

---

## Fontes de ofertas

Configure no `.env` (veja `.env.example`):

| Fonte | Chaves | Observações |
|---|---|---|
| **Demonstração** | — | Sempre disponível. Gera ofertas plausíveis e determinísticas. |
| **Shopping (Bing)** | nada (padrão) | **Navegador real** — cards com preço/loja e link real do produto (ASIN, MLB…). `SHOPPING_WEB_ENABLED=false` volta para o Google Shopping/SerpAPI. |
| **Amazon Brasil** | nada (padrão) | **Navegador real** (Edge/Chrome) — sem custo e sem cota. `AMAZON_WEB_ENABLED=false` volta para o SerpAPI. Links `amazon.com.br/dp/ASIN`. |
| **Mercado Livre** | nada (padrão) | **Navegador real** — a API oficial de busca dá 403 para apps de terceiros. `MELI_USE_API=true` usa a API (após certificação). |
| **Shopee** | `SHOPEE_APP_ID`, `SHOPEE_SECRET` | Open API de afiliados. **Experimental** — requer aprovação. |
| **AliExpress** | `ALIEXPRESS_APP_KEY`, `ALIEXPRESS_SECRET`, `ALIEXPRESS_TRACKING_ID` | Affiliate API. **Experimental** — assinatura/endpoint podem variar. |

> **Modo só fontes reais:** `DEMO_MODE=false`  
> Se uma fonte falhar, a tela mostra o motivo (chave inválida, limite, timeout) sem interromper as demais.

> **Um único navegador:** Mercado Livre, Amazon e Shopping usam o **mesmo Edge** (perfil em `data/browser_profile`), numa janela só, fora da tela. As abas são fechadas após cada busca para não acumular memória.

### Links de afiliado

O app reescreve o link de cada oferta quando há credencial do programa:

| Loja | Variáveis no `.env` | Como fica o link |
|---|---|---|
| **Mercado Livre** | `ML_AFFILIATE_TAG` (etiqueta) + `ML_AFFILIATE_TOOL` (número) | `?matt_word=...&matt_tool=...` |
| **Amazon** | `AMAZON_ASSOCIATE_TAG` (`seusite-20`) | `?tag=seusite-20` |

- No Mercado Livre, pegue os dois valores em **Afiliados → Ferramentas → Gerador de links**: gere um link de qualquer produto e copie `matt_word` e `matt_tool` da URL.
- **Os dois são obrigatórios**: sem o `matt_tool` o Mercado Livre não atribui a comissão, então o link fica o original.
- Links de Shopping que apontam para Mercado Livre ou Amazon também recebem o afiliado da loja de destino.
- Sem credencial, a oferta usa a URL original (nada quebra).

### Cor, material, marca e tipo

Quando o pedido cita cor, material ou marca ("PLA Silk Dourado", "tênis azul", "air fryer Philips"), a curadoria:

- descarta ofertas que citam **outra cor** (ou misturam várias cores) ou **outro material** (ex.: PETG quando você pediu PLA);
- descarta produto de tipo diferente que só coincidiu na cor (ex.: linha de crochê "ouro");
- descarta **marca concorrente explícita** (ex.: Oster/Philco/Mondial numa busca por Philips);
- mantém ofertas sem cor/marca no título, mas **rebaixadas** e marcadas com `Cor não confirmada` / `Marca não confirmada`;
- rebaixa título que não cita o **tipo** pedido (ex.: sutiã numa busca por camiseta), com o selo `Tipo não confirmado`;
- aceita sinônimos de categoria ("air fryer" = "fritadeira", "camiseta" = "camisa"/"t-shirt");
- envia às lojas termos limpos (`pla silk dourado`), sem rótulos como `cor:` / `material:`.

### Cache inteligente (15 min)

- Cada busca por conector é cacheada por **15 minutos** (configurável via `CACHE_TTL`).
- Buscas repetidas **não consomem créditos** do SerpAPI.
- No painel lateral, fontes vindas do cache mostram: `"Resultado em cache (15 min)"`.

---

## IA (opcional)

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
# OPENAI_BASE_URL=https://api.openai.com/v1
```

Qualquer endpoint compatível com **OpenAI Chat Completions** serve (OpenAI, OpenRouter, Ollama + camada compatível).  
Sem IA, a interpretação e a análise usam regras locais — o app continua **100% funcional**.

---

## Estrutura

```
app.py                      FastAPI, SSE, arquivos estáticos, rotas OAuth
core/
  config.py                 leitura do .env, configuração pública, meli_oauth
  models.py                 contratos (Intent, Offer, Analysis, SearchResult…)
  orchestrator.py           encadeamento dos agentes + cache + streaming
  utils.py                  texto, preço, similaridade, hash
  attributes.py             cor/material do pedido × título da oferta
agents/
  intent.py                 intenção (regras + LLM, termos ancorados no pedido)
  curator.py                dedupe, filtros (cor/material), score
  analyst.py                estatísticas e recomendação
connectors/
  base.py                   contrato base + build_terms
  demo.py                   catálogo simulado
  google_shopping.py        SerpAPI (Google Shopping) — reserva
  bing_shopping.py          Shopping (Bing) via navegador — padrão
  amazon_web.py             navegador real (Amazon) — padrão
  amazon_serpapi.py         SerpAPI (Amazon) — reserva
  browser.py                navegador off-screen compartilhado
  amazon.py                 PA-API 5.0 — **legacy, descontinuado**
  melo_oauth.py             gerenciador tokens ML (refresh automático)
  mercadolivre.py           API oficial (usa OAuth se configurado)
  shopee.py                 afiliados (experimental)
  aliexpress.py             afiliados (experimental)
web/                        tela (HTML/CSS/JS vanilla, sem build)
.github/workflows/ci.yml    CI: testes, lint, verificação de segredos, build Docker
Dockerfile                  multi-stage, non-root, healthcheck
docker-compose.yml          sobe app + variáveis via .env
```

---

## API

| Endpoint | Descrição |
|---|---|
| `GET /api/config` | Fontes disponíveis + status (sem expor segredos) + `meli_oauth.auth_url` |
| `GET /api/health` | `{status, llm, demo}` |
| `GET /api/meli/status` | Status do token ML (válido, expirando, tem refresh) |
| `POST /api/meli/disconnect` | Remove tokens salvos (logout) |
| `GET /auth/meli/start` | Inicia OAuth → redireciona para ML |
| `GET /auth/meli/callback` | Callback do ML → troca code por tokens |
| `POST /api/search` | Resultado completo em JSON |
| `POST /api/search/stream` | Eventos SSE: `trace`, `intent`, `source`, `offers`, `analysis`, `done`, `error` |

**Exemplo de busca:**

```bash
curl -X POST http://127.0.0.1:8765/api/search \
  -H "Content-Type: application/json" \
  -d '{"query":"notebook i5 com 16GB até 4000","sources":["google_shopping","amazon"],"limit":20}'
```

---

## Como configurar o Mercado Livre (OAuth)

1. **Crie app** em https://developers.mercadolivre.com.br/devcenter/
2. **Redirect URI:** `http://localhost:8765/auth/meli/callback` (exato)
3. **Escopo:** Leitura
4. Copie `Client ID` e `Client Secret` para `.env`:

```env
MELI_CLIENT_ID=seu_client_id
MELI_CLIENT_SECRET=seu_client_secret
MELI_REDIRECT_URI=http://localhost:8765/auth/meli/callback
MELI_TOKEN_FILE=data/meli_token.json
```

5. Reinicie o app → no painel lateral clique **"Conectar Mercado Livre"** → autorize → pronto!

> Tokens renovam **automaticamente** (5 min antes de expirar). Refresh token é **single-use** — o novo é salvo a cada renovação.

---

## Adicionar uma fonte

1. Crie `connectors/minhaloja.py` herdando de `Connector`.
2. Implemente `configured`, `setup_hint` e `async def search(intent, limit)`.
3. Normalize para `Offer` (preço em BRL, URL https, `source`, `source_label`).
4. Registre em `connectors/__init__.py` e exponha em `Settings.public_config()`.
5. Erros esperados → lance `ConnectorError` com mensagem amigável.

---

## Limitações e boas práticas

- Use **APIs oficiais** e respeite termos de uso, limites e programas de afiliado.
- A API do Mercado Livre (`/sites/MLB/search`) pode retornar **403** para alguns apps — teste antes.
- Shopee e AliExpress são **experimentais**: assinatura/estrutura pode mudar.
- Modo demonstração usa URLs fictícias (`example.com`) e lojas inventadas.
- O app é **local**, sem autenticação. Não exponha na internet sem adicionar auth, rate limit e HTTPS.
- **Nunca** commite `.env` — chaves vazam no histórico!

---

## Roadmap

- [ ] Cache persistente (arquivo/Redis) — sobrevive a reinícios
- [ ] Watchlist + alertas de queda de preço (agendador)
- [ ] Histórico de preços por produto
- [ ] Exportar comparação em CSV/PDF
- [ ] Perfis de compra ("custo-benefício", "só original", "entrega rápida")
- [ ] Integração Ollama local para IA 100% offline
- [ ] Testes de integração dos conectores reais

---

## Licença

MIT — use, modifique, distribua. Veja [LICENSE](LICENSE) se existir.