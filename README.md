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
| `src/site.py` | Gera o dashboard estático publicado no GitHub Pages |
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

### Agendamento automático na nuvem (GitHub Actions)

O projeto também tem um workflow em `.github/workflows/scan.yml` para rodar sem
deixar seu computador ligado. Ele pode ser iniciado manualmente pelo botão
**Run workflow** no GitHub e também roda agendado de hora em hora.

Antes de ativar, cadastre os Secrets do repositório em:
`Settings → Secrets and variables → Actions → New repository secret`.

Secrets principais:

| Secret | Obrigatório? | Uso |
|---|---:|---|
| `RENTCAST_API_KEY` | Sim | Busca listagens e ARV/comps na RentCast |
| `REGRID_API_KEY` | Opcional | Zoneamento/uso do solo/dono da parcela (Regrid; **requer plano pago** — o trial não cobre Orlando) |
| `ZAPI_INSTANCE_ID` | Para WhatsApp | Instância da Z-API |
| `ZAPI_INSTANCE_TOKEN` | Para WhatsApp | Token da instância Z-API |
| `ZAPI_CLIENT_TOKEN` | Se sua Z-API exigir | Client token da Z-API |
| `ZAPI_PHONE` | Para WhatsApp | Número que recebe os alertas |
| `RAPIDAPI_KEY` / `RAPIDAPI_HOST` | Opcional | Fallback se trocar a fonte para RapidAPI |
| `SMTP_*` / `ALERT_EMAIL_TO` | Opcional | Alertas por e-mail |
| `TELEGRAM_*` | Opcional | Alertas por Telegram |

O workflow restaura e salva `seen_listings.db`, `region_signals.db`,
`opportunities.csv` e `evaluations.csv` usando cache do GitHub Actions, e
também **grava uma cópia permanente no branch `data` do repositório** ao fim
de cada rodada. Se o cache for despejado (o GitHub apaga caches após ~7 dias
sem uso), o estado é restaurado do branch `data` automaticamente — sem isso, a
rodada seguinte trataria tudo como novo e dispararia alertas repetidos. Os
CSVs e o banco também são enviados como artifacts por 14 dias para auditoria.

Para mudar a frequência, edite o cron no workflow:

```yaml
# de hora em hora
- cron: "0 * * * *"

# aproximadamente a cada 5 horas
- cron: "0 0,5,10,15,20 * * *"
```

### Resumo diário (sinal de vida)

Além dos alertas de cada rodada, o workflow `.github/workflows/summary.yml`
manda **um resumo consolidado 1x ao dia** (12:00 UTC = 8h de Orlando no horário
de verão) por WhatsApp/e-mail/Telegram, com a janela de `config.yaml →
summary.period_hours`. Ele **sempre envia** — mesmo sem oportunidade nova —
com as contagens do dia (avaliados, viáveis, radar) e o link do dashboard,
para que silêncio nunca deixe dúvida de que o sistema está rodando.

Para rodar manualmente:

```bash
python -m src.summary            # envia o resumo
python -m src.summary --dry-run  # só mostra no console
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

**Confirmação automática via GIS:** quando a listagem vem sem zoneamento, o
sistema consulta fontes de parcela por coordenada e preenche o uso do solo
antes da avaliação (`config.yaml → zoning_lookup`). A fonte preferencial é a
**Regrid Parcels API** (zoneamento, uso do solo e dono da parcela; liga
automaticamente quando `REGRID_API_KEY` existir). Atenção: o **trial da
Regrid não cobre Orlando** — a API responde "This area is not included in
API trials"; para dados reais é preciso um plano pago (regrid.com/api).
Sem chave válida, o sistema usa os GIS públicos (estadual e por county, com
raio de 30 m para geocodes que caem na rua) — validados em produção; se
tudo falhar, a listagem segue para o Radar, como sempre.
Residencial confirmado vira oportunidade viável direto no WhatsApp;
comercial/industrial/conservação é reprovado sem revisão manual; falha de
GIS mantém o comportamento atual (Radar). O resultado fica em cache por 90
dias e novas fontes (ex.: GIS de um county) podem ser adicionadas só no
config, sem mexer em Python.

### Normalização de endereço e red flags

O sistema normaliza endereços dos EUA com `usaddress` para reduzir duplicidade
quando a mesma oportunidade aparece com IDs diferentes em fontes diferentes. O
dedupe continua sensível a mudança de preço: mesmo endereço com novo preço pode
voltar a alertar.

Antes do WhatsApp, também existe uma checagem direta na FEMA National Flood
Hazard Layer (`config.yaml → red_flags.flood`). Zonas como `AE`, `VE` ou pontos
marcados como SFHA entram nas atenções do alerta e do CSV. Por padrão, falha na
FEMA não bloqueia alerta; ela apenas adiciona uma atenção para conferência manual.

### Sinais de crescimento da região

Para ajudar a identificar regiões em valorização, cada oportunidade (viável ou
radar) é enriquecida com sinais estudados de crescimento, usando fontes
públicas gratuitas:

- **Escolas e comércio próximos** (OpenStreetMap/Overpass): contagem num raio
  de 3 km do terreno.
- **Crescimento de população e renda** (US Census ACS 5 anos, por ZIP):
  variação percentual em 5 anos.

Os sinais viram um **score 0–10** (`config.yaml → region_signals`) que aparece
nos cards "Crescimento por região" do dashboard, na coluna "Região ↑" das
tabelas, no popup do mapa, no CSV (`growth_score`, `growth_signals`) e na
mensagem do WhatsApp. Falha de API nunca bloqueia alerta — só deixa o sinal
vazio. Os resultados ficam em cache por ZIP (`region_signals.db`, revalidado a
cada 30 dias), então o custo por rodada é de poucas chamadas.

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
Maps, Zillow, Realtor e para o **mapa da Regrid nas coordenadas do lote** (com
uma conta Regrid Pro logada, mostra o dono da parcela e o zoneamento — dado
chave para abordagem off-market). Se a fonte trouxer o link original da
listagem, ele também entra na mensagem. Para evitar excesso, o padrão envia só as 10 melhores
oportunidades por rodada (`WHATSAPP_MAX_OPPORTUNITIES` no `.env`).

Além dos alertas de oportunidade, `config.yaml → notifications.whatsapp_run_summary`
envia um resumo operacional a cada rodada: quantas listagens foram encontradas,
quantas já eram vistas, quantas reprovaram e quantas viraram oportunidade. Assim
você sabe que o monitor rodou mesmo quando não há nada para comprar.

Se o workflow inteiro **falhar** (API fora, erro inesperado), um alerta de pane
é enviado por WhatsApp com o link da execução — silêncio significa "sem
oportunidade", nunca "sistema quebrado".

Antes do WhatsApp, o sistema faz uma checagem de disponibilidade com dados
estruturados da fonte: status ativo, sem `removedDate`, visto recentemente,
listado há poucos dias e com MLS. Isso reduz casos em que o endereço aparece no
Zillow como vendido/off-market. O Zillow continua como link de conferência, não
como fonte automática por scraping.

Antes do WhatsApp, o sistema faz a checagem de disponibilidade descrita acima.
Listagens **sem número de MLS** não são mais descartadas em silêncio: elas
passam com a atenção "MLS ausente (conferir listagem manualmente)" no alerta.
Para voltar ao comportamento restritivo, ligue `availability.require_mls_number`.

O padrão busca listagens com `daysOld: "0-7"` e até 3 páginas por rodada
(`max_pages: 3`, ~300 listagens). Esses valores são ajustáveis em `config.yaml`.

## Testes

```bash
pip install -r requirements-dev.txt
pytest
```

O workflow `.github/workflows/tests.yml` roda a suíte automaticamente em cada
push e pull request.

## Dashboard para a empresa (GitHub Pages)

A cada varredura, o workflow gera um **dashboard estático** com KPIs, mapa e
tabelas (viáveis, radar e todas as avaliações) e publica no GitHub Pages:

```
https://gchohfi.github.io/Zillow/
```

É esse link que você passa para a empresa acompanhar as oportunidades — ele
também sai no resumo de rodada do WhatsApp. O dashboard tem busca por
endereço/ZIP/região, filtros por status e download dos CSVs.

> ⚠️ Como o repositório é público, o dashboard também é público: qualquer pessoa
> com o link vê os dados. Se isso for um problema, torne o repositório privado
> (Pages privado exige plano pago) ou me peça outra forma de publicação.

Para ativar na primeira vez: o workflow tenta habilitar o Pages sozinho; se a
etapa "Configure GitHub Pages" falhar, habilite manualmente em
`Settings → Pages → Source: GitHub Actions` e rode o workflow de novo.

Para gerar localmente sem publicar:

```bash
python -m src.site        # escreve site/index.html a partir dos CSVs
```

A janela de dados exibida é `config.yaml → site.period_days` (padrão 30 dias).

## Dashboard interno (Streamlit)

O painel Streamlit mostra oportunidades, avaliações reprovadas, tese de mercado,
red flags e mapa interativo quando houver coordenadas no CSV:

```bash
streamlit run dashboard.py
```

O dashboard lê `opportunities.csv` e `evaluations.csv`. O segundo arquivo é criado
automaticamente com toda listagem nova avaliada, mesmo quando ela não vira alerta.

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
− Preparação do lote                      = site_prep_cost (limpeza, aterro, conexões)
− Impact fees do county                   = impact_fees (por unidade)
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

Além disso:

- **Preparação do lote e impact fees** entram na conta por segmento
  (`costs.site_prep_cost` / `costs.impact_fees`). Os valores padrão são
  estimativas de mercado de Central FL — **calibre com os seus números**
  (0 desliga). Eles apertam a régua de propósito: eram custos reais que a
  fórmula ignorava.
- **Impact fees por county** (`config.yaml → county_costs`): quando o ZIP da
  listagem é conhecido, os custos do county sobrepõem os do segmento —
  Osceola cobra bem mais que Polk, e um valor único mascarava isso. ZIPs
  fora da tabela usam os valores do segmento.
- **Cenário pessimista em toda avaliação** (`config.yaml → stress`): cada
  oportunidade mostra lucro e margem também com ARV 10% menor e obra 10%
  mais cara — no WhatsApp, no CSV (`margin_stress`) e no dashboard. Margem
  negativa no pessimista vira atenção no alerta (não bloqueia).
- **Divergência de ARV** (`arv.divergence_warn_pct`): quando o ARV dos comps
  diverge mais de 15% da premissa fixa, a oportunidade ganha a atenção
  "conferir comps" — divergência grande significa incerteza no número mais
  importante da conta.
- **Validação do config na largada**: erros de digitação no `config.yaml`
  (percentual acima de 1, campo ausente) param a execução com mensagem
  clara em vez de produzir números silenciosamente errados.
- **Trava de qualidade do ARV**: comps agora exigem mínimo de 5
  (`arv.min_comps`); AVM com confiança baixa acima da premissa fica
  **limitado à premissa** (`arv.cap_confidences`), evitando falso positivo
  por AVM otimista.
- **Lote mínimo por segmento**: médio padrão exige 7.000 sqft (casa de
  2.200 sqft + recuos), alto padrão 12.000 sqft.

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
