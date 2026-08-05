from src.config import Config
from src.models import Listing
from src.search_spec import apply_search_spec
from src.viability import evaluate


def _result(*, price=800_000, zip_code="32789", zoning="residential", arv=2_250_000):
    cfg = Config.load()
    listing = Listing(
        id="infill",
        price=price,
        lat=28.60,
        lng=-81.35,
        address=f"100 Test Ave, Winter Park, FL {zip_code}",
        lot_size_sqft=12_000,
        zoning=zoning,
        arv_estimate=arv,
        arv_source="rentcast_avm",
    )
    result = evaluate(listing, cfg)
    return cfg, result


def test_target_market_is_scored_and_auditable():
    cfg, result = _result()
    apply_search_spec(result, cfg)

    assert result.search_spec_status == "aderente"
    assert result.search_spec_score == 100
    assert result.search_spec_region == "Winter Park"
    assert result.search_spec_target_land_min == 750_000
    assert result.search_spec_target_land_max == 850_000
    assert result.search_spec_target_irr_annual == 0.23


def test_price_more_than_15_percent_above_market_is_out():
    cfg, result = _result(price=1_000_000)
    apply_search_spec(result, cfg)

    assert result.search_spec_status == "fora"
    assert any("15% acima" in reason for reason in result.search_spec_reasons)


def test_unmapped_zip_is_out_without_changing_viability():
    cfg, result = _result(zip_code="34711")
    original_viability = result.is_viable
    apply_search_spec(result, cfg)

    assert result.search_spec_status == "fora"
    assert result.search_spec_score == 0
    assert result.is_viable is original_viability
