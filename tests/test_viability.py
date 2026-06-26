"""Testes da fórmula de viabilidade e do geofiltro."""

from src.config import Config
from src.geo import haversine_km, within_radius
from src.models import Listing
from src.viability import evaluate


def _cfg() -> Config:
    return Config(raw={
        "search": {"center_lat": 28.5384, "center_lng": -81.3789, "radius_km": 150},
        "build": {
            "living_area_sqft": 2000,
            "construction_cost_per_sqft": 165,
            "resale_price_per_sqft": 330,
        },
        "costs": {"soft_cost_pct": 0.10, "carrying_cost_pct": 0.06, "selling_cost_pct": 0.07},
        "rules": {
            "target_margin": 0.18,
            "max_land_to_arv_pct": 0.20,
            "require_residential_zoning": True,
        },
        "storage": {"db_path": ":memory:"},
    })


def test_haversine_orlando_to_tampa():
    # Orlando → Tampa ~ 130 km
    dist = haversine_km(28.5384, -81.3789, 27.9506, -82.4572)
    assert 120 < dist < 145


def test_within_radius():
    inside, dist = within_radius(28.5384, -81.3789, 28.41, -81.50, 150)
    assert inside and dist < 30


def test_cheap_lot_is_viable():
    lot = Listing(id="a", price=95_000, lat=28.41, lng=-81.50, zoning="residential")
    r = evaluate(lot, _cfg())
    assert r.is_viable
    assert r.margin >= 0.18
    assert r.land_to_arv <= 0.20


def test_expensive_lot_fails_margin_or_ratio():
    lot = Listing(id="b", price=240_000, lat=28.6, lng=-81.2, zoning="residential")
    r = evaluate(lot, _cfg())
    assert not r.is_viable


def test_commercial_zoning_rejected():
    lot = Listing(id="c", price=95_000, lat=28.41, lng=-81.50, zoning="commercial")
    r = evaluate(lot, _cfg())
    assert not r.is_viable


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
