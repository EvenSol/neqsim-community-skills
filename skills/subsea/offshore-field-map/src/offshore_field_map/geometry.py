"""Small, dependency-free geodesy helpers for longitude/latitude polylines.

All coordinates are ``(longitude, latitude)`` in decimal degrees (WGS84 /
EPSG:4326), matching the GeoJSON axis order (RFC 7946). Distances use the
haversine great-circle relation on a spherical Earth, which is adequate for
screening-level route lengths (error well below 0.5 % on the NCS).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from math import asin, cos, isfinite, radians, sin, sqrt

EARTH_RADIUS_M = 6_371_000.0

LonLat = tuple[float, float]


def validate_lonlat(lon: float, lat: float) -> LonLat:
    """Return ``(lon, lat)`` as floats or raise ``ValueError`` when out of range."""
    try:
        lon_f = float(lon)
        lat_f = float(lat)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"coordinate is not numeric: {(lon, lat)!r}") from exc
    if not (isfinite(lon_f) and isfinite(lat_f)):
        raise ValueError(f"coordinate is not finite: {(lon, lat)!r}")
    if not -180.0 <= lon_f <= 180.0:
        raise ValueError(f"longitude {lon_f} outside [-180, 180]")
    if not -90.0 <= lat_f <= 90.0:
        raise ValueError(f"latitude {lat_f} outside [-90, 90]")
    return lon_f, lat_f


def haversine_m(a: LonLat, b: LonLat) -> float:
    """Great-circle distance in metres between two ``(lon, lat)`` points."""
    lon1, lat1 = a
    lon2, lat2 = b
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = phi2 - phi1
    dlmb = radians(lon2 - lon1)
    h = sin(dphi / 2.0) ** 2 + cos(phi1) * cos(phi2) * sin(dlmb / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_M * asin(min(1.0, sqrt(h)))


def normalize_polyline(coords: Iterable[Sequence[float]]) -> list[LonLat]:
    """Validate a polyline and return it as a list of ``(lon, lat)`` tuples."""
    points = [validate_lonlat(c[0], c[1]) for c in coords]
    if len(points) < 2:
        raise ValueError("a polyline needs at least two coordinates")
    return points


def cumulative_distance_m(coords: Sequence[LonLat]) -> list[float]:
    """Cumulative along-line distance in metres at each vertex (first is 0)."""
    out = [0.0]
    for i in range(1, len(coords)):
        out.append(out[-1] + haversine_m(coords[i - 1], coords[i]))
    return out


def polyline_length_m(coords: Sequence[LonLat]) -> float:
    """Total great-circle length of a polyline in metres."""
    return cumulative_distance_m(coords)[-1]


def point_at_distance(coords: Sequence[LonLat], distance_m: float) -> LonLat:
    """Linearly interpolate the ``(lon, lat)`` position at an along-line distance.

    Distances outside ``[0, length]`` are clamped to the end points. Linear
    interpolation in lon/lat is adequate for the short segments of a route.
    """
    cum = cumulative_distance_m(coords)
    if distance_m <= 0.0:
        return coords[0]
    if distance_m >= cum[-1]:
        return coords[-1]
    for i in range(1, len(cum)):
        if distance_m <= cum[i]:
            span = cum[i] - cum[i - 1]
            frac = 0.0 if span == 0.0 else (distance_m - cum[i - 1]) / span
            lon = coords[i - 1][0] + frac * (coords[i][0] - coords[i - 1][0])
            lat = coords[i - 1][1] + frac * (coords[i][1] - coords[i - 1][1])
            return lon, lat
    return coords[-1]


def bbox(points: Iterable[LonLat], margin_deg: float = 0.0) -> tuple[float, float, float, float]:
    """Return ``(min_lon, min_lat, max_lon, max_lat)`` with an optional margin."""
    pts = list(points)
    if not pts:
        raise ValueError("cannot compute a bounding box of no points")
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    return (
        max(-180.0, min(lons) - margin_deg),
        max(-90.0, min(lats) - margin_deg),
        min(180.0, max(lons) + margin_deg),
        min(90.0, max(lats) + margin_deg),
    )


def bbox_around(points: Iterable[LonLat], margin_km: float = 10.0) -> tuple[float, float, float, float]:
    """Bounding box around points expanded by ``margin_km`` in every direction."""
    pts = list(points)
    if margin_km < 0.0:
        raise ValueError("margin_km must be non-negative")
    min_lon, min_lat, max_lon, max_lat = bbox(pts)
    mid_lat = radians((min_lat + max_lat) / 2.0)
    dlat = margin_km / 111.32
    dlon = margin_km / max(1e-6, 111.32 * cos(mid_lat))
    return (
        max(-180.0, min_lon - dlon),
        max(-90.0, min_lat - dlat),
        min(180.0, max_lon + dlon),
        min(90.0, max_lat + dlat),
    )
