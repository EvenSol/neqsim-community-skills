"""Offshore field map example.

Default (offline): synthetic Sodir-shaped layers around a synthetic host, a new
well, and a tie-in route coloured by hydrate margin. Writes an interactive
``field_map.html`` (folium + EMODnet WMS overlay, loaded by the browser) and a
static ``field_map.png``.

Live mode (network, public open data): ``--live "TROLL A"`` downloads Sodir
facilities, pipelines and fields within 40 km of that facility (NLOD 2.0) and
samples the EMODnet depth along the example route (CC BY 4.0).

Run:
    python skills/subsea/offshore-field-map/examples/basic_offshore_field_map.py [out_dir] [--live NAME]
"""

from __future__ import annotations

import sys
from pathlib import Path

from offshore_field_map import (
    LAYERS,
    FieldMapBuilder,
    bbox_around,
    facilities_by_name,
    fetch_layer,
    normalize_facilities,
    normalize_fields,
    normalize_pipelines,
    sample_route_depths,
)

SYNTH_FACILITIES = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [3.60, 60.60]},
         "properties": {"fclName": "HOST A", "fclKind": "FIXED PLATFORM", "fclWaterDepth": 303}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [3.72, 60.66]},
         "properties": {"fclName": "TEMPLATE C", "fclKind": "SUBSEA STRUCTURE", "fclWaterDepth": 315}},
    ],
}
SYNTH_PIPELINES = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[3.72, 60.66], [3.60, 60.60]]},
         "properties": {"pplName": "SYNTH 10in GAS", "fclNameFrom": "TEMPLATE C", "fclNameTo": "HOST A", "pplMedium": "Gas", "pplDimension": 10}},
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[3.60, 60.60], [4.20, 60.45], [4.80, 60.50]]},
         "properties": {"pplName": "SYNTH EXPORT", "fclNameFrom": "HOST A", "fclNameTo": "SHORE", "pplMedium": "Gas", "pplDimension": 36}},
    ],
}
SYNTH_FIELDS = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature",
         "geometry": {"type": "Polygon", "coordinates": [[[3.50, 60.55], [3.80, 60.55], [3.80, 60.70], [3.50, 60.70], [3.50, 60.55]]]},
         "properties": {"fldName": "SYNTH FIELD", "fldCurrentActivitySatus": "Producing", "fldHcType": "GAS"}},
    ],
}

NEW_WELL = {"name": "NEW-1", "lon": 3.30, "lat": 60.78, "kind": "well", "water_depth_m": 345}
ROUTE = [(3.300, 60.780), (3.350, 60.752), (3.420, 60.720), (3.480, 60.685), (3.545, 60.640), (3.600, 60.600)]
# Hydrate margin [C] per route vertex, e.g. from the neqsim-pipeline-profile-plot skill.
ROUTE_MARGIN = [33.2, 24.0, 14.5, 6.8, -0.3, -4.7]
ROUTE_INFO = [{"KP [km]": kp, "Hydrate margin [C]": m} for kp, m in zip([0, 4, 9, 14, 20, 25], ROUTE_MARGIN)]


def build(live: str | None) -> FieldMapBuilder:
    fm = FieldMapBuilder("NEW-1 tie-in screening (synthetic)" if not live else f"Tie-in near {live}")
    if live:
        everything = normalize_facilities(fetch_layer(LAYERS["facilities_in_place"], where=f"fclName='{live}'"))
        host = facilities_by_name(everything).get(live.upper())
        if host is None:
            raise SystemExit(f"facility {live!r} not found in Sodir FactMaps")
        box = bbox_around([(host.lon, host.lat)], margin_km=40.0)
        fm.add_fields(normalize_fields(fetch_layer(LAYERS["fields"], bbox=box)))
        fm.add_pipelines(normalize_pipelines(fetch_layer(LAYERS["pipelines"], bbox=box)))
        fm.add_facilities(normalize_facilities(fetch_layer(LAYERS["facilities_in_place"], bbox=box)), highlight=[live])
        depths = sample_route_depths(ROUTE)
        print("EMODnet depth along route [m]:", [round(s.depth_m) for s in depths[:: max(1, len(depths) // 8)]])
        fm.use_emodnet()
    else:
        fm.add_fields(normalize_fields(SYNTH_FIELDS))
        fm.add_pipelines(normalize_pipelines(SYNTH_PIPELINES))
        fm.add_facilities(normalize_facilities(SYNTH_FACILITIES), highlight=["HOST A"])
    fm.add_nodes([NEW_WELL])
    fm.add_route("NEW-1 to HOST A", ROUTE, values=ROUTE_MARGIN, vertex_info=ROUTE_INFO)
    return fm


def main(argv: list[str]) -> None:
    live = None
    if "--live" in argv:
        i = argv.index("--live")
        live = argv[i + 1]
        argv = argv[:i] + argv[i + 2 :]
    out = Path(argv[0] if argv else ".")
    out.mkdir(parents=True, exist_ok=True)

    fm = build(live)
    summary = fm.summary()
    print("route length km:", summary.route_lengths_km)
    print("worst route status:", summary.worst_route_status)
    print("attribution:", "; ".join(summary.attributions))

    try:
        fm.save_html(str(out / "field_map.html"), bathymetry="multicolour")
        print("wrote", out / "field_map.html")
    except ImportError:
        print("folium not installed; skipping HTML map")
    try:
        import matplotlib

        matplotlib.use("Agg")
        ax = fm.plot_static()
        ax.figure.savefig(out / "field_map.png", dpi=160, bbox_inches="tight")
        print("wrote", out / "field_map.png")
    except ImportError:
        print("matplotlib not installed; skipping static map")


if __name__ == "__main__":
    main(sys.argv[1:])
