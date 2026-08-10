# CLAUDE.md — Instruções do projeto

Guia para sessões de IA e colaboradores. Contexto: detector de oportunidades
de terreno para spec build em Orlando/FL, operado por uma usuária não
programadora — **explicações em português, sem jargão desnecessário**.

## O que é o sistema

Pipeline Python que roda no GitHub Actions (hourly, `scan.yml`): busca
listagens de terreno (RentCast) num raio de 80 km de Orlando, detecta o que é
novo (SQLite), enriquece (zoneamento via GIS, ARV por comps, aluguel, zona
FEMA, sinais de crescimento, tese de mercado por ZIP), avalia viabilidade de
spec build (comprar → construir → vender) com estresse e matriz de
sensibilidade, e alerta por WhatsApp (Z-API). Publica dashboard + `data.json`
+ memorandos no GitHub Pages. Resumo diário às 12:00 UTC (`summary.yml`).

## Princípios que governam o código

1. **Tudo configurável em `config.yaml`** — a fórmula é da usuária. Novos
   parâmetros de negócio entram no config com comentário em PT-BR explicando
   o que é e marcando "AJUSTE COM SEUS NÚMEROS" quando for estimativa.
2. **Silêncio nunca pode significar "quebrado"** — falha de API externa não
   bloqueia alerta (fail-open com atenção ⚠); pane do workflow dispara
   WhatsApp; o resumo diário sempre envia.
3. **Falso positivo é pior que falso negativo** — travas de qualidade (ARV
   capado com confiança baixa, min_comps, zoneamento exigido) existem para o
   WhatsApp não recomendar terreno ruim. Não as afrouxe sem pedido explícito.
4. **Tri-estado, não binário**: viável / radar (revisão manual com motivo) /
   reprovado. Pendência de dado → radar, nunca aprovação silenciosa.
5. **Cota de API é dinheiro**: RentCast rent-AVM só roda para candidatos a
   alerta/radar; zoneamento e sinais têm cache em SQLite (`region_signals.db`).
6. **Estado entre rodadas**: cache do Actions + cópia permanente no branch
   `data` (restaurada automaticamente se o cache evaporar). Nunca apague os
   .db/.csv de produção sem preservar esse fluxo.

## Decisões já tomadas (não reabrir sem novidade)

- **Zillow**: sem API pública; scraping viola os termos. Fonte é RentCast
  (fallback RapidAPI configurável). Zillow fica só como link de conferência.
- **Regrid**: o trial da API é restrito a 7 counties de amostra (Orlando
  fora — "This area is not included in API trials"); a v2 devolve vazio em
  silêncio. A usuária tem o plano **Pro do app de mapa** (US$ 10/mês, uso
  manual: dono da parcela + zoneamento), **não** o plano de API. A integração
  de código está pronta e liga sozinha se um dia houver token de API pago no
  secret `REGRID_API_KEY`. Links "Regrid" nos alertas/dashboard abrem o mapa
  nas coordenadas (`app.regrid.com/map#ll=lat,lng&z=17`).
- **Zoneamento em produção**: GIS públicos gratuitos (camada estadual +
  camadas por county, raio de 30 m para geocode na rua), com cache de 90
  dias e retry de falha em 6h. Validado em produção.
- **Seguro na Flórida é variável central**: zona FEMA de alto risco soma
  `red_flags.flood.insurance_surcharge_annual` ao carrego e ao NOI.
- **Pontuação de mercado** (`market_strategy`): derivada do relatório Arwell
  Orlando Market Research (arquivos não estão no repo — repo é público).

## Convenções

- Comentários e mensagens de usuário em **português**; identificadores em
  inglês. Docstrings curtas explicando o *porquê*.
- Testes em `tests/` (pytest); CI roda em cada push/PR (`tests.yml`).
  **Nada entra na main sem a suíte verde.** Toda feature nova leva teste.
- CSVs têm migração automática de cabeçalho (`reporter._ensure_header`) —
  para adicionar coluna, adicione nas DUAS listas e nos DOIS writers.
- Campos novos de resultado: `models.ViabilityResult` → reporter (CSV) →
  `site._ROW_FIELDS`/`_FLOAT_FIELDS` (dashboard + data.json) → notifier
  (WhatsApp) quando fizer sentido.
- Fluxo de mudança: branch `claude/...` → PR → CI verde → squash-merge na
  `main`. A rodada seguinte do Actions já usa o código novo.
- Segredos só em GitHub Actions Secrets (nunca em código/commit — repo
  público). A sessão de IA não consegue escrever secrets: pedir à usuária.

## Operação

- Workflows: `scan.yml` (varredura hourly + smoke test de zoneamento +
  deploy do Pages + persistência no branch `data`), `summary.yml` (resumo
  diário 12:00 UTC), `tests.yml` (CI).
- Dashboard: https://gchohfi.github.io/Zillow/ · dados: `/data.json` ·
  memorandos: `/memo/<id>.html`.
- Smoke test do zoneamento roda a cada rodada com coordenada fixa do centro
  de Orlando; linha `[smoke]` no log diz qual fonte respondeu. Com
  `REGRID_API_KEY` presente, vira health check da assinatura (avisa se a
  resposta cair para o GIS público e sonda `/usage` para diagnóstico).
- Debug de rodada: log do job no Actions; estado histórico no branch `data`;
  artifacts de CSV/DB por 14 dias.

## Comandos úteis

```bash
python -m pytest -q                 # suíte completa
python -m src.main --mock --dry-run # pipeline ponta a ponta sem chaves
python -m src.site                  # gera site/ localmente a partir dos CSVs
python -m src.summary --dry-run     # resumo diário no console
```
