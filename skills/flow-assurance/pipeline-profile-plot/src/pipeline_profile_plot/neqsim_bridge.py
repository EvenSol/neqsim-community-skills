"""Optional bridge from NeqSim calculations to a :class:`PipelineProfile`.

Everything here needs the ``neqsim`` Python package (``pip install neqsim``)
and calls validated NeqSim Java classes through ``jneqsim``:

* ``neqsim.process.equipment.pipeline.PipeBeggsAndBrills`` - one pipe per
  route leg, run in series so each leg gets its own elevation change.
  Profiles: ``getLengthProfile()`` [m], ``getPressureProfile()`` [bara],
  ``getTemperatureProfile()`` [K].
* ``neqsim.thermodynamicoperations.ThermodynamicOperations.hydrateFormationTemperature()``
  on a clone of the inlet fluid with ``setHydrateCheck(True)``.
* ``ThermodynamicOperations.calcPTphaseEnvelope()`` for an optional envelope.

The functions only orchestrate NeqSim; they add no thermodynamics of their own.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from math import isfinite, nan, sqrt
from typing import Any

from .profile import PipelineProfile

KELVIN = 273.15


def _jneqsim():
    try:
        from neqsim import jneqsim
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise ImportError("the neqsim package is required: pip install neqsim") from exc
    return jneqsim


@dataclass
class HydrateCurve:
    pressure_bara: list[float]
    temperature_c: list[float]
    errors: list[str] = field(default_factory=list)


def _route_rows(route: Sequence[Mapping[str, Any]]) -> list[dict[str, float]]:
    rows = []
    for raw in route:
        row = {"kp_km": float(raw["kp_km"]), "depth_m": float(raw["depth_m"])}
        if "lon" in raw and "lat" in raw:
            row["lon"] = float(raw["lon"])
            row["lat"] = float(raw["lat"])
        rows.append(row)
    if len(rows) < 2:
        raise ValueError("route needs at least two stations")
    for a, b in pairwise(rows):
        if b["kp_km"] <= a["kp_km"]:
            raise ValueError("route kp_km must be strictly increasing")
    if any(r["depth_m"] < 0 for r in rows):
        raise ValueError("depth_m is water depth and must be non-negative")
    has_xy = ["lon" in r for r in rows]
    if any(has_xy) and not all(has_xy):
        raise ValueError("give lon/lat for every route station or for none")
    return rows


def run_route_pipeline(
    inlet_stream: Any,
    route: Sequence[Mapping[str, Any]],
    *,
    diameter_m: float,
    ambient_temperature_c: float = 4.0,
    heat_transfer_coefficient_w_m2k: float = 15.0,
    roughness_m: float = 5.0e-5,
    increments_per_km: float = 2.0,
    min_increments_per_leg: int = 3,
    name: str = "Pipeline",
) -> tuple[PipelineProfile, list[Any]]:
    """Run ``PipeBeggsAndBrills`` leg by leg along a KP/depth route.

    ``route`` rows need ``kp_km`` and ``depth_m`` (water depth, positive down)
    and may carry ``lon``/``lat``. Each leg's elevation change is
    ``depth_in - depth_out`` (positive = rising). Returns the stitched profile
    and the list of NeqSim pipe objects (for further inspection).
    """
    if diameter_m <= 0:
        raise ValueError("diameter_m must be positive")
    rows = _route_rows(route)
    jneqsim = _jneqsim()
    Pipe = jneqsim.process.equipment.pipeline.PipeBeggsAndBrills

    kp: list[float] = []
    pres: list[float] = []
    temp: list[float] = []
    depth: list[float] = []
    lon: list[float] = []
    lat: list[float] = []
    pipes = []
    stream = inlet_stream
    for i, (a, b) in enumerate(pairwise(rows)):
        horizontal_m = (b["kp_km"] - a["kp_km"]) * 1000.0
        rise_m = a["depth_m"] - b["depth_m"]
        length_m = sqrt(horizontal_m**2 + rise_m**2)
        pipe = Pipe(f"{name} leg {i + 1}", stream)
        pipe.setDiameter(float(diameter_m))
        pipe.setLength(length_m)
        pipe.setElevation(rise_m)
        pipe.setPipeWallRoughness(float(roughness_m))
        pipe.setNumberOfIncrements(max(int(min_increments_per_leg), round(horizontal_m / 1000.0 * increments_per_km)))
        pipe.setConstantSurfaceTemperature(float(ambient_temperature_c), "C")
        pipe.setHeatTransferCoefficient(float(heat_transfer_coefficient_w_m2k))
        pipe.run()
        pipes.append(pipe)

        lengths = [float(x) for x in pipe.getLengthProfile()]
        pressures = [float(x) for x in pipe.getPressureProfile()]
        temps_k = [float(x) for x in pipe.getTemperatureProfile()]
        total = lengths[-1] if lengths and lengths[-1] > 0 else length_m
        for j, (l_m, p, t_k) in enumerate(zip(lengths, pressures, temps_k)):
            if i > 0 and j == 0:
                continue  # leg inlet equals previous leg outlet
            frac = 0.0 if total == 0 else l_m / total
            kp.append(a["kp_km"] + frac * (b["kp_km"] - a["kp_km"]))
            pres.append(p)
            temp.append(t_k - KELVIN)
            depth.append(a["depth_m"] + frac * (b["depth_m"] - a["depth_m"]))
            if "lon" in a:
                lon.append(a["lon"] + frac * (b["lon"] - a["lon"]))
                lat.append(a["lat"] + frac * (b["lat"] - a["lat"]))
        stream = pipe.getOutletStream()

    profile = PipelineProfile(
        kp_km=kp,
        pressure_bara=pres,
        temperature_c=temp,
        depth_m=depth,
        lon=lon or None,
        lat=lat or None,
        name=name,
        meta={
            "model": "neqsim.process.equipment.pipeline.PipeBeggsAndBrills (legs in series)",
            "diameter_m": diameter_m,
            "ambient_temperature_c": ambient_temperature_c,
            "heat_transfer_coefficient_w_m2k": heat_transfer_coefficient_w_m2k,
            "roughness_m": roughness_m,
        },
    )
    return profile, pipes


def hydrate_temperatures(
    fluid: Any,
    pressures_bara: Sequence[float],
    *,
    resolution_bar: float = 0.5,
    initial_guess_c: float = 10.0,
) -> HydrateCurve:
    """Hydrate equilibrium temperature [C] at each pressure for a NeqSim fluid.

    The fluid should include water (and any inhibitor) and use a CPA EoS such as
    ``SystemSrkCPAstatoil``. Results are cached on a ``resolution_bar`` grid,
    which keeps long profiles fast. Failed points are returned as NaN and the
    error text is kept in ``errors``.
    """
    if resolution_bar <= 0:
        raise ValueError("resolution_bar must be positive")
    jneqsim = _jneqsim()
    Ops = jneqsim.thermodynamicoperations.ThermodynamicOperations
    cache: dict[int, float] = {}
    out: list[float] = []
    errors: list[str] = []
    for p in pressures_bara:
        key = round(float(p) / resolution_bar)
        if key not in cache:
            p_eval = max(key * resolution_bar, 1.0)
            work = fluid.clone()
            try:
                work.setHydrateCheck(True)
                work.setPressure(p_eval)
                work.setTemperature(initial_guess_c + KELVIN)
                Ops(work).hydrateFormationTemperature()
                t_c = float(work.getTemperature()) - KELVIN
                cache[key] = t_c if isfinite(t_c) else nan
            except Exception as exc:  # noqa: BLE001 - Java exceptions vary
                cache[key] = nan
                errors.append(f"{p_eval:.2f} bara: {exc}")
        out.append(cache[key])
    return HydrateCurve(pressure_bara=[float(p) for p in pressures_bara], temperature_c=out, errors=errors)


def add_hydrate_temperatures(profile: PipelineProfile, fluid: Any, **kwargs: Any) -> tuple[PipelineProfile, HydrateCurve]:
    """Return a copy of ``profile`` with NeqSim hydrate temperatures at each station."""
    curve = hydrate_temperatures(fluid, profile.pressure_bara, **kwargs)
    return profile.with_hydrate_temperatures(curve.temperature_c), curve


def hydrate_curve(fluid: Any, p_min_bara: float = 10.0, p_max_bara: float = 200.0, points: int = 20) -> HydrateCurve:
    """Hydrate equilibrium curve over a pressure range, for P-T plots."""
    if points < 2 or p_max_bara <= p_min_bara:
        raise ValueError("need points >= 2 and p_max_bara > p_min_bara")
    step = (p_max_bara - p_min_bara) / (points - 1)
    pressures = [p_min_bara + i * step for i in range(points)]
    return hydrate_temperatures(fluid, pressures, resolution_bar=step / 4.0)


def phase_envelope(fluid: Any) -> dict[str, list[float]] | None:
    """PT phase envelope (dew and bubble branches) in C and bara, or ``None``.

    Uses ``ThermodynamicOperations.calcPTphaseEnvelope()`` on a clone. Envelopes
    of water-saturated CPA fluids can fail to converge; in that case ``None`` is
    returned and the plot simply omits the envelope.
    """
    jneqsim = _jneqsim()
    work = fluid.clone()
    try:
        ops = jneqsim.thermodynamicoperations.ThermodynamicOperations(work)
        ops.calcPTphaseEnvelope()
        out: dict[str, list[float]] = {}
        for key in ("dewT", "dewP", "bubT", "bubP"):
            values = [float(v) for v in ops.get(key)]
            out[key] = values
    except Exception:  # noqa: BLE001
        return None
    pairs = {}
    for branch in ("dew", "bub"):
        ts, ps = out.get(f"{branch}T", []), out.get(f"{branch}P", [])
        clean = [(t - KELVIN, p) for t, p in zip(ts, ps) if isfinite(t) and isfinite(p) and t > 0]
        pairs[f"{branch}_temperature_c"] = [t for t, _ in clean]
        pairs[f"{branch}_pressure_bara"] = [p for _, p in clean]
    if not pairs["dew_temperature_c"] and not pairs["bub_temperature_c"]:
        return None
    return pairs
