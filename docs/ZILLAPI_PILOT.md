# Piloto controlado Zillapi

## Limites

- uma execução agendada por dia;
- no máximo 29 resultados/créditos por execução;
- apenas uma bbox por execução, com rotação diária entre seis áreas;
- pausa automática quando o saldo chegaria ao piso de 100 créditos;
- consulta gratuita a `GET /v1/me` antes e depois da busca;
- nenhuma chamada adicional de detalhe ou Zestimate neste piloto.

No pior mês de 31 dias, a busca consome no máximo `29 × 31 = 899` créditos.
O saldo e o consumo estimado são registrados em `scan_status.json` e no resumo
operacional da rodada.

## Zillow Research

O enriquecimento usa somente o ZHVI por ZIP que o Zillow Research publica para
essa geografia. O URL oficial é estável; o arquivo é substituído mensalmente e o
período real é lido da última coluna do CSV. Preço mediano de venda e Market Heat
Index não são apresentados como dados por ZIP porque a página oficial atualmente
os disponibiliza em outras geografias.

O cache SQLite usa chave primária composta `(zip, dataset)` e migra de forma não
destrutiva a versão antiga que usava somente `zip`.

## Hold point

Este código permanece em Draft PR. Antes de qualquer merge ou scan real:

1. revogar a chave que apareceu fora do cofre e criar outra;
2. cadastrar a nova somente em `GitHub Actions Secrets` como `ZILLAPI_KEY`;
3. executar uma única rodada manual controlada;
4. validar humanamente endereço, preço, área, vacância, zoneamento, FEMA, comps,
   custos e margem;
5. confirmar que o consumo real ficou em até 29 créditos.

Não fazer merge, ativação diária definitiva ou reprocessamento histórico sem
aprovação posterior.

## Referências oficiais

- https://zillapi.com/api/search/
- https://zillapi.com/api/account/
- https://zillapi.com/pricing/
- https://www.zillow.com/research/data/
