# Due diligence de terrenos para desenvolvimento

O Radar de desenvolvimento faz uma triagem de aquisição. Ele não substitui
survey, parecer jurídico, delimitação ambiental, estudo de tráfego, carta de
utility ou aprovação pública.

## Regra de evidência

Cada tema recebe um estado:

- `confirmado`: documento oficial, survey, licença, carta de utility ou parecer profissional;
- `indicativo`: GIS oficial, mapa público ou registro administrativo ainda sujeito a validação;
- `nao_confirmado`: anúncio, corretor, proprietário ou estimativa;
- `alerta`: aumenta custo, prazo ou risco e requer diligência;
- `bloqueio`: condição explícita capaz de impedir o uso pretendido.

Ausência de dado nunca é interpretada como resposta positiva. Em especial, o
sistema não informa “sem wetlands” apenas porque a camada consultada não mostra
wetland.

`DOR_UC`, `PA_UC`, `usedesc` e `landuse` descrevem uso cadastral ou fiscal da
parcela. Eles ajudam a priorizar o Radar, mas não comprovam o direito de
construir. Somente um campo de zoning legal da Regrid/GIS competente, datado e
identificado pela fonte, pode preencher o zoneamento automático. Sem essa
evidência, a oportunidade permanece como “confirmar zoning legal”.

## Fluxo no sistema

1. A listagem é normalizada e consultada no Regrid/GIS, quando configurado. O
   sistema preserva separadamente zoning legal e uso cadastral indicativo.
2. Terrenos a partir de 1 acre recebem uma ficha preliminar de due diligence.
3. Terrenos a partir de 2 acres podem entrar no `radar_desenvolvimento`, mesmo
   quando a conta de uma única casa reprova.
4. O sistema registra jurisdição, parcel ID, proprietário, Future Land Use,
   zoning, utilities, acesso, ambiente, entitlement, fontes e pendências quando
   esses dados existirem na fonte. Campos ausentes continuam não confirmados.
5. A área líquida provável considera restrições percentuais disponíveis e
   reservas configuráveis para stormwater e infraestrutura. Também são exibidos
   cenários conservador, provável e agressivo.
6. A decisão preliminar é `avancar`, `avancar_com_condicoes`, `hold` ou
   `descartar`. Nenhuma dessas decisões concede entitlement.

## Fórmula preliminar

```text
área bruta
- wetlands e buffers conhecidos
- floodplain/floodway inutilizável conhecido
- easements conhecidos
- reserva de stormwater
- vias e infraestrutura internas
- reserva por restrições ainda desconhecidas (cenário conservador)
= área líquida preliminar
```

O preço por acre líquido é calculado sobre o cenário provável. As porcentagens
em `config.yaml` são premissas de triagem e devem ser substituídas por medições
do projeto assim que existirem.

## Próximas confirmações

Antes de oferta sem condições, confirme:

- jurisdição, Future Land Use, zoning e capacidade by-right;
- densidade/FAR, altura, setbacks, open space e estacionamento;
- FEMA flood zone/BFE e delimitação formal de wetlands;
- stormwater, buffers, mitigação e Environmental Resource Permit;
- provedor, capacidade, extensão, custo e prazo de energia, água e esgoto;
- acesso legal, driveway permit, medianas, turn lanes e impacto de tráfego;
- easements, right-of-way, plat, approvals e caminho crítico de entitlement.

## Fontes oficiais de partida

- [Orange County Interactive Mapping](https://www.orangecountyfl.net/PlanningDevelopment/InteractiveMapping.aspx)
- [Orange County Zoning Division](https://www.orangecountyfl.net/PermitsLicenses/ZoningDivision.aspx)
- [FEMA Map Service Center](https://msc.fema.gov/)
- [Florida DEP ERP](https://floridadep.gov/water/submerged-lands-environmental-resources-coordination/content/erp-e-permitting)
- [OUC Development Services](https://www.ouc.com/solutions-programs/business/development-services/)
- [FDOT Access Management](https://www.fdot.gov/planning/systems/systems-management/access-management)
- [Orange County FastTrack](https://fasttrack.ocfl.net/OnlineServices/Default.aspx)
- [Florida Statutes, Chapter 163 Part II](https://www.leg.state.fl.us/Statutes/index.cfm?App_mode=Display_Statute&URL=0100-0199/0163/0163PARTIIContentsIndex.html)

Guarde sempre a data da regra/fonte consultada. O campo `rules_as_of` registra
a versão temporal usada pela triagem.
