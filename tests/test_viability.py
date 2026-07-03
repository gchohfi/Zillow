"""Testes da fórmula de viabilidade e do geofiltro."""

from src.config import Config
from src.datasource import MockDataSource
from src.geo import haversine_km, within_radius
from src.models import Listing
from src.viability import evaluate


def _cfg() -> Config:
    return Config(raw={
        "search": {"center_lat": 28.5384, "center_lng": -81.3789, "radius_km": 180},
        "build": {
            "living_area_sqft": 2000,
            "construction_cost_per_sqft": 165,
            "resale_price_per_sqft": 330,
        },
        "costs": {"soft_cost_pct": 0.10, "carrying_cost_pct": 0.06, "selling_cost_pct": 0.07},
        "rules": {
            "target_margin": 0.18,
            "max_land_price": 0,
            "max_land_to_total_investment_pct": 0.27,
            "require_residential_zoning": True,
            "require_known_zoning": False,
        },
        "market_strategy": {
            "default_priority": "fora",
            "default_score": 0,
            "zip_groups": [
                {
                    "label": "Lake Nona / Narcoossee",
                    "priority": "Alta",
                    "score": 10,
                    "zips": ["32827"],
                    "strategies": ["SFR/BTR"],
                    "risk_flags": ["checar utilities"],
                }
            ],
        },
        "storage": {"db_path": ":memory:"},
    })


def test_haversine_orlando_to_tampa():
    # Orlando → Tampa ~ 130 km
    dist = haversine_km(28.5384, -81.3789, 27.9506, -82.4572)
    assert 120 < dist < 145


def test_within_radius():
    inside, dist = within_radius(28.5384, -81.3789, 28.41, -81.50, 180)
    assert inside and dist < 30


def test_cheap_lot_is_viable():
    lot = Listing(
        id="a",
        price=95_000,
        lat=28.41,
        lng=-81.50,
        address="123 Main St, Orlando, FL 32827",
        zoning="residential",
    )
    r = evaluate(lot, _cfg())
    assert r.is_viable
    assert r.margin >= 0.18
    assert r.land_to_total_investment <= 0.27
    assert r.land_to_total_investment == r.land_cost / r.total_cost
    assert r.arv_source == "config"
    assert r.zip_code == "32827"
    assert r.market_priority == "Alta"
    assert r.market_region == "Lake Nona / Narcoossee"
    assert r.market_score == 10
    assert r.market_strategies == ["SFR/BTR"]
    assert r.risk_flags == ["checar utilities"]


def test_listing_arv_estimate_overrides_config_arv():
    lot = Listing(
        id="arv",
        price=95_000,
        lat=28.41,
        lng=-81.50,
        zoning="residential",
        arv_estimate=500_000,
        arv_source="rentcast_avm",
        arv_comps_count=5,
        arv_confidence="high",
    )
    r = evaluate(lot, _cfg())
    assert r.arv == 500_000
    assert r.arv_source == "rentcast_avm"
    assert r.arv_comps_count == 5
    assert any("ARV por comps RentCast" in reason for reason in r.reasons)


def test_zero_price_is_rejected():
    lot = Listing(id="zero", price=0, lat=28.41, lng=-81.50, zoning="residential")
    try:
        evaluate(lot, _cfg())
    except ValueError as exc:
        assert "preco invalido" in str(exc)
    else:
        raise AssertionError("zero-price listing should not be evaluated as viable")


def test_expensive_lot_fails_margin_or_ratio():
    lot = Listing(id="b", price=240_000, lat=28.6, lng=-81.2, zoning="residential")
    r = evaluate(lot, _cfg())
    assert not r.is_viable


def test_max_land_price_rejects_otherwise_viable_lot():
    cfg = _cfg()
    cfg.raw["rules"]["max_land_price"] = 50_000
    lot = Listing(id="price-cap", price=95_000, lat=28.41, lng=-81.50, zoning="residential")
    r = evaluate(lot, cfg)
    assert not r.is_viable
    assert any("teto US$ 50,000" in reason for reason in r.reasons)


def test_manual_review_only_segment_never_auto_approves():
    cfg = _cfg()
    cfg.raw["tiers"] = [
        {"name": "alto_padrao", "label": "Alto padrão", "max_price": None,
         "rules": {"manual_review_only": True}},
    ]
    lot = Listing(id="high", price=95_000, lat=28.41, lng=-81.50, zoning="residential")
    r = evaluate(lot, cfg)
    assert not r.is_viable
    assert any("análise manual" in reason for reason in r.reasons)


def test_commercial_zoning_rejected():
    lot = Listing(id="c", price=95_000, lat=28.41, lng=-81.50, zoning="commercial")
    r = evaluate(lot, _cfg())
    assert not r.is_viable


def test_unknown_zoning_rejected_when_required():
    cfg = _cfg()
    cfg.raw["rules"]["require_known_zoning"] = True
    lot = Listing(id="unknown-zoning", price=95_000, lat=28.41, lng=-81.50, zoning=None)

    r = evaluate(lot, cfg)

    assert not r.is_viable
    assert any("zoneamento desconhecido" in reason for reason in r.reasons)


def test_configurable_residential_zoning_hint_passes():
    cfg = _cfg()
    cfg.raw["rules"]["require_known_zoning"] = True
    cfg.raw["rules"]["residential_zoning_hints"] = ["mx-r"]
    lot = Listing(id="mixed-residential", price=95_000, lat=28.41, lng=-81.50, zoning="MX-R")

    r = evaluate(lot, cfg)

    assert r.is_viable
    assert any("zoneamento residencial" in reason for reason in r.reasons)


def test_tier_classification_and_override():
    cfg = _cfg()
    cfg.raw["tiers"] = [
        {"name": "baixo_padrao", "label": "Baixo padrão", "max_price": 50000},
        {"name": "medio_padrao", "label": "Médio padrão", "max_price": 300000,
         "rules": {"target_margin": 0.50}},  # margem absurda -> reprova o de médio
        {"name": "alto_padrao", "label": "Alto padrão", "max_price": None},
    ]
    baixo = Listing(id="t1", price=45_000, lat=28.41, lng=-81.50, zoning="residential")
    rb = evaluate(baixo, cfg)
    assert rb.tier == "Baixo padrão"

    medio = Listing(id="t2", price=120_000, lat=28.41, lng=-81.50, zoning="residential")
    rm = evaluate(medio, cfg)
    assert rm.tier == "Médio padrão"
    assert not rm.is_viable          # override de margem 50% derruba

    alto = Listing(id="t3", price=600_000, lat=28.41, lng=-81.50, zoning="residential")
    assert evaluate(alto, cfg).tier == "Alto padrão"


def test_small_lot_rejected():
    cfg = _cfg()
    cfg.raw["rules"]["min_lot_size_sqft"] = 5000
    small = Listing(id="d", price=95_000, lat=28.41, lng=-81.50,
                    zoning="residential", lot_size_sqft=3000)
    assert not evaluate(small, cfg).is_viable
    big = Listing(id="e", price=95_000, lat=28.41, lng=-81.50,
                  zoning="residential", lot_size_sqft=8000)
    assert evaluate(big, cfg).is_viable


def test_real_config_evaluates_mock_listings():
    cfg = Config.load()
    listings = MockDataSource().fetch_new_land_listings(cfg)
    results = [evaluate(listing, cfg) for listing in listings if listing.price > 0]
    assert results
    assert cfg.search["radius_km"] == 80
    assert cfg.rules["max_land_price"] == 0
    assert cfg.raw["tiers"][0]["rules"]["max_land_price"] == 50000
    assert cfg.raw["tiers"][2]["rules"]["manual_review_only"] is True
    assert "max_land_to_total_investment_pct" in cfg.rules
    assert all(hasattr(result, "land_to_total_investment") for result in results)


def test_site_prep_and_impact_fees_enter_total_cost():
    from src.config import Config
    from src.models import Listing
    from src.viability import evaluate

    base = {
        "build": {
            "living_area_sqft": 1000,
            "construction_cost_per_sqft": 100,
            "resale_price_per_sqft": 300,
        },
        "costs": {
            "soft_cost_pct": 0.0,
            "selling_cost_pct": 0.0,
            "site_prep_cost": 15000,
            "impact_fees": 20000,
        },
        "rules": {
            "target_margin": 0.10,
            "max_land_to_total_investment_pct": 0.50,
            "require_residential_zoning": False,
        },
        "tiers": [],
    }
    listing = Listing(id="x", price=50_000, lat=28.5, lng=-81.3)
    result = evaluate(listing, Config(raw=base))

    # 50k terreno + 100k obra + 15k preparação + 20k impact fees
    assert result.total_cost == 185_000
    assert result.site_prep_cost == 15_000
    assert result.impact_fees == 20_000
    assert any("custos de lote" in reason for reason in result.reasons)

    # Sem os custos de lote, o total cai exatamente 35k.
    base["costs"]["site_prep_cost"] = 0
    base["costs"]["impact_fees"] = 0
    lighter = evaluate(listing, Config(raw=base))
    assert lighter.total_cost == 150_000
    assert not any("custos de lote" in reason for reason in lighter.reasons)


def test_tier_can_override_site_costs():
    from src.config import Config
    from src.models import Listing
    from src.viability import evaluate

    cfg = Config(raw={
        "build": {
            "living_area_sqft": 1000,
            "construction_cost_per_sqft": 100,
            "resale_price_per_sqft": 300,
        },
        "costs": {
            "soft_cost_pct": 0.0,
            "selling_cost_pct": 0.0,
            "site_prep_cost": 15000,
            "impact_fees": 20000,
        },
        "rules": {
            "target_margin": 0.10,
            "max_land_to_total_investment_pct": 0.50,
            "require_residential_zoning": False,
        },
        "tiers": [{
            "name": "baixo",
            "max_price": 60000,
            "costs": {"site_prep_cost": 25000, "impact_fees": 15000},
        }],
    })
    result = evaluate(Listing(id="x", price=50_000, lat=28.5, lng=-81.3), cfg)
    assert result.site_prep_cost == 25_000
    assert result.impact_fees == 15_000
