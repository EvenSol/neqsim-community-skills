"""Tests for host-field rates, ratios, ullage proxy and nearby discoveries."""

from __future__ import annotations

import urllib.parse

import pytest
from norwegian_continental_shelf_data import (
    TABLE_IDS,
    Discovery,
    Facility,
    ProductionRecord,
    SodirDataService,
    haversine_km,
    host_context,
    monthly_rates,
    nearby_discoveries,
    pick_host_location,
    ratio_trend,
    ullage_indicator,
)


def _rec(year, month, oil, gas, water=None, cond=0.0, gas_gross=None):
    return ProductionRecord(
        carrier="HOST", carrier_kind="FIELD", year=year, month=month,
        oil_net=oil, gas_net=gas, ngl_net=0.0, condensate_net=cond,
        oe_net=oil + gas + cond, gas_gross=gas_gross, water_mill_sm3=water,
    )


def _series(months=24):
    """Synthetic host: oil declines, GOR and water cut rise."""
    recs = []
    for i in range(months):
        year, month = 2024 + i // 12, i % 12 + 1
        oil = 0.30 - 0.005 * i            # mill Sm3 / month
        gas = oil * (150 + 5 * i) / 1000  # bill Sm3 / month, GOR rising
        water = 0.10 + 0.01 * i
        recs.append(_rec(year, month, oil, gas, water))
    return recs


def test_monthly_rates_units_and_ratios() -> None:
    (r,) = monthly_rates([_rec(2025, 1, oil=0.31, gas=0.062, water=0.31)])
    assert r.days == 31
    assert r.oil_sm3_d == pytest.approx(10_000.0)
    assert r.gas_sm3_d == pytest.approx(2_000_000.0)
    assert r.gor_sm3_sm3 == pytest.approx(200.0)
    assert r.water_cut == pytest.approx(0.5)
    assert r.label == "2025-01"


def test_monthly_rates_skip_yearly_and_handle_zero_oil() -> None:
    rates = monthly_rates([_rec(2025, 0, 1.0, 1.0), _rec(2025, 2, 0.0, 0.1)])
    assert len(rates) == 1
    assert rates[0].gor_sm3_sm3 is None
    assert rates[0].water_cut is None


def test_gross_basis_uses_gross_gas() -> None:
    rec = _rec(2026, 1, oil=0.154374, gas=0.0, gas_gross=0.170005)
    net, = monthly_rates([rec])
    gross, = monthly_rates([rec], basis="gross")
    assert net.gor_sm3_sm3 == pytest.approx(0.0)
    assert gross.gor_sm3_sm3 == pytest.approx(0.170005e9 / 0.154374e6, rel=1e-3)
    with pytest.raises(ValueError):
        monthly_rates([rec], basis="wet")


def test_ratio_trend_detects_rising_gor_and_water_cut() -> None:
    trend = ratio_trend(monthly_rates(_series()), window_months=12)
    assert trend.latest_month == "2025-12"
    assert trend.gor_change_fraction > 0
    assert trend.water_cut_change > 0
    assert trend.warnings == ()


def test_ratio_trend_warns_on_short_history_and_missing_water() -> None:
    rates = monthly_rates([_rec(2025, m, 0.2, 0.03) for m in range(1, 7)])
    trend = ratio_trend(rates, window_months=12)
    assert trend.recent_mean_water_cut is None
    assert any("only 6 months" in w for w in trend.warnings)
    assert any("previous window" in w for w in trend.warnings)
    assert any("water cut" in w for w in trend.warnings)
    with pytest.raises(ValueError):
        ratio_trend([], window_months=12)
    with pytest.raises(ValueError):
        ratio_trend(rates, window_months=0)


def test_ullage_indicator_peak_minus_recent() -> None:
    rates = monthly_rates(_series())
    ind = ullage_indicator(rates, window_months=12)
    oil = ind.stream("oil")
    # Peak is on daily rate, so a short month (Feb) can beat a larger month volume.
    best = max(rates, key=lambda r: r.oil_sm3_d)
    assert oil.peak_month == best.label == "2024-02"
    assert oil.historic_peak == pytest.approx(best.oil_sm3_d, abs=0.01)
    assert oil.indicative_ullage > 0
    assert 0 < oil.utilisation_of_peak < 1
    water = ind.stream("water")  # rising water: recent window holds the peak
    assert water.peak_month.startswith("2025")
    assert water.utilisation_of_peak > oil.utilisation_of_peak
    assert {s.stream for s in ind.streams} == {"oil", "gas", "water", "liquid", "oe"}
    assert "not nameplate" in ind.caveat
    with pytest.raises(KeyError):
        ind.stream("steam")


def test_haversine_known_distance() -> None:
    # One degree of latitude ~ 111.2 km
    assert haversine_km(60.0, 2.0, 61.0, 2.0) == pytest.approx(111.2, abs=0.2)
    assert haversine_km(60.0, 2.0, 60.0, 2.0) == 0.0


def _disc(name, lat, lon, field=None, status="Production in clarification phase", hc="GAS"):
    return Discovery(npdid=None, name=name, status=status, hc_type=hc, operator="X",
                     main_area="North sea", discovery_year=2020, field_name=field,
                     latitude=lat, longitude=lon)


def test_nearby_discoveries_filters_and_sorts() -> None:
    discs = [
        _disc("FAR", 62.0, 2.0),
        _disc("NEAR", 60.1, 2.0),
        _disc("MID", 60.3, 2.0, hc="OIL"),
        _disc("IN FIELD", 60.05, 2.0, field="HOST"),
        _disc("NO COORD", None, None),
    ]
    out = nearby_discoveries(60.0, 2.0, discs, radius_km=50)
    assert [c.name for c in out] == ["NEAR", "MID"]
    assert out[0].distance_km == pytest.approx(11.1, abs=0.1)
    assert [c.name for c in nearby_discoveries(60.0, 2.0, discs, hc_types=["oil"])] == ["MID"]
    with_field = nearby_discoveries(60.0, 2.0, discs, exclude_in_field=False)
    assert with_field[0].name == "IN FIELD"
    assert nearby_discoveries(60.0, 2.0, discs, statuses=["unlikely"]) == []
    with pytest.raises(ValueError):
        nearby_discoveries(60.0, 2.0, discs, radius_km=0)
    with pytest.raises(ValueError):
        nearby_discoveries(95.0, 2.0, discs)


def _fac(name, lat, lon, phase="IN SERVICE", fixed="FIXED"):
    return Facility(npdid=None, name=name, kind="JACKET", phase=phase, functions="",
                    fixed_or_moveable=fixed, belongs_to="HOST", belongs_to_kind="FIELD",
                    operator="X", water_depth_m=100.0, startup=None,
                    design_lifetime_years=None, latitude=lat, longitude=lon)


def test_pick_host_location_prefers_fixed_in_service() -> None:
    facs = [_fac("SUBSEA", 60.2, 2.2, fixed="MOVEABLE"), _fac("OLD", 60.4, 2.4, phase="REMOVED"),
            _fac("MAIN", 60.0, 2.0), _fac("NOWHERE", None, None)]
    assert pick_host_location(facs) == (60.0, 2.0)
    assert pick_host_location([_fac("NOWHERE", None, None)]) is None


def test_host_context_end_to_end_with_fake_service() -> None:
    series = _series()

    def fetch(url: str):
        table = int(urllib.parse.urlsplit(url).path.split("/")[-2])
        if table == TABLE_IDS["field"]:
            return {"features": [{"attributes": {"fldName": "HOST", "fldHcType": "OIL"}}]}
        if table == TABLE_IDS["facility"]:
            return {"features": [{"attributes": {
                "fclName": "HOST A", "fclPhase": "IN SERVICE", "fclFixedOrMoveable": "FIXED",
                "fclBelongsToName": "HOST", "fclNsDeg": 60, "fclNsMin": 0, "fclNsSec": 0,
                "fclNsCode": "N", "fclEwDeg": 2, "fclEwMin": 0, "fclEwSec": 0,
                "fclEwCode": "E"}}]}
        if table == TABLE_IDS["profiles"]:
            return {"features": [{"attributes": {
                "prfInformationCarrier": "HOST", "prfYear": r.year, "prfMonth": r.month,
                "prfPrdOilNetMillSm3": r.oil_net, "prfPrdGasNetBillSm3": r.gas_net,
                "prfPrdOeNetMillSm3": r.oe_net,
                "prfPrdProducedWaterInFieldMillS": r.water_mill_sm3}} for r in series]}
        if table == TABLE_IDS["discovery"]:
            return {"features": [{"attributes": {"dscNpdidDiscovery": 1, "dscName": "CAND",
                                                 "dscCurrentActivityStatus": "x"},
                                  "geometry": {"x": 2.0, "y": 60.2}}]}
        if table == TABLE_IDS["discovery_reserves"]:
            return {"features": [{"attributes": {"dscNpdidDiscovery": 1,
                                                 "dscRecoverableOe": 3.0}}]}
        raise AssertionError(url)

    ctx = host_context("host", service=SodirDataService(fetcher=fetch), radius_km=30)
    assert ctx.field_name == "HOST"
    assert (ctx.host_latitude, ctx.host_longitude) == (60.0, 2.0)
    assert len(ctx.monthly) == 24
    assert ctx.trend is not None and ctx.trend.gor_change_fraction > 0
    assert ctx.ullage is not None
    assert [c.name for c in ctx.candidates] == ["CAND"]
    assert ctx.candidates[0].recoverable_oe_mill_sm3 == 3.0
    assert "Sodir" in ctx.attribution
