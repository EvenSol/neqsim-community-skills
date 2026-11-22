"""EMODnet Bathymetry access: WMS overlay description and depth sampling.

EMODnet Bathymetry data products are owned by the EU and licensed CC BY 4.0.
Two services are used:

* WMS ``https://ows.emodnet-bathymetry.eu/wms`` for a map overlay
  (layers such as ``emodnet:mean_multicolour``, ``emodnet:mean_atlas_land``,
  ``emodnet:contours``).
* REST ``https://rest.emodnet-bathymetry.eu`` for depth sampling
  (``depth_sample?geom=POINT(lon lat)`` returns a JSON object with ``avg``;
  ``depth_profile?geom=LINESTRING(...)`` returns a JSON list of values).
  Both return elevations, negative below sea level; this module converts them
  to water depth, positive downwards, which is the convention used by the
  NeqSim community subsea skills.

Network access is opt-in and injectable through ``fetcher``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Any
from urllib.parse import quote

from .geometry import LonLat, cumulative_distance_m, normalize_polyline, point_at_distance

EMODNET_WMS_URL = "https://ows.emodnet-bathymetry.eu/wms"
EMODNET_REST_URL = "https://rest.emodnet-bathymetry.eu"
EMODNET_ATTRIBUTION = "Bathymetry: EMODnet Bathymetry Consortium (EU), CC BY 4.0"

WMS_LAYERS: dict[str, str] = {
    "multicolour": "emodnet:mean_multicolour",
    "rainbow": "emodnet:mean_rainbowcolour",
    "atlas_land": "emodnet:mean_atlas_land",
    "contours": "emodnet:contours",
}

Fetcher = Callable[[str], Any]


@dataclass(frozen=True)
class WmsOverlay:
    """Everything a web map needs to draw the EMODnet bathymetry overlay."""

    url: str
    layers: str
    name: str
    attribution: str
    fmt: str = "image/png"
    transparent: bool = True
    opacity: float = 0.6


@dataclass(frozen=True)
class DepthSample:
    distance_m: float
    lon: float
    lat: float
    depth_m: float


def wms_overlay(style: str = "multicolour", opacity: float = 0.6) -> WmsOverlay:
    """Return the WMS overlay spec for an EMODnet mean-depth style or contours."""
    if style not in WMS_LAYERS:
        raise ValueError(f"unknown EMODnet style {style!r}; known: {sorted(WMS_LAYERS)}")
    if not 0.0 <= opacity <= 1.0:
        raise ValueError("opacity must be within [0, 1]")
    return WmsOverlay(
        url=EMODNET_WMS_URL,
        layers=WMS_LAYERS[style],
        name=f"EMODnet bathymetry ({style})",
        attribution=EMODNET_ATTRIBUTION,
        opacity=opacity,
    )


def _wkt_linestring(coords: Sequence[LonLat]) -> str:
    return "LINESTRING(" + ",".join(f"{lon:.6f} {lat:.6f}" for lon, lat in coords) + ")"


def depth_sample_url(lon: float, lat: float) -> str:
    return f"{EMODNET_REST_URL}/depth_sample?geom={quote(f'POINT({lon:.6f} {lat:.6f})')}"


def depth_profile_url(coords: Sequence[Sequence[float]]) -> str:
    line = normalize_polyline(coords)
    return f"{EMODNET_REST_URL}/depth_profile?geom={quote(_wkt_linestring(line))}"


def elevation_to_depth(value: Any) -> float | None:
    """EMODnet elevation (negative below sea level) to water depth (positive down).

    Returns ``None`` for missing or non-finite values; land (positive
    elevation) is returned as a depth of 0.
    """
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(number):
        return None
    return max(0.0, -number)


def parse_depth_profile(values: Sequence[Any], coords: Sequence[Sequence[float]]) -> list[DepthSample]:
    """Spread an EMODnet ``depth_profile`` list evenly along the route.

    The REST service samples the line at equal spacing, so sample ``i`` of
    ``n`` sits at distance ``i / (n - 1) * route_length``. Missing samples are
    dropped. This is a screening assumption: resample with your own survey
    data before any design use.
    """
    line = normalize_polyline(coords)
    total = cumulative_distance_m(line)[-1]
    vals = list(values)
    if len(vals) < 2:
        raise ValueError("depth profile needs at least two samples")
    out: list[DepthSample] = []
    for i, value in enumerate(vals):
        depth = elevation_to_depth(value)
        if depth is None:
            continue
        dist = total * i / (len(vals) - 1)
        lon, lat = point_at_distance(line, dist)
        out.append(DepthSample(distance_m=dist, lon=lon, lat=lat, depth_m=depth))
    if len(out) < 2:
        raise ValueError("depth profile has fewer than two valid samples")
    return out


def sample_point_depth(lon: float, lat: float, fetcher: Fetcher | None = None) -> float | None:
    """Water depth (m, positive down) at a point from EMODnet ``depth_sample``."""
    from .sodir import default_fetcher

    payload = (fetcher or default_fetcher)(depth_sample_url(lon, lat))
    if not isinstance(payload, dict):
        return None
    return elevation_to_depth(payload.get("avg"))


def sample_route_depths(
    coords: Sequence[Sequence[float]], fetcher: Fetcher | None = None
) -> list[DepthSample]:
    """Sample the EMODnet depth profile along a route (opt-in network call)."""
    from .sodir import default_fetcher

    payload = (fetcher or default_fetcher)(depth_profile_url(coords))
    if not isinstance(payload, (list, tuple)):
        raise ValueError("unexpected EMODnet depth_profile response")
    return parse_depth_profile(payload, coords)
