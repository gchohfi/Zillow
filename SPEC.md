# Orlando Land Detector - Product and App Specification

Status: canonical specification for the current product

Last reviewed: 2026-08-01

References:

- Production dashboard: <https://gchohfi.github.io/Zillow/>
- Product mockup: <https://app.paper.design/file/01KYZPPF8YTFYFFF8R7BT0R9QY/1-0>
- Runtime configuration: `config.yaml`
- Dashboard generator: `src/site.py`
- Decision memo generator: `src/memo.py`
- Scanner workflow: `.github/workflows/scan.yml`

## 1. Purpose of this document

This specification describes the Orlando Land Detector in a format that is explicit enough for both humans and AI coding agents. It is the source of truth for:

- what the product does and does not do;
- the current pages and published assets;
- the components visible in each page;
- the behavior of every interactive element;
- the main user journeys;
- the data and status contracts used by the UI;
- required empty, error, loading and stale-data states;
- acceptance criteria for changes.

When this specification conflicts with an informal prompt, the prompt must explicitly state whether it is changing this specification. Financial rules remain owned by `config.yaml` and the calculation modules, not by the UI.

## 2. Product definition

### 2.1 Name

Orlando Land Detector.

### 2.2 Product objective

Find, enrich, evaluate and prioritize land listings for spec-build opportunities within the configured radius around Orlando, Florida. The product should reduce the time between a new listing appearing and a human deciding whether to investigate, negotiate or discard it.

### 2.3 Primary user

An investor or acquisition analyst who needs to triage many land listings quickly and then perform deeper diligence on the strongest candidates.

### 2.4 Secondary users

- A partner or manager reviewing the current pipeline.
- An analyst comparing opportunities using a consistent financial basis.
- An external front end or spreadsheet consuming `data.json`.
- An operator monitoring the automated scan and deployment workflow.

### 2.5 Core product promise

The dashboard must answer these questions in under one minute:

1. What is new?
2. Which listings are viable or worth diligence?
3. Why is each listing in that status?
4. What are the key financial and development metrics?
5. What must be confirmed before a decision?
6. Where can the user continue the investigation?

### 2.6 Non-goals

The product does not:

- provide a final legal, zoning, environmental or title opinion;
- guarantee ARV, construction cost, rent, profit or liquidity;
- replace a broker, attorney, surveyor, engineer or local authority;
- submit an offer or contact a seller automatically;
- expose a public control that runs the production scanner;
- treat cadastral use as legally confirmed zoning;
- approve a site for development solely from a preliminary net-area estimate.

## 3. Product surfaces and routes

The current product is a generated static site. A page in this specification means either a route or a generated HTML surface with a distinct user purpose.

### 3.1 Dashboard

- Route: `/Zillow/`
- Generated file: `site/index.html`
- Source: `src/site.py`
- Purpose: daily triage, filtering, comparison, mapping and export.

The dashboard is a single responsive page with anchored sections rather than separate client-side routes.

Sections:

- `#visao-geral`
- `#oportunidades`
- `#mapa`
- `#regioes`
- `#sec-compare`
- `#avaliacoes`
- `#premissas`

### 3.2 Opportunity decision memo

- Route pattern: `/Zillow/memo/<slug>.html`
- Generated files: `site/memo/*.html`
- Source: `src/memo.py`
- Purpose: deeper analysis and a decision-oriented summary for one open opportunity.

The memo must preserve the distinction between verified evidence, modeled assumptions and pending confirmations.

### 3.3 Machine-readable data

- Route: `/Zillow/data.json`
- Generated file: `site/data.json`
- Source: the same normalized payload embedded in the dashboard.
- Purpose: integration with other front ends, spreadsheets and scripts.

This is a public read-only data contract. No secret, API key or private credential may be included.

### 3.4 CSV downloads

- `/Zillow/opportunities.csv`
- `/Zillow/evaluations.csv`

Downloads represent the generated source files. They are not filtered dynamically by the controls currently active in the browser.

### 3.5 Future routes

These routes are candidates, not current requirements:

- `/Zillow/scans/` for scan history and failure details;
- `/Zillow/regions/<zip>/` for regional drill-down;
- `/Zillow/premises/` for a read-only view of financial assumptions;
- authenticated collaboration pages for notes, assignments and centralized decisions.

An implementation must not invent these routes unless the relevant roadmap item is approved.

## 4. Shared layout

### 4.1 AppShell

Responsibilities:

- contain the sidebar and the main content area;
- provide the page background and responsive structure;
- prevent horizontal page overflow;
- collapse to a mobile header and horizontally scrollable navigation at small widths.

### 4.2 Sidebar

Visible items:

- Visão geral;
- Oportunidades;
- Mapa;
- Regiões;
- Avaliações;
- CSV Oportunidades;
- CSV Avaliações.

Behavior:

- section links scroll to anchors within the dashboard;
- CSV links download the generated files;
- the active visual state indicates the dashboard overview, not live scroll position;
- at widths below 1180 px, labels may collapse;
- at widths below 720 px, navigation becomes horizontal.

### 4.3 Topbar

Components:

- breadcrumb;
- global search input;
- CSV export action.

Behavior:

- the search input filters the dashboard after a short debounce;
- the export action downloads `evaluations.csv`;
- the topbar is sticky on desktop and static on mobile.

### 4.4 Visual language

- Blue is the product and action accent.
- Green represents a viable opportunity.
- Amber represents radar or pending diligence.
- Gray represents rejected, unavailable or secondary information.
- Status must never depend on color alone; use text and a dot or badge.
- Currency is displayed in USD using Brazilian number formatting.
- Percentages use one decimal place unless the underlying metric requires otherwise.

## 5. Dashboard components and behavior

### 5.1 PageHeader

Content:

- eyebrow: "Radar de oportunidades";
- title: "Orlando Land Detector";
- short product description;
- scan completion label;
- payload generation timestamp.

The timestamp represents when the dashboard payload was generated, not when each listing was originally found.

### 5.2 NewOpportunityBanner

Purpose: tell a returning user how many open opportunities appeared after the previous browser visit.

Behavior:

- store the last visit timestamp in `localStorage`;
- count only viable and radar opportunities newer than that timestamp;
- remain hidden on a first visit or when no new open opportunities exist;
- fail silently if browser storage is unavailable.

### 5.3 KPIBar

KPIs:

- open opportunities found in the last 24 hours;
- viable opportunities;
- radar opportunities;
- highest margin among viable opportunities, or radar when no viable opportunity exists;
- total evaluations within the configured dashboard period.

Rules:

- rejected evaluations are included only in total evaluations;
- the highest margin must display `n/d` or an em dash when no usable value exists;
- the dashboard period comes from `config.yaml -> site.period_days`;
- KPIs become horizontally scrollable on narrow screens.

### 5.4 FilterBar

Controls:

- status: Oportunidades, Viáveis, Radar, Todas;
- ordering: recommended, recent, margin, profit;
- minimum margin: all, 15%, 20%, 25%, 30%;
- global search in the topbar.

Behavior:

- Oportunidades includes viable and radar, but excludes rejected;
- Viáveis includes only `viavel`;
- Radar includes all statuses whose value starts with `radar_`;
- Todas includes every evaluation in the payload;
- minimum margin excludes a row when its margin is missing or below the selected threshold;
- search is case-insensitive and matches address, ZIP, market region, priority, tier and zoning;
- changing any control updates cards, table data and map markers;
- changing controls must not reset the user's map zoom after the initial map fit.

### 5.5 Recommended ranking

The default ranking is a triage aid, not an investment recommendation.

The current ranking combines:

- status priority;
- margin relative to a 25% reference;
- regional growth score;
- market score;
- cadastral residential evidence for zoning-pending radar;
- recency bonus for opportunities under 24 hours old.

Any change to ranking weights must be explicit, tested and documented. UI styling must not silently change ranking logic.

### 5.6 OpportunityFeed

Rules:

- show viable cards before radar cards;
- show starred cards before non-starred cards within the selected order;
- show at most eight cards initially;
- provide a control to reveal all matching opportunities;
- keep rejected evaluations out of the feed;
- show an explanatory empty state when no card matches.

### 5.7 OpportunityCard

Required content:

- status badge;
- new badge when found less than 24 hours before payload generation;
- relative time;
- address or listing ID fallback;
- market region, ZIP, tier and distance when available;
- cadastral use when available, always labeled as indicative;
- financial or development metrics;
- regional score;
- pending issue or ready-for-offer message;
- expandable diligence checklist;
- external investigation links;
- star and dismiss controls.

Standard spec-build metrics:

- land price;
- ARV;
- estimated profit;
- margin and pessimistic margin;
- regional growth score.

Development-radar metrics:

- land price;
- gross acreage;
- preliminary net developable acreage and confidence;
- price per net acre;
- diligence completion percentage and recommendation;
- regional growth score.

Behavior:

- star toggles tracking in `localStorage`;
- dismiss removes the opportunity from cards and map but not from the audit table;
- a dismissed opportunity can be restored;
- star and dismiss buttons require accessible labels and pressed state where applicable;
- the Memo link appears only when a generated memo exists;
- external links open in a new tab with `noopener`;
- missing numbers display `n/d`, never zero unless the underlying value is actually zero.

### 5.8 DiligenceChecklist

Behavior:

- starts collapsed;
- lists the recorded reasons and checks for the opportunity;
- distinguishes passed, warning, informational and failed items;
- does not appear when no diligence trail exists;
- does not imply that a passed automated check is a legal confirmation.

### 5.9 MapPanel

Behavior:

- use coordinates from the visible filtered rows;
- green marker: viable;
- amber marker: radar;
- gray marker: rejected;
- marker popup contains the address, status, core financial metrics, growth score, risk summary and links;
- fit bounds only on the first successful render;
- filtering updates markers without taking control of the user's zoom;
- dismissed opportunities remain hidden unless the user chooses to show dismissed opportunities;
- when Leaflet fails to load, show a useful fallback and keep cards and tables functional;
- when no visible row has coordinates, show an empty-map message.

### 5.10 RegionPanel

Content per ZIP:

- ZIP;
- market region and priority when mapped;
- growth score from 0 to 10;
- signal categories and full signal text in an accessible tooltip;
- counts of viable, radar and total evaluations.

Behavior:

- sort primarily by available growth score and then by viable count;
- include thesis ZIPs with cached signals even before a current opportunity appears;
- show at most eight regions initially;
- hide the section when no regional score exists;
- a future regional drill-down may filter cards and map, but this is not current behavior.

### 5.11 ComparisonTable

Purpose: compare open single-home opportunities on the same assumptions.

Rules:

- include viable and radar opportunities;
- exclude development-radar opportunities because their decision basis is price per acre and development yield, not single-home margin;
- exclude dismissed opportunities;
- sort by margin descending;
- limit the initial comparison to 12 rows;
- hide the section when fewer than two comparable opportunities exist.

Columns:

- address and memo link;
- status;
- land price;
- total investment;
- profit;
- margin;
- pessimistic margin;
- cap rate;
- DSCR;
- market score;
- growth score;
- leading sensitivity or risk.

### 5.12 EvaluationTable

Purpose: maintain an auditable view of all evaluations within the selected period and current browser filters.

Behavior:

- start collapsed;
- render rows only after the details element is opened;
- include rejected evaluations;
- preserve the full current data columns, including cadastral use, development metrics, ARV, profit, margin, risk and links;
- use horizontal scrolling on narrow screens;
- never remove a rejected evaluation merely because it is absent from the opportunity feed.

### 5.13 Footer and disclaimers

The footer must:

- provide both CSV downloads;
- state that values are estimates used for triage;
- remind the user to confirm title, zoning, infrastructure and comparable sales before investing.

## 6. Opportunity status contract

### 6.1 `viavel`

Meaning: the listing passed the configured financial and automated review criteria.

UI language: "Viável" or "Pronta para oferta - confirme diligência básica".

This status is not a final acquisition approval.

### 6.2 `radar_zoneamento_pendente`

Meaning: the numbers are sufficiently strong for continued investigation, but legal zoning remains unknown or unconfirmed.

Cadastral residential use may improve ranking but must not promote the listing to viable.

### 6.3 `radar_analise_manual`

Meaning: the listing belongs to a segment or condition requiring human review despite potentially useful numbers.

### 6.4 `radar_desenvolvimento`

Meaning: a large site may be relevant as a development opportunity even when the single-home spec-build formula is not the correct evaluation model.

The UI must prioritize acres, net developable estimate, price per net acre and diligence state.

### 6.5 `radar_valorizacao`

The current UI recognizes this label for backward compatibility or future use. The current classifier does not normally emit it. New logic must not start producing this status without a separate rule and test.

### 6.6 `reprovado`

Meaning: the listing does not satisfy the configured criteria or a blocking condition applies.

Rejected rows remain available for audit but stay outside the default opportunity feed.

### 6.7 Status invariants

- Any value starting with `radar_` belongs to the radar UI category.
- Unknown or missing status falls back to legacy `is_viable` when available.
- Cadastral use and zoning are different fields and must never be merged semantically.
- Status changes must originate in the review engine, not from browser interactions.

## 7. Data contract

### 7.1 Payload envelope

`data.json` and the embedded dashboard payload contain:

```json
{
  "generated_at": "ISO-8601 timestamp",
  "period_days": 30,
  "source": "evaluations or opportunities",
  "total_rows": 0,
  "rows": [],
  "regions": []
}
```

Rules:

- rows are ordered from most recent to oldest before browser sorting;
- no more than 1000 rows are embedded or published in the dashboard payload;
- missing numeric values are JSON `null`;
- missing textual values are empty strings;
- rejected rows omit the full diligence-reasons trail to control payload size;
- the payload period defaults to 30 days and is configurable.

### 7.2 Row field groups

Identity and discovery:

- `id`, `found_at`, `address`, `url`, `lat`, `lng`, `distance_km`.

Review:

- `review_status`, `review_reason`, `reasons`, `is_viable`, `risk_flags`.

Market and region:

- `zip_code`, `county`, `market_priority`, `market_region`, `market_score`, `market_strategies`, `growth_score`, `growth_signals`, `tier`.

Land and development:

- `land_price`, `lot_size_sqft`, `lot_size_acres`, `price_per_acre`, `development_profile`, `gross_acres`, `estimated_net_developable_acres`, `net_developable_pct`, `net_estimate_confidence`, `price_per_net_acre`.

Legal and diligence:

- `zoning`, `cadastral_use`, `cadastral_use_code`, `cadastral_use_source`, `cadastral_use_status`, `parcel_id`, `owner_name`, `jurisdiction`, `future_land_use`, `due_diligence_status`, `due_diligence_completion_pct`, `due_diligence_recommendation`, `evidence_status`, `pending_confirmations`, `entitlement_stage`, `rules_as_of`, `sources_consulted`, `net_area_scenarios`.

Utilities and access:

- `electric_utility`, `water_utility`, `sewer_utility`, `access_authority`, `environmental_authority`.

Financial:

- `arv`, `arv_source`, `total_cost`, `profit`, `margin`, `margin_stress`, `land_to_total_investment`, `rent_monthly`, `noi_annual`, `cap_rate`, `dscr`, `cash_on_cash`, `sensitivity_top`.

Risk:

- `flood_zone` and `risk_flags`.

Generated navigation:

- `memo` is added when a decision memo is generated successfully.

### 7.3 Region object

```json
{
  "zip": "32827",
  "region": "Lake Nona",
  "priority": "Alta",
  "growth_score": 8.1,
  "growth_signals": "signal summary",
  "viable": 0,
  "radar": 0,
  "total": 0
}
```

## 8. User journeys

### 8.1 Daily opportunity triage

1. User opens the dashboard.
2. User checks data freshness, new-opportunity count and status KPIs.
3. User selects an opportunity status or margin threshold.
4. User scans the ranked cards.
5. User expands diligence for a promising listing.
6. User stars the listing, opens the memo or continues investigation externally.
7. User dismisses noise without deleting the audit record.

Success condition: the user can identify the next listings to investigate without opening the full table.

### 8.2 Investigate one opportunity

1. User starts from an opportunity card.
2. User reviews financial or development metrics.
3. User reads the pending confirmation and diligence trail.
4. User checks the marker and regional score.
5. User opens the decision memo.
6. User follows Zillow, Maps, Realtor or Regrid links when needed.
7. User decides to keep tracking, negotiate, investigate further or dismiss.

Success condition: modeled assumptions and unverified evidence remain visibly distinct.

### 8.3 Compare open opportunities

1. User reviews the comparison table.
2. User compares margin, pessimistic margin, income lens, market and growth.
3. User opens the memo for the strongest candidate.

Success condition: development sites are not compared using an inappropriate single-home model.

### 8.4 Audit rejected evaluations

1. User changes the status filter to Todas or opens the complete evaluation table.
2. User finds a rejected listing by address, ZIP or region.
3. User inspects its reason, risk flags and available source links.

Success condition: rejection does not remove the listing from the audit trail.

### 8.5 Export data

1. User chooses an opportunities or evaluations download.
2. Browser downloads the generated CSV.

Success condition: the UI does not claim the exported file reflects browser filters.

### 8.6 Automated scan and publish

1. GitHub Actions starts by schedule or manual dispatch.
2. The workflow restores scanner state.
3. The scanner fetches, enriches and evaluates listings.
4. It generates CSVs, dashboard payload, memos and static HTML.
5. It publishes `site/` to GitHub Pages.
6. It persists scanner state and uploads run artifacts.

Success condition: the dashboard remains publishable even when a noncritical enrichment check fails. A workflow failure must be visible to the operator and must never be represented as "no opportunities".

## 9. UI states

### 9.1 Loading

The current static page has no application-level loading state because data is embedded. External map tiles may load progressively. A future API-driven UI must define skeletons and must not display zero KPIs before data resolution.

### 9.2 Empty

Required empty states:

- no evaluations in the configured period;
- no opportunity matches current filters;
- no coordinates exist for the visible rows;
- no region has a growth score;
- fewer than two comparable opportunities exist.

Each state must explain the condition and, when applicable, suggest clearing search or lowering the margin threshold.

### 9.3 Error

Required graceful failures:

- Leaflet unavailable: show a map fallback while keeping cards and tables usable;
- local browser storage unavailable: continue without personalization;
- missing numeric field: display `n/d`;
- invalid timestamp: display the raw value or `n/d` without breaking rendering;
- missing CSV asset: the generation workflow must report it; the UI must not fabricate a download.

### 9.4 Stale data

The page must always display `generated_at`. A future stale-data warning should compare this timestamp with the configured scan frequency and show a warning when the most recent successful publish exceeds an approved threshold.

## 10. Responsive behavior

### Desktop above 1180 px

- full sidebar;
- sticky topbar;
- opportunity feed and insight column side by side;
- five KPI cells in one row.

### Compact desktop and tablet from 921 to 1180 px

- compact sidebar;
- two-column dashboard remains available while space permits;
- KPI padding may reduce.

### Tablet at 920 px and below

- dashboard becomes one column;
- map and region panels may share a two-column insights row;
- KPIs wrap into multiple rows.

### Mobile at 720 px and below

- sidebar becomes a top navigation region;
- navigation and filter controls scroll horizontally;
- search and export occupy the mobile topbar;
- KPI cells scroll horizontally;
- opportunity metrics use two columns;
- insight panels stack;
- page width must equal viewport width with no document-level horizontal overflow.

## 11. Accessibility requirements

- Use semantic landmarks: navigation, banner, main, complementary and footer.
- Maintain one page-level `h1` and ordered section headings.
- Every input requires an accessible label.
- Icon-only actions require `aria-label`.
- Toggle controls expose `aria-pressed` when relevant.
- Keyboard focus must remain visible.
- Color cannot be the only status indicator.
- Map interaction cannot be the only way to access an opportunity.
- Tables require textual column headings.
- Links that open new tabs use safe rel attributes.
- Empty and error states must be readable without visual context.

## 12. Security, privacy and publication

- The repository and GitHub Pages dashboard are public.
- The UI and `data.json` must contain no credentials or secret headers.
- Any owner, parcel or contact field must be reviewed before public display.
- Browser favorites and dismissals are currently local to one browser profile.
- A future multi-user decision system requires authentication, authorization and an explicit data-retention policy.
- Running the scanner from the public dashboard is out of scope until an authenticated backend exists.

## 13. Implementation boundaries

### 13.1 Current architecture

- Python performs scanning, enrichment, evaluation and static-site generation.
- The dashboard uses generated HTML, CSS and vanilla JavaScript.
- Leaflet supplies the interactive map.
- GitHub Actions generates and publishes the site.
- GitHub Pages hosts read-only assets.

### 13.2 Componentization rule

Component names in this specification describe responsibility, not a required JavaScript framework. The current implementation may use Python template functions or HTML partials. Do not introduce React, a build system or a server solely to mirror component names.

### 13.3 Rule ownership

- Financial formulas: `config.yaml`, `src/viability.py`, `src/rental.py`.
- Status classification: `src/review.py`.
- Diligence evidence: `src/due_diligence.py`, `src/zoning.py` and related enrichers.
- Dashboard ranking and presentation: `src/site.py`.
- Decision memo: `src/memo.py`.
- Scan and deployment behavior: `.github/workflows/scan.yml`.

The UI may explain a rule but must not duplicate it as an independent business decision.

## 14. Acceptance criteria

### 14.1 Dashboard generation

- Given no source CSV, generating the site still creates a valid dashboard.
- Given evaluations, the same normalized payload is embedded in HTML and written to `data.json`.
- Given configured CSV paths, existing CSVs are copied into the site output.
- Given an open opportunity, a memo path is added only when memo generation succeeds.
- Given more than 1000 recent evaluations, only 1000 are embedded and the generator reports the omitted count.

### 14.2 Filtering and ranking

- Given status Oportunidades, rejected rows do not appear as cards.
- Given status Todas, rejected rows remain available in audit results and on the map when coordinates exist.
- Given a search term, matching is case-insensitive across the documented fields.
- Given a minimum margin, missing margins do not pass the filter.
- Given a starred item, it appears before non-starred items without changing the selected base order.

### 14.3 Personalization

- Given a user stars an opportunity, reloading the same browser preserves the state.
- Given a user dismisses an opportunity, it leaves the card feed and map but remains in the complete table.
- Given storage access fails, the dashboard remains usable.

### 14.4 Map

- Given visible coordinates, markers reflect the current filters.
- Given an initial marker set, the map fits those bounds once.
- Given the user changes zoom and then filters, the application preserves user map position.
- Given Leaflet is unavailable, the page shows a fallback instead of throwing an uncaught error.

### 14.5 Responsive and accessible UI

- At 1440 x 900, the dashboard displays the full sidebar and two-column content.
- At 390 x 844, there is no document-level horizontal overflow.
- Search, filters, star, dismiss, details and downloads are keyboard accessible.
- The browser console has no application errors during the primary triage flow.

### 14.6 Regression checks

- Run `python3 -m py_compile src/site.py` after template changes.
- Run the complete `pytest` suite.
- Validate desktop and mobile rendering with a real generated payload.
- Test search, status filtering, star, dismiss, details expansion and table lazy rendering.
- Confirm the public Pages HTML after deployment rather than relying only on workflow status.

## 15. Approved roadmap

Roadmap items are proposals until explicitly selected for implementation.

### P0 - specification and decision clarity

- Keep this document aligned with product behavior.
- Make the entire opportunity card lead clearly to its memo or detail view without interfering with star, dismiss and external links.
- Add visible source and confidence labels for ARV, zoning and net developable area.
- Define and display a stale-data warning threshold.
- Add automated browser tests for the primary journeys.

### P1 - investigation efficiency

- Add click-to-filter behavior from region rows and map markers.
- Add explicit selection for side-by-side comparison.
- Add scan-history and last-success information.
- Add saved filter presets.
- Improve the detail memo navigation back to the filtered dashboard context.

### P2 - collaboration

- Replace browser-only star and dismiss state with authenticated persistence.
- Add notes, owner assignment and decision history.
- Add access control if parcel or owner data becomes sensitive.
- Add an authenticated scanner control with run status and audit history.

## 16. Change protocol for AI coding agents

Before implementing a request:

1. Identify which page, component, behavior or journey changes.
2. Identify the owning business-rule module.
3. State whether the request changes current scope or implements a roadmap item.
4. Preserve all unrelated current behaviors.
5. Update this specification when behavior changes.
6. Add or update tests for the acceptance criteria.
7. Validate with representative real-shaped data.
8. Check desktop and mobile rendering.
9. Do not publish until tests and the public deployment path succeed.

When a prompt is ambiguous, prefer the smallest implementation consistent with this document and ask before changing financial rules, visibility, authentication or publication behavior.
