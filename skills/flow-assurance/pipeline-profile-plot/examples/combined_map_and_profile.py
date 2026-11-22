"""Combined field map + pipeline profile example (synthetic public data).

Chains the two community skills:

1. ``neqsim-pipeline-profile-plot`` builds the along-route profile (NeqSim when
   installed, otherwise a synthetic profile) and screens the hydrate margin.
2. ``neqsim-offshore-field-map`` draws the same route on the field map, with
   every NeqSim station coloured by its hydrate-margin status and a tooltip
   showing KP, P, T and margin.
3. ``plot_combined`` puts map, P-T path and stacked profile on one page.

Run (both skills installed, or PYTHONPATH set to both src folders):
    python skills/flow-assurance/pipeline-profile-plot/examples/combined_map_and_profile.py [out_dir]
"""

from __future__ import annotations

import sys
from importlib.util import find_spec
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from basic_pipeline_profile_plot import neqsim_case, synthetic_case
from pipeline_profile_plot import plot_combined, save_figure


def main(out_dir: str = ".") -> None:
    if find_spec("offshore_field_map") is None:
        raise SystemExit("install the neqsim-offshore-field-map skill first")
    from basic_offshore_field_map import SYNTH_FACILITIES, SYNTH_FIELDS, SYNTH_PIPELINES
    from offshore_field_map import (
        FieldMapBuilder,
        normalize_facilities,
        normalize_fields,
        normalize_pipelines,
    )

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    profile, curve = neqsim_case() if find_spec("neqsim") else synthetic_case()
    result = profile.evaluate(min_margin=3.0)

    fm = FieldMapBuilder(f"{profile.name}: hydrate margin {result.margin_warning}")
    fm.add_fields(normalize_fields(SYNTH_FIELDS))
    fm.add_pipelines(normalize_pipelines(SYNTH_PIPELINES))
    fm.add_facilities(normalize_facilities(SYNTH_FACILITIES), highlight=["HOST A"])
    fm.add_nodes([{"name": "NEW-1", "lon": profile.lon[0], "lat": profile.lat[0], "kind": "well"}])
    fm.add_route(
        profile.name,
        list(zip(profile.lon, profile.lat)),
        values=profile.hydrate_margin_c,
        thresholds=(0.0, 3.0),
        vertex_info=[
            {"KP [km]": r["kp_km"], "P [bara]": r["pressure_bara"], "T [C]": r["temperature_c"],
             "Hydrate margin [C]": r.get("hydrate_margin_c")}
            for r in profile.records()
        ],
    )
    try:
        fm.save_html(str(out / "combined_map.html"))
        print("wrote", out / "combined_map.html")
    except ImportError:
        print("folium not installed; skipping interactive map")

    fig = plot_combined(profile, map_builder=fm, hydrate_curve=curve)
    save_figure(fig, str(out / "combined_dashboard.png"))
    print("wrote", out / "combined_dashboard.png")
    print("first hydrate KP:", result.first_hydrate_kp_km, "min margin:", result.min_hydrate_margin_c)


if __name__ == "__main__":
    here = Path(__file__).resolve()
    sys.path.insert(0, str(here.parent))
    sys.path.insert(0, str(here.parents[3] / "subsea" / "offshore-field-map" / "examples"))
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
