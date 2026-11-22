"""Pipeline profile plot example with public synthetic data.

With the optional ``neqsim`` package the pressures, temperatures and hydrate
temperatures come from NeqSim (PipeBeggsAndBrills legs + hydrateFormationTemperature).
Without it, a small synthetic profile is used so the plotting still runs.

Run:
    python skills/flow-assurance/pipeline-profile-plot/examples/basic_pipeline_profile_plot.py [out_dir]
"""

from __future__ import annotations

import sys
from importlib.util import find_spec
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from pipeline_profile_plot import (
    PipelineProfile,
    plot_combined,
    plot_profile,
    save_figure,
)

# Synthetic tie-in route: new subsea well (KP 0) to a host platform (KP 25).
ROUTE = [
    {"kp_km": 0.0, "depth_m": 345.0, "lon": 3.300, "lat": 60.780},
    {"kp_km": 4.0, "depth_m": 352.0, "lon": 3.350, "lat": 60.752},
    {"kp_km": 9.0, "depth_m": 330.0, "lon": 3.420, "lat": 60.720},
    {"kp_km": 14.0, "depth_m": 338.0, "lon": 3.480, "lat": 60.685},
    {"kp_km": 20.0, "depth_m": 318.0, "lon": 3.545, "lat": 60.640},
    {"kp_km": 25.0, "depth_m": 303.0, "lon": 3.600, "lat": 60.600},
]


def neqsim_case():
    from neqsim import jneqsim
    from pipeline_profile_plot.neqsim_bridge import (
        add_hydrate_temperatures,
        hydrate_curve,
        run_route_pipeline,
    )

    fluid = jneqsim.thermo.system.SystemSrkCPAstatoil(273.15 + 55.0, 140.0)
    for name, moles in [
        ("nitrogen", 0.8), ("CO2", 2.0), ("methane", 80.0), ("ethane", 6.5), ("propane", 3.2),
        ("i-butane", 0.6), ("n-butane", 1.0), ("n-pentane", 0.5), ("n-hexane", 0.4), ("nC10", 1.5),
        ("water", 3.5),
    ]:
        fluid.addComponent(name, moles)
    fluid.setMixingRule(10)
    fluid.setMultiPhaseCheck(True)

    stream = jneqsim.process.equipment.stream.Stream("well stream", fluid)
    stream.setFlowRate(3.0, "MSm3/day")
    stream.setTemperature(55.0, "C")
    stream.setPressure(140.0, "bara")
    stream.run()

    profile, _pipes = run_route_pipeline(
        stream, ROUTE, diameter_m=0.254, ambient_temperature_c=4.0,
        heat_transfer_coefficient_w_m2k=6.0, name="NEW-1 to HOST A (synthetic)",
    )
    profile, _ = add_hydrate_temperatures(profile, fluid, resolution_bar=1.0)
    curve = hydrate_curve(fluid, 20.0, 160.0, 12)
    return profile, curve


def synthetic_case():
    kp = [0, 2, 4, 6, 9, 12, 14, 17, 20, 22, 25]
    depth = [345, 349, 352, 344, 330, 334, 338, 328, 318, 311, 303]
    pres = [140, 137.6, 135.2, 132.9, 129.6, 126.5, 124.4, 121.4, 118.3, 116.3, 113.4]
    temp = [55, 44, 35.5, 29, 22, 17, 14.5, 11.5, 9.0, 7.8, 6.5]
    hyd = [21.2, 21.0, 20.8, 20.6, 20.3, 20.0, 19.8, 19.5, 19.2, 19.0, 18.7]
    lon = [3.300 + 0.012 * k for k in kp]
    lat = [60.780 - 0.0072 * k for k in kp]
    profile = PipelineProfile(kp_km=kp, pressure_bara=pres, temperature_c=temp, depth_m=depth,
                              hydrate_temperature_c=hyd, lon=lon, lat=lat, name="Synthetic tie-in")
    return profile, None


def main(out_dir: str = ".") -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    profile, curve = neqsim_case() if find_spec("neqsim") else synthetic_case()

    result = profile.evaluate(min_margin=3.0)
    print("stations:", result.station_count, "length km:", result.length_km)
    print("arrival:", result.arrival_pressure_bara, "bara,", result.arrival_temperature_c, "C")
    print("min hydrate margin:", result.min_hydrate_margin_c, "C at KP", result.min_margin_kp_km)
    print("first hydrate KP:", result.first_hydrate_kp_km, "warning:", result.margin_warning)

    save_figure(plot_profile(profile, result=result), str(out / "pipeline_profile.png"))
    save_figure(plot_combined(profile, hydrate_curve=curve), str(out / "pipeline_combined.png"))
    print("wrote", out / "pipeline_profile.png", "and", out / "pipeline_combined.png")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
