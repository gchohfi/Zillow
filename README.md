# Orlando Land Detector 🏗️

Detector de oportunidades de **terreno para spec build** (comprar terreno → construir casa → vender)
num raio inicial de **80 km de Orlando, FL**, com cálculo automático de viabilidade financeira.

O sistema busca novas listagens de terreno, filtra por distância, lembra o que já viu
(para te avisar só do que é **novo**), estima o ARV com comps da RentCast quando
disponível, aplica a **sua fórmula de viabilidade** e te alerta quando aparece
algo que vale a pena.

---

## Como funciona (pipeline)

```
  Fonte de dados        Geofiltro          Novidade           Viabilidade         Alerta
 (listagens novas) ──▶ (≤80km de    ──▶ (já vi antes? ) ──▶ (a fórmula diz   ──▶ (e-mail /
                        Orlando)          guarda no DB)        viável?)             Telegram /
                                                                                   console)
```

Arquivos principais:

| Arquivo | Papel |
|---|---|
| `config.yaml` | **A sua fórmula** e parâmetros (margem alvo, custo de construção, raio, etc.) |
| `src/datasource.py` | Cliente da fonte de dados (Fase 1: RapidAPI configurável; tem modo `mock`) |
| `src/geo.py` | Cálculo de distância (Haversine) a partir de Orlando |
| `src/storage.py` | Banco SQLite que lembra listagens já vistas → detecta o que é novo |
| `src/viability.py` | Motor de viabilidade do spec build |
| `src/notifier.py` | Envio de alertas (console, e-mail SMTP, Telegram, WhatsApp via Z-API) |
| `src/main.py` | Orquestra tudo: busca → filtra → pontua → alerta |

---

## Fonte de dados — estratégia em 3 fases

> ⚠️ O **Zillow não tem mais API pública** para listagens e fazer scraping viola os termos
> deles. Por isso o projeto usa fontes melhores e legais.

1. **Fase 1 — Protótipo/produção leve (este código):** [RentCast](https://www.rentcast.io/api)
   como fonte preferencial de listagens à venda, com RapidAPI como fallback configurável.
   Roda em modo `mock` sem chave nenhuma, para você testar a fórmula e o pipeline de ponta a ponta.
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

Para testar com RentCast, preencha `RENTCAST_API_KEY` no `.env`.

## Uso

```bash
# Roda com dados de exemplo (mock) — não precisa de chave nenhuma:
python -m src.main --mock

# Roda de verdade (precisa de RENTCAST_API_KEY no .env):
python -m src.main

# Só mostra no console, sem mandar alerta:
python -m src.main --mock --dry-run
```

### Saída em planilha (CSV)

Toda oportunidade **viável** é acrescentada em `opportunities.csv` (caminho em
`config.yaml → output.csv_path`), com colunas de preço, ARV, lucro, margem,
distância e link. Abra direto no Excel/Google Sheets.

### Agendamento automático (cron)

Já existe um `run.sh` pronto. Para rodar **de hora em hora**, rode `crontab -e`
e cole (ajuste o caminho):

```
0 * * * * /caminho/orlando-land-detector/run.sh >> /caminho/orlando-land-detector/run.log 2>&1
```

A cada execução ele busca o que é novo, calcula viabilidade, grava no CSV e
dispara os alertas. Como ele lembra o que já viu (SQLite), você só é avisado de
oportunidades **inéditas**.

### Resumo diário por e-mail

Além dos alertas de cada rodada, dá para receber **um resumo consolidado 1x ao dia**
(janela em `config.yaml → summary.period_hours`). Ele lê o `opportunities.csv` e
manda tudo junto, ordenado pela maior margem:

```bash
python -m src.summary            # envia o resumo
python -m src.summary --dry-run  # só mostra no console
```

No cron, por exemplo todo dia às 8h:
```
0 8 * * * cd /caminho/orlando-land-detector && .venv/bin/python -m src.summary >> run.log 2>&1
```

### Filtro de tamanho mínimo de lote

`config.yaml → rules.min_lot_size_sqft` descarta terrenos menores que o valor (em
sqft). Use `0` para desligar. Listagens sem o dado de lote passam com um aviso.

### Filtro de zoneamento

O sistema também segura oportunidades cujo zoneamento não esteja claramente
compatível com uso residencial. Em `config.yaml → rules`, `require_known_zoning:
true` faz com que listagens sem zoneamento sejam bloqueadas antes do alerta,
em vez de chegarem no WhatsApp como viáveis. As listas
`residential_zoning_hints` e `prohibited_zoning_hints` permitem ajustar padrões
locais como `R-1`, `RSF`, `PUD`, comercial, industrial, conservação etc.

### Tese de mercado por ZIP

Além da matemática, o sistema classifica cada oportunidade pela tese de mercado
do relatório Arwell. Em `config.yaml → market_strategy`, cada grupo de ZIPs tem
prioridade, pontuação, teses prováveis e riscos de diligência. O WhatsApp e o CSV
passam a mostrar região, prioridade, tese e atenções como `checar utilities`,
`checar HOA/CDD`, `checar STR legality por endereço` ou `checar airport/noise
overlay`.

Essa camada ajuda a separar um terreno apenas barato de uma oportunidade dentro
das regiões-alvo: Lake Nona/Narcoossee, Horizon West/Winter Garden,
Minneola/Clermont, St. Cloud/NeoCity, Kissimmee/Four Corners/Davenport e outros
corredores do relatório.

### ARV por comps reais

Antes de calcular a viabilidade, o sistema tenta chamar o endpoint RentCast AVM
para estimar o valor da casa pronta hipotética (`Single Family`) com as premissas
do segmento: área, quartos e banheiros. Se a AVM retornar valor e comps
suficientes, esse ARV substitui o preço fixo por sqft do `config.yaml`. Se a
chamada falhar ou vier fraca, o sistema volta para a premissa fixa e marca isso
no alerta.

### Cobertura dos 80 km

A primeira peneira busca terrenos até **80 km** de Orlando. Os tetos de preço
ficam por segmento em `config.yaml → tiers`: baixo padrão até US$ 50.000,
médio padrão até US$ 300.000, e alto padrão acima disso fica marcado para
análise manual de localização.
Se quiser voltar para uma área maior, aumente `search.radius_km` e reative
pontos sobrepostos em `config.yaml → datasource.rentcast.search_points`.

### Alertas por WhatsApp

O alerta por WhatsApp manda uma mensagem curta por oportunidade com endereço,
segmento, preço, ARV, lucro, margem, distância e links automáticos para Google
Maps, Zillow e Realtor. Se a fonte trouxer o link original da listagem, ele
também entra na mensagem. Para evitar excesso, o padrão envia só as 10 melhores
oportunidades por rodada (`WHATSAPP_MAX_OPPORTUNITIES` no `.env`).

Antes do WhatsApp, o sistema faz uma checagem de disponibilidade com dados
estruturados da fonte: status ativo, sem `removedDate`, visto recentemente,
listado há poucos dias e com MLS. Isso reduz casos em que o endereço aparece no
Zillow como vendido/off-market. O Zillow continua como link de conferência, não
como fonte automática por scraping.

Para economizar chamadas no primeiro teste, o padrão busca listagens com
`daysOld: "1-14"` e apenas a primeira página (`max_pages: 1`). Esses valores são
ajustáveis em `config.yaml`.

## Testes

```bash
pip install -r requirements-dev.txt
pytest
```

---

## A fórmula de viabilidade (spec build)

Para cada terreno, o motor calcula:

```
ARV (valor de revenda da casa pronta)   = RentCast AVM/comps, ou fallback preço_revenda_por_sqft × área
− Preço do terreno (o preço da listagem)
− Custo de construção                    = custo_construção_por_sqft × área_construída
− Custos "soft" (projeto, licenças)      = soft_cost_pct × custo_construção
− Closing da compra do terreno           = purchase_closing_pct × terreno
− Contingência de obra                    = contingency_pct × construção
− Custos de carrego (juros, IPTU, seguro)= carrying_cost_annual_pct × meses/12 × (terreno + construção)
− Custos de venda (comissão + closing)   = selling_cost_pct × ARV
= LUCRO estimado

Margem = LUCRO / ARV
Terreno/investimento total = Preço do terreno / Custo total estimado
```

**Regras de corte** (ajustáveis em `config.yaml`) que decidem viável / não viável:

- Terreno deve ser **≤ `max_land_to_total_investment_pct`** do investimento total, hoje 27%
- No baixo padrão, preço do terreno deve ser **≤ `max_land_price`**, hoje US$ 50.000
- Alto padrão não é aprovado automaticamente: exige análise de bairro/demanda
- Margem líquida **≥ `target_margin`** (ex.: 18%)
- Listagens com preço zerado ou inválido são descartadas antes de gerar alerta
- Zoneamento deve permitir residencial; se `require_known_zoning` estiver ligado,
  zoneamento ausente também bloqueia alerta automático

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
