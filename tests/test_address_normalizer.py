"""Tests for US address normalization helpers."""

from src.address_normalizer import address_fingerprint, has_address_locator, normalize_address
from src.models import Listing


def test_normalize_address_canonicalizes_common_suffixes():
    a = normalize_address("123 Main Street, Orlando, Florida 32801")
    b = normalize_address("123 MAIN ST Orlando FL 32801")

    assert a == b
    assert "123" in a
    assert "MAIN" in a
    assert "ST" in a


def test_address_fingerprint_requires_specific_locator():
    vague = Listing(id="road-only", price=10, lat=0, lng=0, address="Blackwelder Rd, FL")
    specific = Listing(id="specific", price=10, lat=0, lng=0, address="1876 Blackwelder Rd, FL")

    assert not has_address_locator(vague.address)
    assert address_fingerprint(vague) == ""
    assert address_fingerprint(specific)
