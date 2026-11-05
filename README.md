# Squad de Ofertas

Aplicação web local em Python onde você descreve o que quer comprar — produto, especificações e
orçamento — e um **squad de agentes** busca, compara e recomenda a melhor oferta.

> Sem chaves de API, o app roda em **modo demonstração** com ofertas simuladas. Basta abrir e usar.

## Como rodar

```bat
iniciar.bat
```

O script cria a virtualenv, instala as dependências, copia `.env.example` para `.env` na primeira
execução e abre `http://127.0.0.1:8765`.

Manual:

```bash
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Requisitos: Python 3.11+ (testado no 3.14) e conexão com a internet apenas para fontes reais/IA.

## O squad

| Agente | Papel | O que faz |
| --- | --- | --- |
| **Intenção** | interpreta | Extrai produto, especificações, orçamento, restrições e exclusões. Usa regras locais e, se houver LLM, refina o resultado. |
| **Busca** | coleta | Consulta todas as fontes selecionadas em paralelo, com timeout por fonte. Uma fonte que falha não derruba a busca. |
| **Curadoria** | filtra | Normaliza títulos, remove duplicatas por similaridade, aplica orçamento/exclusões, confere specs e calcula o score. |
| **Análise** | decide | Compara preço, nota, avaliações, frete e specs; aponta prós/contras e escreve a recomendação. |

Fluxo: `texto livre → intenção → busca paralela → curadoria → análise → recomendação`.
A tela mostra o squad trabalhando em tempo real via SSE (`/api/search/stream`).

### Score (0–100)

| Peso | Critério |
| --- | --- |
| 34% | preço relativo ao menor preço do resultado |
| 20% | nota do produto (quando disponível) |
| 15% | specs atendidas |
| 13% | confiabilidade da fonte |
| 10% | frete grátis |
| 8% | volume de avaliações |

O score é uma heurística transparente, não uma promessa de melhor compra. Preço e disponibilidade
mudam — confirme sempre na loja.

## Fontes de ofertas

Configure no `.env` (veja `.env.example`):

| Fonte | Chaves | Observações |
| --- | --- | --- |
| **Demonstração** | — | Sempre disponível. Gera ofertas plausíveis e determinísticas para qualquer busca. |
| **Mercado Livre** | `MELI_ACCESS_TOKEN` | API oficial. Tokens expiram; renove no painel de desenvolvedor. |
| **Google Shopping** | `SERPAPI_KEY` | Via [SerpAPI](https://serpapi.com/), com plano gratuito limitado. |
| **Amazon** | `AMAZON_ACCESS_KEY`, `AMAZON_SECRET_KEY`, `AMAZON_PARTNER_TAG` | PA-API 5.0 com assinatura SigV4. Exige conta de afiliado aprovada. |
| **Shopee** | `SHOPEE_APP_ID`, `SHOPEE_SECRET` | Open API de afiliados. **Experimental** — requer aprovação no programa. |
| **AliExpress** | `ALIEXPRESS_APP_KEY`, `ALIEXPRESS_SECRET`, `ALIEXPRESS_TRACKING_ID` | Affiliate API. **Experimental** — assinatura e endpoint podem variar por conta. |

Para usar **somente** fontes reais: `DEMO_MODE=false`.
Se uma fonte falhar, a tela mostra o motivo (chave inválida, limite, tempo esgotado) sem interromper
as demais.

### IA (opcional)

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
# OPENAI_BASE_URL=https://api.openai.com/v1
```

Qualquer endpoint compatível com OpenAI Chat Completions serve (OpenAI, OpenRouter, Ollama com
camada compatível etc.). Sem IA, a interpretação e a análise usam regras locais — o app continua
100% funcional.

## Estrutura

```
app.py                     FastAPI, SSE e arquivos estáticos
core/
  config.py                leitura do .env e configuração pública
  models.py                contratos (Intent, Offer, Analysis, SearchResult…)
  orchestrator.py          encadeamento dos agentes e streaming
  utils.py                 texto, preço, similaridade
agents/
  intent.py                intenção (regras + LLM)
  curator.py               dedupe, filtros, score
  analyst.py               estatísticas e recomendação
connectors/
  demo.py                  catálogo simulado
  mercadolivre.py          API oficial
  amazon.py                PA-API 5.0 (SigV4)
  google_shopping.py       SerpAPI
  shopee.py                afiliados (experimental)
  aliexpress.py            afiliados (experimental)
web/                       tela (HTML/CSS/JS, sem build)
```

### API

- `GET /api/config` — fontes disponíveis e status (sem expor segredos)
- `GET /api/health`
- `POST /api/search` — retorna o resultado completo em JSON
- `POST /api/search/stream` — eventos SSE: `trace`, `intent`, `source`, `offers`, `analysis`, `done`, `error`

Exemplo:

```bash
curl -X POST http://127.0.0.1:8765/api/search \
  -H "Content-Type: application/json" \
  -d '{"query":"notebook i5 com 16GB até 4000","limit":20}'
```

## Adicionar uma fonte

1. Crie `connectors/minhaloja.py` herdando de `Connector`.
2. Implemente `configured`, `setup_hint` e `async def search(intent, limit)`.
3. Normalize tudo para `Offer` (preço em BRL, URL https, `source` e `source_label`).
4. Registre em `connectors/__init__.py` e exponha em `Settings.public_config()`.
5. Erros esperados devem lançar `ConnectorError` com mensagem amigável.

## Limitações e boas práticas

- Use **APIs oficiais** e respeite termos de uso, limites e programas de afiliado. Scraping de
  marketplaces é frágil e pode violar contratos.
- A API do Mercado Livre pode exigir autenticação/renovação de token dependendo do app e do país.
- Shopee e AliExpress estão marcadas como experimentais: a assinatura/estrutura pode mudar.
- O modo demonstração usa URLs fictícias (`example.com`) e lojas inventadas.
- O app é local, sem autenticação. Não exponha a porta na internet sem adicionar autenticação,
  rate limit e HTTPS.

## Próximos passos sugeridos

- [ ] Persistir buscas e criar alertas de queda de preço (watchlist + agendador)
- [ ] Histórico de preços por produto
- [ ] Cache de resultados e rate limit por fonte
- [ ] Testes automatizados dos agentes e conectores
- [ ] Exportar comparação em CSV/PDF
- [ ] Perfis de compra (ex.: “custo-benefício”, “só original”, “entrega rápida”)
