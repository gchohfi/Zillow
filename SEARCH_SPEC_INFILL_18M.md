# Especificação adicional de busca — Infill residencial, ciclo de 18 meses

Status: especificação operacional v1  
Origem: páginas fotografadas `IMG_4616.JPG` a `IMG_4628.JPG`, fornecidas pela usuária em 05/08/2026  
Implementação: `config.yaml → search_spec_infill_18m` e `src/search_spec.py`

## 1. Objetivo

Adicionar ao Orlando Land Detector uma lente independente para localizar e priorizar terrenos ou imóveis antigos com potencial de demolição e reconstrução de residências premium em bairros consolidados de Orlando.

A lente não substitui o motor atual de spec build e não aprova investimentos. Ela responde: **“Esta listagem merece underwriting pelo modelo de infill residencial com ciclo-alvo de 18 meses?”**

## 2. Separação de modelos

- O motor principal continua decidindo `viavel`, `radar_*` ou `reprovado` com as regras vigentes.
- A nova lente classifica cada avaliação como `aderente`, `revisar` ou `fora`.
- A TIR de 23% a.a., as faixas de custo e os valores de saída são premissas fornecidas, não retornos garantidos.
- Nenhuma listagem pode ser promovida a investimento apenas por pontuação de aderência.

## 3. Tese operacional

- Capital por cota: US$ 250 mil.
- Referência de portfólio: 8 grupos, 2 residências por grupo, 16 casas no total.
- Estrutura de referência: 3 cotas por projeto, 24 cotas e US$ 6 milhões no programa completo.
- Ciclo-alvo por residência: aproximadamente 18 meses.
- Retorno-alvo de referência: aproximadamente 23% a.a.
- Produto: Modern Farmhouse Premium, estrutura CBS/concrete block, janelas de impacto, acabamentos premium e, quando suportado pelo lote e mercado, piscina, spa e cozinha externa.

Esses itens descrevem o programa de referência. A busca avalia oportunidades individuais e não presume que a estrutura de captação esteja disponível.

## 4. Mercados e benchmarks iniciais

| Mercado | ZIPs | Aquisição | Obra por sqft | Venda por sqft | Saída de referência |
|---|---|---:|---:|---:|---:|
| Winter Park | 32789, 32792 | US$ 750–850 mil | US$ 220–230 | US$ 700 | ~US$ 2,2 mi |
| Orlando · SODO | 32806 | US$ 350–450 mil | US$ 160 | US$ 380–480 | US$ 1,1–1,4 mi |
| College Park | 32804 | US$ 500–550 mil | US$ 210–220 | US$ 480 | ~US$ 1,4 mi |
| Maitland | 32751 | a calibrar | a calibrar | referência de US$ 513 | a calibrar |

Maitland entra como região de comparáveis e revisão manual até que aquisição, obra e saída sejam confirmadas.

## 5. Pontuação de aderência

A pontuação vai de 0 a 100 e serve apenas para ordenar a investigação:

- 35 pontos: ZIP pertence a um mercado da especificação;
- 25 pontos: preço pedido está até o teto de aquisição do mercado;
- 20 pontos: ARV com fonte externa alcança a faixa mínima de saída;
- 10 pontos: zoning residencial indicativo;
- 10 pontos: ausência de bloqueio ambiental conhecido na triagem.

Regras:

- `aderente`: 70 pontos ou mais, sem bloqueio;
- `revisar`: 45 a 69 pontos, sem bloqueio;
- `fora`: menos de 45 pontos ou bloqueio explícito;
- preço até 15% acima do teto recebe crédito parcial e exige negociação;
- preço mais de 15% acima do teto é bloqueio para esta lente;
- ARV vindo apenas de configuração recebe crédito parcial e exige comps vendidos;
- zoning incompatível ou diligência impeditiva força `fora`;
- flood de alto risco gera alerta, orçamento de seguro e mitigação, mas não é descartado silenciosamente.

## 6. Evidências obrigatórias antes de avançar

1. Comps vendidos recentes, equivalentes em microlocalização, área, padrão e amenidades.
2. Zoning legal, FAR, setbacks, altura, cobertura e capacidade construtiva.
3. Orçamento de aquisição, demolição, projeto, licenças, obra, contingência, carrego e venda.
4. Flood, seguro, título, utilities, acesso e restrições do lote.
5. Cronograma com buffer e estratégia de preço/staging antes da listagem.
6. Liquidez e absorção do micromercado.

## 7. Dados produzidos

Cada linha de avaliação passa a registrar:

- nome, região, status e pontuação da especificação;
- justificativas da classificação;
- faixas-alvo de aquisição, obra, venda e saída;
- ciclo e TIR de referência.

Esses campos saem no CSV de avaliações, entram no payload do dashboard e podem ser encontrados pela busca textual usando termos como `infill`, `aderente`, `revisar`, `Winter Park`, `SODO`, `College Park` ou `Maitland`.

## 8. Fora de escopo desta versão

- alterar a aprovação financeira principal;
- garantir TIR ou prazo;
- buscar automaticamente casas antigas quando a fonte estiver configurada apenas para `Land`;
- confirmar comps, zoning, licenças ou custo de construção sem fonte externa;
- modelar a captação e distribuição entre cotistas.

## 9. Critérios de aceite

- Uma listagem no ZIP 32789 recebe a região Winter Park e os benchmarks correspondentes.
- Uma listagem fora dos ZIPs mapeados recebe status `fora` e motivo explícito.
- Uma listagem acima de 115% do teto do mercado não pode receber status `aderente`.
- ARV de configuração não é apresentado como comp confirmado.
- Os campos da lente são persistidos no CSV e pesquisáveis no dashboard.
- O resultado principal de viabilidade permanece inalterado pela nova lente.
