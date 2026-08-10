# Piloto RentCast Developer — handoff operacional

Este documento descreve o limite operacional do piloto de sete dias. Ele não
autoriza o agente de código a ativar plano, acessar ou alterar secrets, disparar
o workflow, fazer merge ou gerar gasto.

## Pré-condições e sequência

1. Revisão humana e merge do Draft PR do Gate 6.
2. Confirmar no GitHub que o workflow publicado contém `0 */6 * * *`.
3. O operador/Board ativa **somente** o plano API Developer. Não selecionar
   Foundation, Growth ou Scale; não alterar cartão nem o trial RentCast Pro.
4. O operador executa uma única validação controlada após a ativação.
5. Manter o piloto por sete dias, sem reprocessar histórico e sem alterar as 57
   chaves já registradas no estado do scanner.

## Barreira de consumo do AVM

O pipeline chama o AVM de valor somente depois de o item:

- estar dentro do raio;
- não existir no `seen_listings.db` com a mesma chave de deduplicação;
- não duplicar outro item já reservado na mesma rodada;
- passar pelo filtro de disponibilidade/frescor; e
- passar pela avaliação inicial com premissas locais como viável ou Radar.

Depois do enriquecimento, a avaliação definitiva roda novamente com o AVM. O
rent AVM é ainda mais restrito: só roda para o resultado definitivo que não
ficou `reprovado`. Itens históricos, duplicados ou reprovados no filtro inicial
não fazem chamada de AVM/comparáveis.

## Estimativa de chamadas

Definições por execução:

- `S`: páginas de busca de listagens, entre 1 e 3 com a configuração atual;
- `A`: candidatos novos e aprovados no filtro inicial que recebem AVM de valor;
- `R`: candidatos que não ficam `reprovado` na avaliação definitiva e recebem
  rent AVM (`0 <= R <= A`).

A estimativa de respostas HTTP 200 contabilizáveis é:

```text
chamadas por execução = S + A + R
```

Com quatro execuções agendadas por dia, sete dias produzem 28 execuções. A
validação controlada única acrescenta uma execução, então o piloto completo
estima:

```text
29 a 87 chamadas de busca + soma(A + R) das 29 execuções
```

O plano Developer oferece 50 chamadas mensais incluídas e cobra US$ 0,20 por
resposta adicional. Assim, se cada execução usar uma única página, restam no
máximo 21 chamadas incluídas para AVM/rent durante o piloto, antes de considerar
qualquer uso 200 já acumulado no ciclo. Com duas páginas por execução, só a
busca chegaria a 58 chamadas; com três, a 87. O custo estimado do overage é:

```text
US$ 0,20 x max(0, chamadas 200 do ciclo + chamadas do piloto - 50)
```

Erros não-200 entram no monitoramento de confiabilidade, mas, conforme a
documentação pública da RentCast, não contam como chamadas faturáveis.

Fontes públicas consultadas em 10/08/2026:

- <https://www.rentcast.io/api>
- <https://developers.rentcast.io/reference/billing-and-pricing>

## Validação única e monitoramento por sete dias

Na validação controlada, registrar sem expor credenciais:

- URL da execução e SHA publicado;
- cron encontrado no workflow publicado;
- requests totais e respostas 200/4xx/5xx;
- quantidade de itens retornados, já vistos, indisponíveis, reprovados, Radar e
  oportunidades;
- custo/overage exibido no dashboard RentCast, sem identificadores pessoais; e
- `source_captured_at`, frescor dos dados avaliados e horário público do GitHub
  Pages.

Durante sete dias, consolidar diariamente os mesmos campos. Não repetir a
validação manual: as quatro execuções agendadas são a amostra do piloto.

## Hold point e rollback

Qualquer um destes sinais interrompe o piloto para decisão humana: overage não
esperado, erro persistente, regressão de frescor, duplicação de alertas ou
publicação divergente do SHA aprovado.

Rollback simples, sem tocar em secrets ou histórico:

1. desabilitar o workflow `Orlando Land Scan` no GitHub Actions para parar novas
   chamadas; e
2. reverter o commit do Gate 6 em novo PR (`git revert <sha-do-gate-6>`).

Se a decisão for apenas restaurar a agenda anterior, o cron era `0 * * * *`.
Esse rollback aumenta consumo e, por isso, exige decisão explícita da Board.
