# Orlando Land Detector 🏗️

Detector de oportunidades de **terreno para spec build** (comprar terreno → construir casa → vender)
num raio de **150 km de Orlando, FL**, com cálculo automático de viabilidade financeira.

O sistema busca novas listagens de terreno, filtra por distância, lembra o que já viu
(para te avisar só do que é **novo**), aplica a **sua fórmula de viabilidade** e te alerta
quando aparece algo que vale a pena.

---

## Como funciona (pipeline)

```
  Fonte de dados        Geofiltro          Novidade           Viabilidade         Alerta
 (listagens novas) ──▶ (≤150km de   ──▶ (já vi antes? ) ──▶ (a fórmula diz   ──▶ (e-mail /
                        Orlando)          guarda no DB)        viável?)             Telegram /
                                                                                   console)
```

Arquivos principais:

| Arquivo | Papel |
|---|---|
| `config.yaml` | **A sua fórmula** e parâmetros (margem alvo, custo de construção, raio, etc.) |
| `src/datasource.py` | Cliente da fonte de dados (Fase 1: Realtor.com via RapidAPI; tem modo `mock`) |
| `src/geo.py` | Cálculo de distância (Haversine) a partir de Orlando |
| `src/storage.py` | Banco SQLite que lembra listagens já vistas → detecta o que é novo |
| `src/viability.py` | Motor de viabilidade do spec build |
| `src/notifier.py` | Envio de alertas (console, e-mail SMTP, Telegram) |
| `src/main.py` | Orquestra tudo: busca → filtra → pontua → alerta |

---

## Fonte de dados — estratégia em 3 fases

> ⚠️ O **Zillow não tem mais API pública** para listagens e fazer scraping viola os termos
> deles. Por isso o projeto usa fontes melhores e legais.

1. **Fase 1 — Protótipo (este código):** Realtor.com via [RapidAPI](https://rapidapi.com)
   (tem plano gratuito/barato). Roda em modo `mock` sem chave nenhuma, para você testar
   a fórmula e o pipeline de ponta a ponta.
2. **Fase 2 — Produção leve:** [Regrid](https://regrid.com) (dados de parcela/lote e
   zoneamento) + [ATTOM](https://www.attomdata.com) (valor de revenda / comps).
3. **Fase 3 — Tempo real:** feed da **Stellar MLS** (a MLS de Orlando) via RESO Web API,
   obtido por um corretor parceiro. É aqui que você pega a oportunidade no momento em que sai.

A arquitetura já está pronta para trocar a fonte: basta criar uma nova classe em
`src/datasource.py` que herde de `DataSource` e implemente `fetch_new_land_listings()`.

---

## Instalação

```bash
cd orlando-land-detector
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # preencha as chaves quando tiver
```

## Uso

```bash
# Roda com dados de exemplo (mock) — não precisa de chave nenhuma:
python -m src.main --mock

# Roda de verdade (precisa de RAPIDAPI_KEY no .env):
python -m src.main

# Só mostra no console, sem mandar alerta:
python -m src.main --mock --dry-run
```

Para rodar de tempos em tempos, use um agendador (cron). Ex.: a cada hora:

```
0 * * * * cd /caminho/orlando-land-detector && .venv/bin/python -m src.main >> run.log 2>&1
```

## Testes

```bash
pip install pytest
pytest
```

---

## A fórmula de viabilidade (spec build)

Para cada terreno, o motor calcula:

```
ARV (valor de revenda da casa pronta)   = preço_revenda_por_sqft × área_construída
− Preço do terreno (o preço da listagem)
− Custo de construção                    = custo_construção_por_sqft × área_construída
− Custos "soft" (projeto, licenças)      = soft_cost_pct × custo_construção
− Custos de carrego (juros, IPTU, seguro)= carrying_cost_pct × (terreno + construção)
− Custos de venda (comissão + closing)   = selling_cost_pct × ARV
= LUCRO estimado

Margem = LUCRO / ARV
```

**Regras de corte** (ajustáveis em `config.yaml`) que decidem viável / não viável:

- Terreno deve ser **≤ `max_land_to_arv_pct`** do ARV (regra clássica de incorporador, ~20%)
- Margem líquida **≥ `target_margin`** (ex.: 18%)
- Zoneamento deve permitir residencial (quando o dado existir)

Todos esses números são **seus** — edite `config.yaml`.

---

## Transformar isto num repositório próprio

Quando quiser separar este projeto num repositório dedicado:

```bash
# 1. Crie um repo vazio no GitHub (ex.: orlando-land-detector)
# 2. A partir desta pasta:
cd orlando-land-detector
git init
git add .
git commit -m "Initial commit: Orlando land detector"
git branch -M main
git remote add origin https://github.com/gchohfi/orlando-land-detector.git
git push -u origin main
```
