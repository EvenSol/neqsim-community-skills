import math

import pytest
from pipeline_profile_plot import PipelineProfile, margin_status


def _profile(**overrides):
    data = dict(
        kp_km=[0, 5, 10, 15, 20, 25],
        pressure_bara=[140, 135, 130, 125, 118, 112],
        temperature_c=[55, 40, 30, 24, 20, 16],
        depth_m=[345, 352, 330, 338, 318, 303],
        hydrate_temperature_c=[22, 21.9, 21.7, 21.5, 21.2, 21.0],
        lon=[3.30, 3.36, 3.42, 3.48, 3.54, 3.60],
        lat=[60.78, 60.75, 60.72, 60.68, 60.64, 60.60],
        name="Synthetic",
    )
    data.update(overrides)
    return PipelineProfile(**data)


def test_margin_status_thresholds() -> None:
    assert margin_status(-0.1) == "high"
    assert margin_status(0.0) == "high"
    assert margin_status(2.9) == "watch"
    assert margin_status(3.0) == "ok"
    assert margin_status(float("nan")) == "unknown"
    assert margin_status(None) == "unknown"


def test_evaluate_finds_sections_and_minimum() -> None:
    result = _profile().evaluate(min_margin=3.0)
    assert result.length_km == pytest.approx(25.0)
    assert result.arrival_pressure_bara == pytest.approx(112.0)
    assert result.min_hydrate_margin_c == pytest.approx(-5.0)
    assert result.min_margin_kp_km == pytest.approx(25.0)
    assert result.first_watch_kp_km == pytest.approx(15.0)
    assert result.first_hydrate_kp_km == pytest.approx(20.0)
    assert result.margin_warning == "high"
    assert [(s.kp_start_km, s.kp_end_km) for s in result.hydrate_sections] == [(20.0, 25.0)]
    assert result.watch_sections[0].status == "high"
    assert result.watch_sections[0].kp_start_km == pytest.approx(15.0)


def test_evaluate_ok_and_unknown() -> None:
    warm = _profile(temperature_c=[60, 58, 56, 54, 52, 50])
    assert warm.evaluate().margin_warning == "ok"
    no_hyd = _profile(hydrate_temperature_c=None)
    result = no_hyd.evaluate()
    assert result.margin_warning == "unknown"
    assert result.min_hydrate_margin_c is None
    assert any("No hydrate temperatures" in a for a in result.assumptions)


def test_nan_hydrate_points_are_tolerated() -> None:
    prof = _profile(hydrate_temperature_c=[22, None, 21.7, float("nan"), 21.2, 21.0])
    result = prof.evaluate()
    assert result.margin_warning == "high"
    assert math.isnan(prof.hydrate_margin_c[1])


def test_validation_errors() -> None:
    with pytest.raises(ValueError):
        _profile(kp_km=[0, 5, 4, 15, 20, 25])
    with pytest.raises(ValueError):
        _profile(pressure_bara=[140, 135, 130])
    with pytest.raises(ValueError):
        _profile(pressure_bara=[140, 135, 0, 125, 118, 112])
    with pytest.raises(ValueError):
        _profile(depth_m=[345, -1, 330, 338, 318, 303])
    with pytest.raises(ValueError):
        _profile(lat=None)
    with pytest.raises(ValueError):
        PipelineProfile(kp_km=[0], pressure_bara=[10], temperature_c=[5])
    with pytest.raises(ValueError):
        _profile().evaluate(min_margin=0)


def test_records_roundtrip() -> None:
    prof = _profile()
    rows = prof.records()
    assert rows[-1]["hydrate_margin_c"] == pytest.approx(-5.0)
    again = PipelineProfile.from_records(rows, name="again")
    assert again.kp_km == prof.kp_km
    assert again.hydrate_temperature_c == prof.hydrate_temperature_c
    assert prof.elevation_m[0] == -345


def test_plots_render(tmp_path) -> None:
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    from pipeline_profile_plot import plot_combined, plot_profile, plot_pt_trajectory, save_figure

    prof = _profile()
    fig = plot_profile(prof)
    assert len(fig.axes) == 4
    save_figure(fig, str(tmp_path / "p.png"))

    class Curve:
        pressure_bara = (20, 80, 140)
        temperature_c = (9.0, 18.0, 22.0)

    envelope = {"dew_temperature_c": [-80, 0, 40], "dew_pressure_bara": [5, 60, 90]}
    ax = plot_pt_trajectory(prof, hydrate_curve=Curve(), envelope=envelope)
    assert ax.get_xlabel() == "Temperature [C]"
    combined = plot_combined(prof, hydrate_curve=Curve())
    save_figure(combined, str(tmp_path / "c.png"))
    assert (tmp_path / "c.png").stat().st_size > 10_000
    # profile without depth, hydrate and coordinates still renders
    bare = PipelineProfile(kp_km=[0, 1], pressure_bara=[10, 9], temperature_c=[20, 18])
    assert len(plot_profile(bare).axes) == 2
    assert len(plot_combined(bare).axes) == 3


def test_neqsim_bridge_small_route() -> None:
    pytest.importorskip("neqsim")
    from neqsim import jneqsim
    from pipeline_profile_plot.neqsim_bridge import add_hydrate_temperatures, run_route_pipeline

    fluid = jneqsim.thermo.system.SystemSrkCPAstatoil(273.15 + 40.0, 100.0)
    for name, moles in [("methane", 85.0), ("ethane", 6.0), ("propane", 3.0), ("CO2", 2.0), ("water", 4.0)]:
        fluid.addComponent(name, moles)
    fluid.setMixingRule(10)
    fluid.setMultiPhaseCheck(True)
    stream = jneqsim.process.equipment.stream.Stream("s", fluid)
    stream.setFlowRate(2.0, "MSm3/day")
    stream.run()
    route = [
        {"kp_km": 0.0, "depth_m": 300.0, "lon": 3.0, "lat": 60.0},
        {"kp_km": 3.0, "depth_m": 280.0, "lon": 3.05, "lat": 60.0},
        {"kp_km": 6.0, "depth_m": 100.0, "lon": 3.10, "lat": 60.0},
    ]
    profile, pipes = run_route_pipeline(stream, route, diameter_m=0.25, increments_per_km=1.0)
    assert len(pipes) == 2
    assert profile.kp_km[0] == 0.0 and profile.kp_km[-1] == pytest.approx(6.0)
    assert profile.pressure_bara[-1] < profile.pressure_bara[0]
    assert profile.temperature_c[-1] < profile.temperature_c[0]
    assert profile.lon[-1] == pytest.approx(3.10)
    with_hyd, _curve = add_hydrate_temperatures(profile, fluid, resolution_bar=5.0)
    finite = [t for t in with_hyd.hydrate_temperature_c if math.isfinite(t)]
    assert finite and all(0.0 < t < 30.0 for t in finite)
    with pytest.raises(ValueError):
        run_route_pipeline(stream, route[:1], diameter_m=0.25)
