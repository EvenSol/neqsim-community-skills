"""Norwegian Offshore Directorate (Sodir) FactMaps access and normalization.

FactMaps is published under the Norwegian Licence for Open Government Data
(NLOD 2.0). The REST API is an ArcGIS MapServer that supports ``f=geojson``
queries with ``outSR=4326``. Layer ids below are for the WGS84 service:

* 304 Facilities, in place      (points)
* 307 All facilities            (points)
* 311 Pipelines                 (polylines, main pipelines only)
* 502 Field by status           (polygons)
* 503 Discovery, active         (polygons)
* 201 Wellbores, all            (points)

Network access is opt-in: :func:`fetch_layer` performs HTTP only when called,
and every function accepts a ``fetcher`` callable so tests and offline users can
inject already-downloaded GeoJSON. The ``normalize_*`` functions are pure and
work on any parsed GeoJSON ``FeatureCollection`` with Sodir attribute names.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .geometry import LonLat, validate_lonlat

FACTMAPS_WGS84_URL = (
    "https://factmaps.sodir.no/api/rest/services/Factmaps/FactMapsWGS84/MapServer"
)

LAYERS: dict[str, int] = {
    "facilities_in_place": 304,
    "facilities_all": 307,
    "pipelines": 311,
    "fields": 502,
    "discoveries_active": 503,
    "wellbores_all": 201,
}

SODIR_ATTRIBUTION = (
    "Facilities, pipelines and fields: Norwegian Offshore Directorate (Sodir) "
    "FactMaps, NLOD 2.0"
)

Fetcher = Callable[[str], Mapping[str, Any]]


@dataclass(frozen=True)
class Facility:
    name: str
    lon: float
    lat: float
    kind: str
    phase: str
    water_depth_m: float | None
    belongs_to: str
    operator: str
    functions: str
    fact_page_url: str
    properties: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)


@dataclass(frozen=True)
class Pipeline:
    name: str
    paths: tuple[tuple[LonLat, ...], ...]
    from_facility: str
    to_facility: str
    medium: str
    diameter_inch: float | None
    max_water_depth_m: float | None
    phase: str
    operator: str
    fact_page_url: str
    properties: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)


@dataclass(frozen=True)
class FieldArea:
    name: str
    rings: tuple[tuple[LonLat, ...], ...]
    status: str
    hc_type: str
    operator: str
    main_area: str
    fact_page_url: str
    properties: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)


@dataclass
class NormalizeReport:
    """Items skipped while normalizing, so a partial layer is still usable."""

    skipped: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- URLs


def layer_id(layer: int | str) -> int:
    """Resolve a layer alias from :data:`LAYERS` or pass an integer id through."""
    if isinstance(layer, bool):
        raise ValueError("layer must be an int id or a known alias")
    if isinstance(layer, int):
        return layer
    if isinstance(layer, str) and layer.isdigit():
        return int(layer)
    try:
        return LAYERS[layer]
    except KeyError as exc:
        raise ValueError(f"unknown Sodir layer alias {layer!r}; known: {sorted(LAYERS)}") from exc


def build_query_url(
    layer: int | str,
    *,
    where: str = "1=1",
    out_fields: str | Iterable[str] = "*",
    bbox: tuple[float, float, float, float] | None = None,
    result_offset: int = 0,
    record_count: int = 1000,
    base_url: str = FACTMAPS_WGS84_URL,
) -> str:
    """Build a FactMaps ``query`` URL that returns GeoJSON in WGS84.

    ``bbox`` is ``(min_lon, min_lat, max_lon, max_lat)`` and selects features
    intersecting that envelope.
    """
    if record_count <= 0 or record_count > 1000:
        raise ValueError("record_count must be in 1..1000 (FactMaps maxRecordCount)")
    if result_offset < 0:
        raise ValueError("result_offset must be non-negative")
    fields = out_fields if isinstance(out_fields, str) else ",".join(out_fields)
    params: dict[str, Any] = {
        "where": where,
        "outFields": fields,
        "returnGeometry": "true",
        "outSR": 4326,
        "f": "geojson",
        "resultOffset": result_offset,
        "resultRecordCount": record_count,
    }
    if bbox is not None:
        min_lon, min_lat, max_lon, max_lat = (float(v) for v in bbox)
        if min_lon >= max_lon or min_lat >= max_lat:
            raise ValueError("bbox must be (min_lon, min_lat, max_lon, max_lat)")
        params.update(
            {
                "geometry": f"{min_lon},{min_lat},{max_lon},{max_lat}",
                "geometryType": "esriGeometryEnvelope",
                "inSR": 4326,
                "spatialRel": "esriSpatialRelIntersects",
            }
        )
    return f"{base_url.rstrip('/')}/{layer_id(layer)}/query?{urlencode(params)}"


def default_fetcher(url: str, timeout: float = 30.0) -> Mapping[str, Any]:
    """GET a URL and parse JSON. Only called when the user opts into network use."""
    request = Request(url, headers={"User-Agent": "neqsim-community-skills/offshore-field-map"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_layer(
    layer: int | str,
    *,
    where: str = "1=1",
    bbox: tuple[float, float, float, float] | None = None,
    out_fields: str | Iterable[str] = "*",
    page_size: int = 1000,
    max_pages: int = 20,
    fetcher: Fetcher | None = None,
) -> dict[str, Any]:
    """Download a whole FactMaps layer (paged) as one GeoJSON FeatureCollection."""
    get = fetcher or default_fetcher
    features: list[Any] = []
    for page in range(max_pages):
        url = build_query_url(
            layer,
            where=where,
            out_fields=out_fields,
            bbox=bbox,
            result_offset=page * page_size,
            record_count=page_size,
        )
        payload = get(url)
        if "error" in payload:
            raise RuntimeError(f"FactMaps query failed: {payload['error']}")
        batch = list(payload.get("features") or [])
        features.extend(batch)
        exceeded = bool(
            payload.get("exceededTransferLimit")
            or (payload.get("properties") or {}).get("exceededTransferLimit")
        )
        if not exceeded and len(batch) < page_size:
            break
    return {"type": "FeatureCollection", "features": features}


# ------------------------------------------------------------------ normalizing


def _features(collection: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if not isinstance(collection, Mapping) or collection.get("type") != "FeatureCollection":
        raise ValueError("expected a parsed GeoJSON FeatureCollection")
    return list(collection.get("features") or [])


def _text(props: Mapping[str, Any], key: str) -> str:
    value = props.get(key)
    return "" if value is None else str(value).strip()


def _number(props: Mapping[str, Any], key: str) -> float | None:
    value = props.get(key)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _lines(geometry: Mapping[str, Any]) -> tuple[tuple[LonLat, ...], ...]:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if gtype == "LineString":
        parts = [coords]
    elif gtype == "MultiLineString":
        parts = coords
    else:
        raise ValueError(f"unsupported pipeline geometry {gtype!r}")
    out = []
    for part in parts:
        pts = tuple(validate_lonlat(c[0], c[1]) for c in part)
        if len(pts) >= 2:
            out.append(pts)
    if not out:
        raise ValueError("pipeline has no usable line parts")
    return tuple(out)


def _rings(geometry: Mapping[str, Any]) -> tuple[tuple[LonLat, ...], ...]:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if gtype == "Polygon":
        polys = [coords]
    elif gtype == "MultiPolygon":
        polys = coords
    else:
        raise ValueError(f"unsupported field geometry {gtype!r}")
    out = []
    for poly in polys:
        if poly:
            outer = tuple(validate_lonlat(c[0], c[1]) for c in poly[0])
            if len(outer) >= 3:
                out.append(outer)
    if not out:
        raise ValueError("field polygon has no usable rings")
    return tuple(out)


def normalize_facilities(
    collection: Mapping[str, Any], report: NormalizeReport | None = None
) -> list[Facility]:
    """Turn a Sodir facility layer (304/307) GeoJSON into :class:`Facility` items."""
    out: list[Facility] = []
    for feature in _features(collection):
        props = feature.get("properties") or {}
        name = _text(props, "fclName") or _text(props, "name")
        try:
            geometry = feature.get("geometry") or {}
            if geometry.get("type") != "Point":
                raise ValueError(f"expected Point, got {geometry.get('type')!r}")
            lon, lat = validate_lonlat(*geometry["coordinates"][:2])
            if not name:
                raise ValueError("missing facility name")
        except (KeyError, TypeError, ValueError) as exc:
            if report is not None:
                report.skipped.append(f"facility {name or '?'}: {exc}")
            continue
        out.append(
            Facility(
                name=name,
                lon=lon,
                lat=lat,
                kind=_text(props, "fclKind"),
                phase=_text(props, "fclPhase"),
                water_depth_m=_number(props, "fclWaterDepth"),
                belongs_to=_text(props, "fclBelongsToName"),
                operator=_text(props, "fclCurrentOperatorName"),
                functions=_text(props, "fclFunctions"),
                fact_page_url=_text(props, "fclFactPageUrl"),
                properties=dict(props),
            )
        )
    return out


def normalize_pipelines(
    collection: Mapping[str, Any], report: NormalizeReport | None = None
) -> list[Pipeline]:
    """Turn the Sodir pipeline layer (311) GeoJSON into :class:`Pipeline` items."""
    out: list[Pipeline] = []
    for feature in _features(collection):
        props = feature.get("properties") or {}
        name = _text(props, "pplName") or _text(props, "name")
        try:
            paths = _lines(feature.get("geometry") or {})
            if not name:
                raise ValueError("missing pipeline name")
        except (KeyError, TypeError, ValueError) as exc:
            if report is not None:
                report.skipped.append(f"pipeline {name or '?'}: {exc}")
            continue
        out.append(
            Pipeline(
                name=name,
                paths=paths,
                from_facility=_text(props, "fclNameFrom"),
                to_facility=_text(props, "fclNameTo"),
                medium=_text(props, "pplMedium"),
                diameter_inch=_number(props, "pplDimension"),
                max_water_depth_m=_number(props, "pplWaterDepth"),
                phase=_text(props, "pplCurrentPhase"),
                operator=_text(props, "cmpLongName"),
                fact_page_url=_text(props, "pplFactPageUrl"),
                properties=dict(props),
            )
        )
    return out


def normalize_fields(
    collection: Mapping[str, Any], report: NormalizeReport | None = None
) -> list[FieldArea]:
    """Turn the Sodir field layer (502) GeoJSON into :class:`FieldArea` items."""
    out: list[FieldArea] = []
    for feature in _features(collection):
        props = feature.get("properties") or {}
        name = _text(props, "fldName") or _text(props, "name")
        try:
            rings = _rings(feature.get("geometry") or {})
            if not name:
                raise ValueError("missing field name")
        except (KeyError, TypeError, ValueError) as exc:
            if report is not None:
                report.skipped.append(f"field {name or '?'}: {exc}")
            continue
        out.append(
            FieldArea(
                name=name,
                rings=rings,
                # The source attribute name really is spelled "Satus".
                status=_text(props, "fldCurrentActivitySatus"),
                hc_type=_text(props, "fldHcType"),
                operator=_text(props, "cmpLongName"),
                main_area=_text(props, "fldMainArea"),
                fact_page_url=_text(props, "fldFactPageUrl"),
                properties=dict(props),
            )
        )
    return out


def facilities_by_name(facilities: Iterable[Facility]) -> dict[str, Facility]:
    """Index facilities by upper-case name for tie-in lookups (e.g. ``"TROLL A"``)."""
    return {f.name.upper(): f for f in facilities}
