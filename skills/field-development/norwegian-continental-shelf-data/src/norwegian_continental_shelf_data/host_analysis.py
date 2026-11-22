"""Tie-in host screening from Sodir production and discovery data.

Turns monthly saleable-production rows (:class:`~.sodir_api.ProductionRecord`)
into daily rates, producing GOR and water-cut trends, and a historic-peak
"ullage" proxy for a host field, and ranks nearby discoveries as tie-in
candidates by great-circle distance. Everything is deterministic and works
offline on rows you already hold. :func:`host_context` is the one helper that
calls the live :class:`~.sodir_api.SodirDataService`.

These are screening indicators from public reported volumes. They are not
nameplate capacities, well-test GORs or PVT data, and they must be confirmed
against the host operator's design basis and a validated NeqSim process model.
"""

from __future__ import annotations

import calendar
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from .sodir_api import (
    SODIR_ATTRIBUTION,
    Discovery,
    Facility,
    ProductionRecord,
    SodirDataService,
)

EARTH_RADIUS_KM = 6371.0088
MILL = 1.0e6
BILL = 1.0e9


# --------------------------------------------------------------------------- #
# Rates and ratios
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class MonthlyRates:
    """Average daily rates and ratios for one month.

    Rates are Sm3/d. ``gor_sm3_sm3`` is gas / (oil + condensate) on the chosen
    basis (``net`` saleable or ``gross``). ``water_cut`` is water / (water +
    oil + condensate) and is ``None`` when Sodir does not publish water.
    """

    year: int
    month: int
    days: int
    oil_sm3_d: float
    condensate_sm3_d: float
    gas_sm3_d: float
    water_sm3_d: float | None
    liquid_sm3_d: float | None
    oe_sm3_d: float
    gor_sm3_sm3: float | None
    water_cut: float | None

    @property
    def label(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


def days_in_month(year: int, month: int) -> int:
    if not 1 <= month <= 12:
        raise ValueError(f"month must be 1-12, got {month}")
    return calendar.monthrange(year, month)[1]


def monthly_rates(
    records: Iterable[ProductionRecord], *, basis: str = "net"
) -> list[MonthlyRates]:
    """Convert monthly volume rows to average daily rates and ratios.

    ``basis="net"`` uses saleable volumes (gas net of fuel, flare and
    injection, so GOR is a *sales* GOR). ``basis="gross"`` uses Sodir's gross
    volumes, which for gas is closer to produced gas; gross falls back to net
    where gross is not published. Yearly rows (``month == 0``) are skipped.
    """
    if basis not in {"net", "gross"}:
        raise ValueError("basis must be 'net' or 'gross'")
    out: list[MonthlyRates] = []
    for rec in sorted(records, key=lambda r: (r.year, r.month)):
        if not rec.is_monthly:
            continue
        days = days_in_month(rec.year, rec.month)
        if basis == "gross":
            oil = rec.oil_gross if rec.oil_gross is not None else rec.oil_net
            gas = rec.gas_gross if rec.gas_gross is not None else rec.gas_net
            cond = (
                rec.condensate_gross
                if rec.condensate_gross is not None
                else rec.condensate_net
            )
            oe = rec.oe_gross if rec.oe_gross is not None else rec.oe_net
        else:
            oil, gas, cond, oe = rec.oil_net, rec.gas_net, rec.condensate_net, rec.oe_net
        oil_d = oil * MILL / days
        cond_d = cond * MILL / days
        gas_d = gas * BILL / days
        water_d = None if rec.water_mill_sm3 is None else rec.water_mill_sm3 * MILL / days
        hc_liq = oil_d + cond_d
        gor = gas_d / hc_liq if hc_liq > 0 else None
        liquid = None if water_d is None else hc_liq + water_d
        wc = (water_d / liquid) if (water_d is not None and liquid and liquid > 0) else None
        out.append(
            MonthlyRates(
                year=rec.year,
                month=rec.month,
                days=days,
                oil_sm3_d=round(oil_d, 3),
                condensate_sm3_d=round(cond_d, 3),
                gas_sm3_d=round(gas_d, 1),
                water_sm3_d=None if water_d is None else round(water_d, 3),
                liquid_sm3_d=None if liquid is None else round(liquid, 3),
                oe_sm3_d=round(oe * MILL / days, 3),
                gor_sm3_sm3=None if gor is None else round(gor, 2),
                water_cut=None if wc is None else round(wc, 4),
            )
        )
    return out


@dataclass(frozen=True)
class RatioTrend:
    """Recent-window versus previous-window trend of GOR and water cut."""

    window_months: int
    latest_month: str
    recent_mean_gor: float | None
    previous_mean_gor: float | None
    gor_change_fraction: float | None
    recent_mean_water_cut: float | None
    previous_mean_water_cut: float | None
    water_cut_change: float | None
    recent_mean_oil_sm3_d: float
    recent_mean_gas_sm3_d: float
    warnings: tuple[str, ...] = ()


def _mean(values: Sequence[float | None]) -> float | None:
    clean = [v for v in values if v is not None]
    return sum(clean) / len(clean) if clean else None


def ratio_trend(rates: Sequence[MonthlyRates], *, window_months: int = 12) -> RatioTrend:
    """Compare the latest ``window_months`` with the window before it.

    Months with zero hydrocarbon liquid (shut-in or gas-only) carry no GOR and
    are ignored in the GOR means. Water-cut fields are ``None`` when the field
    has no published produced-water volumes.
    """
    if window_months <= 0:
        raise ValueError("window_months must be positive")
    if not rates:
        raise ValueError("no monthly rates supplied")
    ordered = sorted(rates, key=lambda r: (r.year, r.month))
    recent = ordered[-window_months:]
    previous = ordered[-2 * window_months : -window_months]
    warnings: list[str] = []
    if len(recent) < window_months:
        warnings.append(f"only {len(recent)} months available for the recent window")
    if not previous:
        warnings.append("no previous window; trend changes not computed")
    r_gor = _mean([r.gor_sm3_sm3 for r in recent])
    p_gor = _mean([r.gor_sm3_sm3 for r in previous])
    r_wc = _mean([r.water_cut for r in recent])
    p_wc = _mean([r.water_cut for r in previous])
    if r_wc is None:
        warnings.append("produced water not published for this field; water cut unavailable")
    gor_change = (r_gor - p_gor) / p_gor if (r_gor is not None and p_gor) else None
    wc_change = (r_wc - p_wc) if (r_wc is not None and p_wc is not None) else None
    return RatioTrend(
        window_months=window_months,
        latest_month=ordered[-1].label,
        recent_mean_gor=None if r_gor is None else round(r_gor, 2),
        previous_mean_gor=None if p_gor is None else round(p_gor, 2),
        gor_change_fraction=None if gor_change is None else round(gor_change, 4),
        recent_mean_water_cut=None if r_wc is None else round(r_wc, 4),
        previous_mean_water_cut=None if p_wc is None else round(p_wc, 4),
        water_cut_change=None if wc_change is None else round(wc_change, 4),
        recent_mean_oil_sm3_d=round(_mean([r.oil_sm3_d for r in recent]) or 0.0, 2),
        recent_mean_gas_sm3_d=round(_mean([r.gas_sm3_d for r in recent]) or 0.0, 1),
        warnings=tuple(warnings),
    )


@dataclass(frozen=True)
class StreamUllage:
    stream: str
    unit: str
    historic_peak: float
    peak_month: str
    recent_mean: float
    indicative_ullage: float
    utilisation_of_peak: float | None


@dataclass(frozen=True)
class UllageIndicator:
    """Historic-peak ullage proxy per stream for a host field."""

    window_months: int
    streams: tuple[StreamUllage, ...]
    caveat: str = (
        "Historic peak monthly-average rate is a proxy, not nameplate capacity. "
        "It understates capacity never demonstrated and overstates capacity lost "
        "to debottlenecking reversals, equipment degradation or changed fluid "
        "(GOR/water cut). Confirm against the host design basis and a NeqSim model."
    )

    def stream(self, name: str) -> StreamUllage:
        for s in self.streams:
            if s.stream == name:
                return s
        raise KeyError(name)


def ullage_indicator(
    rates: Sequence[MonthlyRates], *, window_months: int = 12
) -> UllageIndicator:
    """Indicative spare capacity: historic peak minus recent mean, per stream.

    Streams: oil (Sm3/d), gas (Sm3/d), water (Sm3/d, if published), total
    liquid (Sm3/d, if water published) and o.e. (Sm3 o.e./d).
    """
    if window_months <= 0:
        raise ValueError("window_months must be positive")
    if not rates:
        raise ValueError("no monthly rates supplied")
    ordered = sorted(rates, key=lambda r: (r.year, r.month))
    recent = ordered[-window_months:]

    def build(name: str, unit: str, getter) -> StreamUllage | None:
        series = [(getter(r), r.label) for r in ordered if getter(r) is not None]
        if not series:
            return None
        peak, peak_label = max(series, key=lambda x: x[0])
        recent_vals = [getter(r) for r in recent if getter(r) is not None]
        recent_mean = sum(recent_vals) / len(recent_vals) if recent_vals else 0.0
        util = recent_mean / peak if peak > 0 else None
        return StreamUllage(
            stream=name,
            unit=unit,
            historic_peak=round(peak, 2),
            peak_month=peak_label,
            recent_mean=round(recent_mean, 2),
            indicative_ullage=round(max(peak - recent_mean, 0.0), 2),
            utilisation_of_peak=None if util is None else round(util, 4),
        )

    candidates = (
        build("oil", "Sm3/d", lambda r: r.oil_sm3_d),
        build("gas", "Sm3/d", lambda r: r.gas_sm3_d),
        build("water", "Sm3/d", lambda r: r.water_sm3_d),
        build("liquid", "Sm3/d", lambda r: r.liquid_sm3_d),
        build("oe", "Sm3 o.e./d", lambda r: r.oe_sm3_d),
    )
    return UllageIndicator(
        window_months=window_months,
        streams=tuple(s for s in candidates if s is not None),
    )


# --------------------------------------------------------------------------- #
# Nearby discoveries
# --------------------------------------------------------------------------- #


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km (spherical Earth, screening accuracy)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


@dataclass(frozen=True)
class TieInCandidate:
    discovery: Discovery
    distance_km: float

    @property
    def name(self) -> str:
        return self.discovery.name

    @property
    def recoverable_oe_mill_sm3(self) -> float | None:
        res = self.discovery.resources
        return None if res is None else res.oe_mill_sm3


def nearby_discoveries(
    host_latitude: float,
    host_longitude: float,
    discoveries: Iterable[Discovery],
    *,
    radius_km: float = 50.0,
    exclude_in_field: bool = True,
    statuses: Sequence[str] | None = None,
    hc_types: Sequence[str] | None = None,
) -> list[TieInCandidate]:
    """Discoveries within ``radius_km`` of the host, nearest first.

    ``exclude_in_field`` drops discoveries already assigned to a field
    (``fldName`` set), which leaves undeveloped tie-in candidates. ``statuses``
    and ``hc_types`` are optional case-insensitive substring filters on the
    Sodir activity status and hydrocarbon type. Distances use polygon vertex
    centroids and a spherical Earth: adequate for ranking, not for routing.
    """
    if radius_km <= 0:
        raise ValueError("radius_km must be positive")
    if not (-90.0 <= host_latitude <= 90.0 and -180.0 <= host_longitude <= 180.0):
        raise ValueError("host coordinates must be WGS84 decimal degrees")
    status_keys = [s.lower() for s in statuses] if statuses else None
    hc_keys = [h.lower() for h in hc_types] if hc_types else None
    out: list[TieInCandidate] = []
    for disc in discoveries:
        if disc.latitude is None or disc.longitude is None:
            continue
        if exclude_in_field and disc.field_name:
            continue
        if status_keys and not any(k in disc.status.lower() for k in status_keys):
            continue
        if hc_keys and not any(k in disc.hc_type.lower() for k in hc_keys):
            continue
        dist = haversine_km(host_latitude, host_longitude, disc.latitude, disc.longitude)
        if dist <= radius_km:
            out.append(TieInCandidate(discovery=disc, distance_km=round(dist, 2)))
    out.sort(key=lambda c: c.distance_km)
    return out


# --------------------------------------------------------------------------- #
# One-call live host context
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class HostContext:
    """Public host-field context for a tie-in screening."""

    field_name: str
    overview: dict
    facilities: tuple[Facility, ...]
    host_latitude: float | None
    host_longitude: float | None
    monthly: tuple[MonthlyRates, ...]
    trend: RatioTrend | None
    ullage: UllageIndicator | None
    candidates: tuple[TieInCandidate, ...]
    attribution: str = SODIR_ATTRIBUTION
    warnings: tuple[str, ...] = field(default=())


def pick_host_location(facilities: Sequence[Facility]) -> tuple[float, float] | None:
    """Pick a representative host location: a fixed, in-service surface facility first."""

    def rank(f: Facility) -> tuple[int, int]:
        fixed = 0 if f.fixed_or_moveable.lower().startswith("fixed") else 1
        in_service = 0 if "service" in f.phase.lower() else 1
        return (in_service, fixed)

    located = [f for f in facilities if f.latitude is not None and f.longitude is not None]
    if not located:
        return None
    best = min(located, key=rank)
    return best.latitude, best.longitude  # type: ignore[return-value]


def host_context(
    field_name: str,
    *,
    service: SodirDataService | None = None,
    radius_km: float = 50.0,
    window_months: int = 12,
    basis: str = "net",
    host_latitude: float | None = None,
    host_longitude: float | None = None,
    discovery_statuses: Sequence[str] | None = None,
) -> HostContext:
    """Fetch and assemble the public context for a host field (live network).

    Pulls the field overview, its facilities, monthly saleable production and
    all discoveries from the Sodir DataService, then computes rates, GOR and
    water-cut trends, the ullage proxy and nearby tie-in candidates. Supply
    ``host_latitude``/``host_longitude`` to override the facility location.
    """
    svc = service or SodirDataService()
    warnings: list[str] = []
    overview = svc.field_overview(field_name)
    canonical = str(overview.get("fldName") or field_name)
    facilities = tuple(svc.facilities(belongs_to=canonical))
    if host_latitude is not None and host_longitude is not None:
        location: tuple[float, float] | None = (host_latitude, host_longitude)
    else:
        location = pick_host_location(facilities)
        if location is None:
            warnings.append("no facility coordinates found; nearby discoveries skipped")
    records = svc.field_production(canonical, period="month")
    rates = monthly_rates(records, basis=basis)
    trend = ratio_trend(rates, window_months=window_months) if rates else None
    ullage = ullage_indicator(rates, window_months=window_months) if rates else None
    if not rates:
        warnings.append("no monthly production published for this field")
    if trend:
        warnings.extend(trend.warnings)
    candidates: tuple[TieInCandidate, ...] = ()
    if location is not None:
        candidates = tuple(
            nearby_discoveries(
                location[0],
                location[1],
                svc.discoveries(),
                radius_km=radius_km,
                statuses=discovery_statuses,
            )
        )
    return HostContext(
        field_name=canonical,
        overview=overview,
        facilities=facilities,
        host_latitude=None if location is None else location[0],
        host_longitude=None if location is None else location[1],
        monthly=tuple(rates),
        trend=trend,
        ullage=ullage,
        candidates=candidates,
        warnings=tuple(warnings),
    )
