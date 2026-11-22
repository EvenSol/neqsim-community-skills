from urllib.parse import parse_qs, urlparse

import pytest
from offshore_field_map import (
    FieldMapBuilder,
    NormalizeReport,
    build_query_url,
    classify,
    elevation_to_depth,
    facilities_by_name,
    fetch_layer,
    haversine_m,
    normalize_facilities,
    normalize_fields,
    normalize_pipelines,
    parse_depth_profile,
    point_at_distance,
    polyline_length_m,
    sample_point_depth,
    sample_route_depths,
    wms_overlay,
)

# Synthetic features shaped like Sodir FactMaps GeoJSON (names and positions invented).
FACILITIES = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [3.60, 60.60]},
            "properties": {
                "fclName": "HOST A",
                "fclKind": "CONDEEP 4 SHAFTS",
                "fclPhase": "IN SERVICE",
                "fclWaterDepth": 303,
                "fclBelongsToName": "SYNTH FIELD",
                "fclCurrentOperatorName": "Example Operator",
            },
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [3.45, 60.70]},
            "properties": {"fclName": "TEMPLATE B", "fclKind": "SUBSEA STRUCTURE", "fclWaterDepth": "320"},
        },
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [999, 60]}, "properties": {"fclName": "BAD"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [3.0, 60.0]}, "properties": {}},
    ],
}

PIPELINES = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[3.45, 60.70], [3.52, 60.66], [3.60, 60.60]]},
            "properties": {
                "pplName": "SYNTH 12\" GAS",
                "fclNameFrom": "TEMPLATE B",
                "fclNameTo": "HOST A",
                "pplMedium": "Gas",
                "pplDimension": 12,
                "pplWaterDepth": 330,
                "pplCurrentPhase": "IN SERVICE",
            },
        },
        {
            "type": "Feature",
            "geometry": {"type": "MultiLineString", "coordinates": [[[3.6, 60.6], [3.9, 60.5]], [[3.9, 60.5]]]},
            "properties": {"pplName": "SYNTH OIL EXPORT", "pplMedium": "Oil"},
        },
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [3.6, 60.6]}, "properties": {"pplName": "WRONG"}},
    ],
}

FIELDS = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[[3.4, 60.55], [3.7, 60.55], [3.7, 60.75], [3.4, 60.75], [3.4, 60.55]]]},
            "properties": {"fldName": "SYNTH FIELD", "fldCurrentActivitySatus": "Producing", "fldHcType": "GAS"},
        }
    ],
}


def test_haversine_one_degree_latitude() -> None:
    assert haversine_m((3.0, 60.0), (3.0, 61.0)) == pytest.approx(111_195, rel=1e-3)


def test_point_at_distance_midpoint_and_clamp() -> None:
    line = [(3.0, 60.0), (3.0, 61.0)]
    total = polyline_length_m(line)
    _lon, lat = point_at_distance(line, total / 2)
    assert lat == pytest.approx(60.5, abs=1e-6)
    assert point_at_distance(line, -5) == line[0]
    assert point_at_distance(line, total * 2) == line[-1]


def test_build_query_url_has_geojson_wgs84_and_bbox() -> None:
    url = build_query_url("pipelines", bbox=(3.0, 60.0, 4.0, 61.0), record_count=500)
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    assert parsed.path.endswith("/311/query")
    assert q["f"] == ["geojson"]
    assert q["outSR"] == ["4326"]
    assert q["geometry"] == ["3.0,60.0,4.0,61.0"]
    assert q["resultRecordCount"] == ["500"]


def test_build_query_url_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        build_query_url("no-such-layer")
    with pytest.raises(ValueError):
        build_query_url(304, bbox=(4.0, 60.0, 3.0, 61.0))
    with pytest.raises(ValueError):
        build_query_url(304, record_count=5000)


def test_fetch_layer_pages_until_short_page() -> None:
    calls = []

    def fake(url):
        calls.append(url)
        offset = int(parse_qs(urlparse(url).query)["resultOffset"][0])
        count = 2 if offset == 0 else 1
        return {"type": "FeatureCollection", "features": [{"id": offset + i} for i in range(count)]}

    result = fetch_layer(304, page_size=2, fetcher=fake)
    assert len(result["features"]) == 3
    assert len(calls) == 2


def test_fetch_layer_raises_on_service_error() -> None:
    with pytest.raises(RuntimeError):
        fetch_layer(304, fetcher=lambda url: {"error": {"code": 400}})


def test_normalize_facilities_skips_bad_records() -> None:
    report = NormalizeReport()
    facilities = normalize_facilities(FACILITIES, report)
    assert [f.name for f in facilities] == ["HOST A", "TEMPLATE B"]
    assert facilities[1].water_depth_m == pytest.approx(320.0)
    assert len(report.skipped) == 2
    assert "HOST A" in facilities_by_name(facilities)


def test_normalize_pipelines_and_fields() -> None:
    report = NormalizeReport()
    pipes = normalize_pipelines(PIPELINES, report)
    assert [p.name for p in pipes] == ['SYNTH 12" GAS', "SYNTH OIL EXPORT"]
    assert pipes[0].diameter_inch == 12
    assert len(pipes[1].paths) == 1  # single-point part dropped
    assert len(report.skipped) == 1
    fields = normalize_fields(FIELDS)
    assert fields[0].status == "Producing"
    with pytest.raises(ValueError):
        normalize_fields({"type": "Feature"})


def test_emodnet_conversion_and_profile_spacing() -> None:
    assert elevation_to_depth(-301.7) == pytest.approx(301.7)
    assert elevation_to_depth(12.0) == 0.0
    assert elevation_to_depth(None) is None
    assert elevation_to_depth(float("nan")) is None
    route = [(3.45, 60.70), (3.60, 60.60)]
    samples = parse_depth_profile([-320, None, -310, -303], route)
    assert len(samples) == 3
    assert samples[0].distance_m == 0.0
    assert samples[-1].distance_m == pytest.approx(polyline_length_m(route))
    assert samples[-1].depth_m == pytest.approx(303)


def test_emodnet_fetch_helpers_with_injected_fetcher() -> None:
    assert sample_point_depth(3.7, 60.6, fetcher=lambda url: {"avg": -301.7}) == pytest.approx(301.7)
    samples = sample_route_depths([(3.45, 60.70), (3.60, 60.60)], fetcher=lambda url: [-320.0, -303.0])
    assert [s.depth_m for s in samples] == [320.0, 303.0]
    with pytest.raises(ValueError):
        sample_route_depths([(3.45, 60.70), (3.60, 60.60)], fetcher=lambda url: {"bad": 1})
    assert wms_overlay("contours").layers == "emodnet:contours"
    with pytest.raises(ValueError):
        wms_overlay("sepia")


def test_classify_both_directions() -> None:
    assert classify(-1.0) == "high"
    assert classify(0.0) == "high"
    assert classify(2.0) == "watch"
    assert classify(5.0) == "ok"
    assert classify(None) == "unknown"
    assert classify(25.0, thresholds=(20.0, 15.0), higher_is_better=False) == "high"
    assert classify(17.0, thresholds=(20.0, 15.0), higher_is_better=False) == "watch"
    with pytest.raises(ValueError):
        classify(1.0, thresholds=(3.0, 0.0))


def _builder() -> FieldMapBuilder:
    fm = FieldMapBuilder("Synthetic tie-in")
    fm.add_fields(normalize_fields(FIELDS))
    fm.add_pipelines(normalize_pipelines(PIPELINES))
    fm.add_facilities(normalize_facilities(FACILITIES), highlight=["host a", "MISSING"])
    fm.add_nodes([{"name": "NEW-1", "lon": 3.30, "lat": 60.78, "kind": "well", "water_depth_m": 340}])
    fm.add_route(
        "NEW-1 to HOST A",
        [(3.30, 60.78), (3.45, 60.70), (3.60, 60.60)],
        values=[12.0, 2.5, -1.0],
        vertex_info=[{"KP [km]": 0.0}, {"KP [km]": 11.6}, {"KP [km]": 25.3}],
    )
    return fm


def test_builder_summary_and_geojson() -> None:
    fm = _builder()
    summary = fm.summary()
    assert summary.route_count == 1
    assert summary.worst_route_status["NEW-1 to HOST A"] == "high"
    assert summary.route_lengths_km["NEW-1 to HOST A"] > 20
    assert any("MISSING" in w for w in summary.warnings)
    assert any("NLOD" in a for a in summary.attributions)
    gj = fm.to_geojson()
    route_segments = [f for f in gj["features"] if f["properties"]["layer"] == "route"]
    assert [f["properties"]["status"] for f in route_segments] == ["watch", "high"]


def test_builder_validates_inputs() -> None:
    fm = FieldMapBuilder()
    with pytest.raises(ValueError):
        fm.add_route("r", [(3.0, 60.0)])
    with pytest.raises(ValueError):
        fm.add_route("r", [(3.0, 60.0), (3.1, 60.1)], values=[1.0])
    with pytest.raises(ValueError):
        fm.add_nodes([{"name": "x", "lon": 3.0}])
    with pytest.raises(ValueError):
        fm.add_nodes([{"lon": 3.0, "lat": 60.0}])


def test_folium_render(tmp_path) -> None:
    pytest.importorskip("folium")
    fm = _builder()
    path = fm.save_html(str(tmp_path / "map.html"))
    text = (tmp_path / "map.html").read_text(encoding="utf-8")
    assert path.endswith("map.html")
    assert "emodnet:mean_multicolour" in text
    assert "NEW-1 to HOST A" in text
    assert "CC BY 4.0" in text and "NLOD" in text


def test_static_plot_render(tmp_path) -> None:
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    ax = _builder().plot_static()
    out = tmp_path / "map.png"
    ax.figure.savefig(out)
    assert out.stat().st_size > 1000
