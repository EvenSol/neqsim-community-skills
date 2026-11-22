"""Offline tests for the Sodir DataService client (fake fetcher, no network)."""

from __future__ import annotations

import urllib.parse

import pytest
from norwegian_continental_shelf_data import (
    SODIR_DATASERVICE_URL,
    TABLE_IDS,
    SodirApiError,
    SodirDataService,
    facility_from_attributes,
    production_record_from_attributes,
)
from norwegian_continental_shelf_data.sodir_api import (
    dms_to_decimal,
    esri_centroid,
    sql_quote,
)


def _params(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).items()}


def _table(url: str) -> int:
    return int(urllib.parse.urlsplit(url).path.rstrip("/").split("/")[-2])


def test_query_url_is_built_against_dataservice() -> None:
    svc = SodirDataService(fetcher=lambda url: {"features": []})
    url = svc.query_url("profiles", where="prfYear=2026", out_fields=["prfYear", "prfMonth"])
    assert url.startswith(f"{SODIR_DATASERVICE_URL}/{TABLE_IDS['profiles']}/query?")
    params = _params(url)
    assert params["where"] == "prfYear=2026"
    assert params["outFields"] == "prfYear,prfMonth"
    assert params["returnGeometry"] == "false"
    assert params["f"] == "json"
    assert "outSR" not in params  # only sent with geometry


def test_query_url_with_geometry_sets_wgs84_and_generalisation() -> None:
    svc = SodirDataService(fetcher=lambda url: {"features": []})
    params = _params(svc.query_url("discovery", return_geometry=True, max_allowable_offset=0.01))
    assert params["outSR"] == "4326"
    assert params["maxAllowableOffset"] == "0.01"


def test_unknown_table_raises() -> None:
    with pytest.raises(KeyError):
        SodirDataService.table_id("no_such_table")
    assert SodirDataService.table_id(7300) == 7300


def test_pagination_follows_exceeded_transfer_limit() -> None:
    def fetch(url: str):
        offset = int(_params(url)["resultOffset"])
        if offset == 0:
            return {"features": [{"attributes": {"i": 0}}, {"attributes": {"i": 1}}],
                    "exceededTransferLimit": True}
        if offset == 2:
            return {"features": [{"attributes": {"i": 2}}], "exceededTransferLimit": False}
        raise AssertionError(f"unexpected offset {offset}")

    svc = SodirDataService(fetcher=fetch, page_size=2)
    rows = svc.query("field")
    assert [r["i"] for r in rows] == [0, 1, 2]
    assert len(svc.requested_urls) == 2


def test_max_records_caps_result() -> None:
    def fetch(url: str):
        return {"features": [{"attributes": {"i": n}} for n in range(5)],
                "exceededTransferLimit": True}

    rows = SodirDataService(fetcher=fetch, max_records=7).query("field")
    assert len(rows) == 7


def test_service_error_and_bad_payload_raise() -> None:
    with pytest.raises(SodirApiError, match="Invalid query"):
        SodirDataService(fetcher=lambda u: {"error": {"message": "Invalid query"}}).query("field")
    with pytest.raises(SodirApiError, match="features"):
        SodirDataService(fetcher=lambda u: {"foo": 1}).query("field")


def test_invalid_construction() -> None:
    with pytest.raises(ValueError):
        SodirDataService(page_size=0)
    with pytest.raises(ValueError):
        SodirDataService(max_records=0)


def test_sql_quote_escapes_apostrophes() -> None:
    assert sql_quote("O'NEIL") == "'O''NEIL'"


def test_field_production_filters_period_and_sorts() -> None:
    seen = {}

    def fetch(url: str):
        seen["where"] = _params(url)["where"]
        return {"features": [
            {"attributes": {"prfInformationCarrier": "GRANE", "prfInformationCarrierKind": "FIELD",
                            "prfYear": 2026, "prfMonth": 2, "prfPrdOilNetMillSm3": 0.154545,
                            "prfPrdGasNetBillSm3": 0.0, "prfPrdOeNetMillSm3": 0.154545,
                            "prfPrdGasGrossBillSm3": 0.143912,
                            "prfPrdProducedWaterInFieldMillS": None}},
            {"attributes": {"prfInformationCarrier": "GRANE", "prfInformationCarrierKind": "FIELD",
                            "prfYear": 2026, "prfMonth": 1, "prfPrdOilNetMillSm3": 0.154374,
                            "prfPrdGasNetBillSm3": 0.0, "prfPrdOeNetMillSm3": 0.154374}},
        ]}

    recs = SodirDataService(fetcher=fetch).field_production("Grane")
    assert "UPPER(prfInformationCarrier)='GRANE'" in seen["where"]
    assert "prfPeriod='month'" in seen["where"]
    assert [r.month for r in recs] == [1, 2]
    assert recs[1].gas_gross == pytest.approx(0.143912)
    assert recs[0].water_mill_sm3 is None
    with pytest.raises(ValueError):
        SodirDataService(fetcher=fetch).field_production("Grane", period="week")


def test_field_overview_not_found() -> None:
    with pytest.raises(KeyError):
        SodirDataService(fetcher=lambda u: {"features": []}).field_overview("NOPE")


def test_production_record_water_column_variants() -> None:
    base = {"prfYear": 2020, "prfMonth": 3}
    assert production_record_from_attributes(
        {**base, "prfPrdProducedWaterInFieldMillS": 0.5}).water_mill_sm3 == 0.5
    assert production_record_from_attributes(
        {**base, "prfPrdProducedWaterInFieldMillSm3": 0.4}).water_mill_sm3 == 0.4
    yearly = production_record_from_attributes({"prfYear": 2020, "prfMonth": 0})
    assert not yearly.is_monthly


def test_dms_and_facility_coordinates() -> None:
    assert dms_to_decimal(59, 30, 0.0, "N") == pytest.approx(59.5)
    assert dms_to_decimal(2, 15, 0.0, "W") == pytest.approx(-2.25)
    assert dms_to_decimal(None, 1, 1, "N") is None
    fac = facility_from_attributes({
        "fclName": "HOST A", "fclKind": "CONDEEP 4 SHAFTS", "fclPhase": "IN SERVICE",
        "fclFixedOrMoveable": "FIXED", "fclBelongsToName": "HOST",
        "fclNsDeg": 60, "fclNsMin": 0, "fclNsSec": 0.0, "fclNsCode": "N",
        "fclEwDeg": 2, "fclEwMin": 30, "fclEwSec": 0.0, "fclEwCode": "E",
        "fclWaterDepth": 120.0, "fclStartupDate": 946684800000,
    })
    assert (fac.latitude, fac.longitude) == pytest.approx((60.0, 2.5))
    assert fac.startup == "2000-01-01"
    assert fac.water_depth_m == 120.0


def test_esri_centroid_point_and_polygon() -> None:
    assert esri_centroid({"x": 2.0, "y": 60.0}) == (60.0, 2.0)
    square = {"rings": [[[2.0, 60.0], [3.0, 60.0], [3.0, 61.0], [2.0, 61.0], [2.0, 60.0]]]}
    assert esri_centroid(square) == pytest.approx((60.5, 2.5))
    assert esri_centroid(None) is None
    assert esri_centroid({"rings": []}) is None


def test_discoveries_join_latest_resources() -> None:
    def fetch(url: str):
        table = _table(url)
        if table == TABLE_IDS["discovery"]:
            return {"features": [{
                "attributes": {"dscNpdidDiscovery": 11, "dscName": "35/11-99 X",
                               "dscCurrentActivityStatus": "Production in clarification phase",
                               "dscHcType": "OIL/GAS", "fldName": None},
                "geometry": {"rings": [[[3.0, 61.0], [3.2, 61.0], [3.2, 61.2], [3.0, 61.2]]]},
            }]}
        if table == TABLE_IDS["discovery_reserves"]:
            return {"features": [
                {"attributes": {"dscNpdidDiscovery": 11, "dscRecoverableOe": 1.0,
                                "dscReservesDateUpdated": 1000}},
                {"attributes": {"dscNpdidDiscovery": 11, "dscRecoverableOe": 2.5,
                                "dscReservesDateUpdated": 2000, "dscReservesRC": "7F"}},
            ]}
        raise AssertionError(url)

    (disc,) = SodirDataService(fetcher=fetch).discoveries()
    assert disc.latitude == pytest.approx(61.1)
    assert disc.longitude == pytest.approx(3.1)
    assert disc.resources is not None
    assert disc.resources.oe_mill_sm3 == 2.5
    assert disc.resources.resource_category == "7F"
    assert disc.field_name is None
