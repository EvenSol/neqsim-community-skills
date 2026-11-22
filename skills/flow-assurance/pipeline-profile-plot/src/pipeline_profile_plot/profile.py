"""Along-route pipeline profile data and hydrate-margin screening.

A :class:`PipelineProfile` holds one value per station along a pipeline:
KP, seabed water depth, pressure, temperature and (optionally) the hydrate
equilibrium temperature at the local pressure, plus optional longitude and
latitude so the same profile can be drawn on a map. The pressures and
temperatures are expected to come from a validated NeqSim pipeline model
(for example ``PipeBeggsAndBrills``) and the hydrate temperatures from
``ThermodynamicOperations.hydrateFormationTemperature()``; see
:mod:`pipeline_profile_plot.neqsim_bridge`.

The screening in :meth:`PipelineProfile.evaluate` uses the same rule as the
``neqsim-hydrate-margin-check`` skill: margin = T - T_hydrate; ``<= 0`` is
``high`` (inside the hydrate region), ``< min_margin`` is ``watch``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from importlib.util import find_spec
from itertools import pairwise
from math import isfinite, nan
from typing import Any


def _floats(name: str, values: Sequence[Any] | None, n: int | None, allow_nan: bool = False) -> tuple[float, ...] | None:
    if values is None:
        return None
    out = []
    for v in values:
        if v is None:
            if not allow_nan:
                raise ValueError(f"{name} contains a missing value")
            out.append(nan)
            continue
        f = float(v)
        if not isfinite(f) and not allow_nan:
            raise ValueError(f"{name} contains a non-finite value")
        out.append(f)
    if n is not None and len(out) != n:
        raise ValueError(f"{name} has {len(out)} values, expected {n}")
    return tuple(out)


@dataclass(frozen=True)
class Section:
    """A contiguous KP interval sharing one screening status."""

    status: str
    kp_start_km: float
    kp_end_km: float
    min_margin_c: float


@dataclass(frozen=True)
class ProfileScreeningResult:
    station_count: int
    length_km: float
    inlet_pressure_bara: float
    arrival_pressure_bara: float
    inlet_temperature_c: float
    arrival_temperature_c: float
    min_temperature_c: float
    min_hydrate_margin_c: float | None
    min_margin_kp_km: float | None
    first_watch_kp_km: float | None
    first_hydrate_kp_km: float | None
    hydrate_sections: tuple[Section, ...]
    watch_sections: tuple[Section, ...]
    margin_warning: str
    neqsim_available: bool
    assumptions: tuple[str, ...]


@dataclass(frozen=True)
class PipelineProfile:
    """Stations along a pipeline. Depth is water depth, positive downwards."""

    kp_km: tuple[float, ...]
    pressure_bara: tuple[float, ...]
    temperature_c: tuple[float, ...]
    depth_m: tuple[float, ...] | None = None
    hydrate_temperature_c: tuple[float, ...] | None = None
    lon: tuple[float, ...] | None = None
    lat: tuple[float, ...] | None = None
    name: str = "Pipeline"
    meta: Mapping[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        kp = _floats("kp_km", self.kp_km, None)
        if kp is None or len(kp) < 2:
            raise ValueError("a profile needs at least two stations")
        n = len(kp)
        if any(b < a for a, b in pairwise(kp)):
            raise ValueError("kp_km must be non-decreasing")
        object.__setattr__(self, "kp_km", kp)
        object.__setattr__(self, "pressure_bara", _floats("pressure_bara", self.pressure_bara, n))
        object.__setattr__(self, "temperature_c", _floats("temperature_c", self.temperature_c, n))
        if any(p <= 0.0 for p in self.pressure_bara):
            raise ValueError("pressure_bara must be positive (absolute pressure)")
        if any(t < -273.15 for t in self.temperature_c):
            raise ValueError("temperature_c below absolute zero")
        depth = _floats("depth_m", self.depth_m, n)
        if depth is not None and any(d < 0.0 for d in depth):
            raise ValueError("depth_m is water depth and must be non-negative (positive downwards)")
        object.__setattr__(self, "depth_m", depth)
        object.__setattr__(self, "hydrate_temperature_c", _floats("hydrate_temperature_c", self.hydrate_temperature_c, n, allow_nan=True))
        lon = _floats("lon", self.lon, n)
        lat = _floats("lat", self.lat, n)
        if (lon is None) != (lat is None):
            raise ValueError("give both lon and lat, or neither")
        object.__setattr__(self, "lon", lon)
        object.__setattr__(self, "lat", lat)

    # -------------------------------------------------------------- builders

    @classmethod
    def from_records(cls, records: Iterable[Mapping[str, Any]], name: str = "Pipeline") -> PipelineProfile:
        """Build from rows with keys ``kp_km``, ``pressure_bara``, ``temperature_c``
        and optionally ``depth_m``, ``hydrate_temperature_c``, ``lon``, ``lat``."""
        rows = list(records)

        def col(key: str):
            if all(key in r and r[key] is not None for r in rows):
                return [r[key] for r in rows]
            if any(key in r and r[key] is not None for r in rows) and key != "hydrate_temperature_c":
                raise ValueError(f"column {key!r} is present for some rows only")
            if key == "hydrate_temperature_c" and any(key in r for r in rows):
                return [r.get(key) for r in rows]
            return None

        return cls(
            kp_km=col("kp_km") or [],
            pressure_bara=col("pressure_bara") or [],
            temperature_c=col("temperature_c") or [],
            depth_m=col("depth_m"),
            hydrate_temperature_c=col("hydrate_temperature_c"),
            lon=col("lon"),
            lat=col("lat"),
            name=name,
        )

    def with_hydrate_temperatures(self, values: Sequence[float | None]) -> PipelineProfile:
        return replace(self, hydrate_temperature_c=tuple(nan if v is None else float(v) for v in values))

    def with_coordinates(self, lon: Sequence[float], lat: Sequence[float]) -> PipelineProfile:
        return replace(self, lon=tuple(lon), lat=tuple(lat))

    # ----------------------------------------------------------------- derived

    @property
    def length_km(self) -> float:
        return self.kp_km[-1] - self.kp_km[0]

    @property
    def elevation_m(self) -> tuple[float, ...] | None:
        """Pipe elevation relative to sea level (negative below), from depth."""
        return None if self.depth_m is None else tuple(-d for d in self.depth_m)

    @property
    def hydrate_margin_c(self) -> tuple[float, ...] | None:
        if self.hydrate_temperature_c is None:
            return None
        return tuple(t - h if isfinite(h) else nan for t, h in zip(self.temperature_c, self.hydrate_temperature_c))

    def records(self) -> list[dict[str, float]]:
        """Rows suitable for CSV/JSON export or a results.json block."""
        margin = self.hydrate_margin_c
        rows = []
        for i, kp in enumerate(self.kp_km):
            row = {"kp_km": kp, "pressure_bara": self.pressure_bara[i], "temperature_c": self.temperature_c[i]}
            if self.depth_m is not None:
                row["depth_m"] = self.depth_m[i]
            if self.hydrate_temperature_c is not None:
                row["hydrate_temperature_c"] = self.hydrate_temperature_c[i]
                row["hydrate_margin_c"] = margin[i]  # type: ignore[index]
            if self.lon is not None and self.lat is not None:
                row["lon"] = self.lon[i]
                row["lat"] = self.lat[i]
            rows.append(row)
        return rows

    # -------------------------------------------------------------- screening

    def evaluate(self, min_margin: float = 3.0) -> ProfileScreeningResult:
        """Screen the hydrate margin along the profile."""
        if not isfinite(min_margin) or min_margin <= 0.0:
            raise ValueError("min_margin must be a positive temperature difference in C")
        margin = self.hydrate_margin_c
        statuses = None if margin is None else [margin_status(m, min_margin) for m in margin]

        min_m = None
        min_kp = None
        first_watch = None
        first_hyd = None
        hyd_sections: list[Section] = []
        watch_sections: list[Section] = []
        warning = "unknown"
        if margin is not None and statuses is not None:
            finite = [(m, kp) for m, kp in zip(margin, self.kp_km) if isfinite(m)]
            if finite:
                min_m, min_kp = min(finite, key=lambda x: x[0])
                min_m = round(min_m, 3)
            for kp, status in zip(self.kp_km, statuses):
                if status in ("watch", "high") and first_watch is None:
                    first_watch = kp
                if status == "high" and first_hyd is None:
                    first_hyd = kp
            hyd_sections = _sections(self.kp_km, margin, statuses, {"high"})
            watch_sections = _sections(self.kp_km, margin, statuses, {"watch", "high"})
            ranked = [s for s in statuses if s != "unknown"]
            if ranked:
                warning = "high" if "high" in ranked else ("watch" if "watch" in ranked else "ok")

        assumptions = [
            "Pressures and temperatures are taken as supplied; they must come from a validated NeqSim pipeline model.",
            "Hydrate margin = fluid temperature - hydrate equilibrium temperature at the local pressure.",
            f"Screening guideline: margin <= 0 C is 'high' (hydrate region), margin < {min_margin:g} C is 'watch'.",
            "Station spacing limits the resolution of section start and end KPs.",
            "Steady state only; shut-in cooldown, restart and transient behaviour are not covered.",
        ]
        if margin is None:
            assumptions.append("No hydrate temperatures supplied; margin_warning is 'unknown'.")

        return ProfileScreeningResult(
            station_count=len(self.kp_km),
            length_km=round(self.length_km, 4),
            inlet_pressure_bara=round(self.pressure_bara[0], 3),
            arrival_pressure_bara=round(self.pressure_bara[-1], 3),
            inlet_temperature_c=round(self.temperature_c[0], 3),
            arrival_temperature_c=round(self.temperature_c[-1], 3),
            min_temperature_c=round(min(self.temperature_c), 3),
            min_hydrate_margin_c=min_m,
            min_margin_kp_km=min_kp,
            first_watch_kp_km=first_watch,
            first_hydrate_kp_km=first_hyd,
            hydrate_sections=tuple(hyd_sections),
            watch_sections=tuple(watch_sections),
            margin_warning=warning,
            neqsim_available=find_spec("neqsim") is not None,
            assumptions=tuple(assumptions),
        )


def margin_status(margin: float | None, min_margin: float = 3.0) -> str:
    """``high`` (<= 0), ``watch`` (< min_margin), ``ok`` or ``unknown``."""
    if margin is None or not isfinite(margin):
        return "unknown"
    if margin <= 0.0:
        return "high"
    return "watch" if margin < min_margin else "ok"


def _sections(kp: Sequence[float], margin: Sequence[float], statuses: Sequence[str], wanted: set[str]) -> list[Section]:
    out: list[Section] = []
    start = None
    worst = None
    for i, status in enumerate(statuses):
        if status in wanted:
            if start is None:
                start = i
                worst = margin[i]
            else:
                worst = min(worst, margin[i])  # type: ignore[type-var]
        elif start is not None:
            out.append(Section(_label(statuses[start:i]), kp[start], kp[i - 1], round(worst, 3)))  # type: ignore[arg-type]
            start = None
    if start is not None:
        out.append(Section(_label(statuses[start:]), kp[start], kp[-1], round(worst, 3)))  # type: ignore[arg-type]
    return out


def _label(statuses: Sequence[str]) -> str:
    return "high" if "high" in statuses else "watch"
