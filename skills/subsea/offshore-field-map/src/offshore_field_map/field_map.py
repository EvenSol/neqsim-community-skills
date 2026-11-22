"""Layered offshore field map: data model plus folium and matplotlib renderers.

The :class:`FieldMapBuilder` collects layers (Sodir fields, pipelines and
facilities, user nodes such as new wells or templates, and candidate tie-in
routes) as plain data. It can then:

* export everything as one GeoJSON ``FeatureCollection`` (no dependencies),
* render an interactive Leaflet map through ``folium`` with an optional
  EMODnet bathymetry WMS overlay, or
* draw a static planform on a ``matplotlib`` axes for reports.

Routes can carry one value per vertex (for example hydrate margin in C from a
NeqSim pipeline run). Segments are then coloured ``ok``/``watch``/``high``
using the same thresholds as the ``neqsim-hydrate-margin-check`` skill, which
is how a map and a pipeline profile plot are combined.
"""

from __future__ import annotations

import html
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib.util import find_spec
from math import cos, isfinite, radians
from typing import Any

from .emodnet import EMODNET_ATTRIBUTION, wms_overlay
from .geometry import LonLat, bbox, normalize_polyline, polyline_length_m, validate_lonlat
from .sodir import SODIR_ATTRIBUTION, Facility, FieldArea, Pipeline

OSM_ATTRIBUTION = "Basemap: (c) OpenStreetMap contributors, ODbL"

STATUS_COLOURS = {
    "ok": "#0ca30c",
    "watch": "#fab219",
    "high": "#d03b3b",
    "unknown": "#898781",
}
MEDIUM_COLOURS = {
    "gas": "#1565c0",
    "oil": "#212121",
    "condensate": "#6a1b9a",
    "water": "#00838f",
    "injection": "#00838f",
    "co2": "#558b2f",
}
NODE_COLOURS = {
    "well": "#d81b60",
    "template": "#8e24aa",
    "manifold": "#8e24aa",
    "tie_in": "#ef6c00",
    "riser_base": "#5d4037",
    "host": "#000000",
}


def classify(
    value: float | None,
    thresholds: tuple[float, float] = (0.0, 3.0),
    higher_is_better: bool = True,
) -> str:
    """Classify a value as ``ok``, ``watch``, ``high`` or ``unknown``.

    With ``higher_is_better`` (e.g. hydrate margin in C) and thresholds
    ``(limit, watch)``: ``value <= limit`` is ``high``, ``value < watch`` is
    ``watch``, otherwise ``ok``. With ``higher_is_better=False`` (e.g.
    velocity) the comparison is mirrored: ``value >= limit`` is ``high``,
    ``value > watch`` is ``watch``.
    """
    if value is None:
        return "unknown"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if not isfinite(number):
        return "unknown"
    limit, watch = thresholds
    if higher_is_better:
        if watch < limit:
            raise ValueError("for higher_is_better thresholds must be (limit, watch) with watch >= limit")
        if number <= limit:
            return "high"
        return "watch" if number < watch else "ok"
    if watch > limit:
        raise ValueError("for lower-is-better thresholds must be (limit, watch) with watch <= limit")
    if number >= limit:
        return "high"
    return "watch" if number > watch else "ok"


def medium_colour(medium: str) -> str:
    key = (medium or "").strip().lower()
    for token, colour in MEDIUM_COLOURS.items():
        if token in key:
            return colour
    return "#455a64"


@dataclass(frozen=True)
class MapNode:
    name: str
    lon: float
    lat: float
    kind: str = "well"
    water_depth_m: float | None = None
    info: Mapping[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class MapRoute:
    name: str
    coords: tuple[LonLat, ...]
    values: tuple[float | None, ...] | None
    statuses: tuple[str, ...] | None
    value_label: str
    vertex_info: tuple[Mapping[str, Any], ...] | None
    length_km: float
    colour: str = "#ef6c00"


@dataclass(frozen=True)
class MapSummary:
    facility_count: int
    pipeline_count: int
    field_count: int
    node_count: int
    route_count: int
    bbox: tuple[float, float, float, float] | None
    route_lengths_km: dict[str, float]
    worst_route_status: dict[str, str]
    attributions: tuple[str, ...]
    warnings: tuple[str, ...]
    neqsim_available: bool
    assumptions: tuple[str, ...]


_STATUS_RANK = {"unknown": 0, "ok": 1, "watch": 2, "high": 3}


class FieldMapBuilder:
    """Collect offshore map layers and render them to GeoJSON, folium or matplotlib."""

    def __init__(self, title: str = "Field map") -> None:
        self.title = title
        self.facilities: list[Facility] = []
        self.highlight: set[str] = set()
        self.pipelines: list[Pipeline] = []
        self.fields: list[FieldArea] = []
        self.nodes: list[MapNode] = []
        self.routes: list[MapRoute] = []
        self.uses_sodir = False
        self.uses_emodnet = False
        self.warnings: list[str] = []

    # ------------------------------------------------------------------ layers

    def add_facilities(self, facilities: Iterable[Facility], highlight: Iterable[str] = ()) -> FieldMapBuilder:
        self.facilities.extend(facilities)
        self.highlight.update(name.upper() for name in highlight)
        self.uses_sodir = True
        return self

    def add_pipelines(self, pipelines: Iterable[Pipeline]) -> FieldMapBuilder:
        self.pipelines.extend(pipelines)
        self.uses_sodir = True
        return self

    def add_fields(self, fields: Iterable[FieldArea]) -> FieldMapBuilder:
        self.fields.extend(fields)
        self.uses_sodir = True
        return self

    def add_nodes(self, nodes: Iterable[Mapping[str, Any]]) -> FieldMapBuilder:
        """Add user nodes, e.g. new wells, templates or a tie-in point.

        Each mapping needs ``name`` and ``lon``/``lat`` (``longitude``/``latitude``
        or GeoJSON-style ``x``/``y`` in degrees are accepted); ``kind`` and
        ``water_depth_m`` are optional. This matches the node list produced by
        the ``neqsim-field-layout-import`` skill with geographic coordinates.
        """
        for raw in nodes:
            name = str(raw.get("name", "")).strip()
            if not name:
                raise ValueError("every node needs a name")
            lon = raw.get("lon", raw.get("longitude", raw.get("x")))
            lat = raw.get("lat", raw.get("latitude", raw.get("y")))
            lon_f, lat_f = validate_lonlat(lon, lat)
            depth = raw.get("water_depth_m")
            extra = {k: v for k, v in raw.items() if k not in {"name", "lon", "lat", "longitude", "latitude", "x", "y", "kind", "water_depth_m"}}
            self.nodes.append(
                MapNode(
                    name=name,
                    lon=lon_f,
                    lat=lat_f,
                    kind=str(raw.get("kind", "well") or "well"),
                    water_depth_m=None if depth is None else float(depth),
                    info=extra,
                )
            )
        return self

    def add_route(
        self,
        name: str,
        coords: Sequence[Sequence[float]],
        *,
        values: Sequence[float | None] | None = None,
        thresholds: tuple[float, float] = (0.0, 3.0),
        higher_is_better: bool = True,
        value_label: str = "Hydrate margin [C]",
        vertex_info: Sequence[Mapping[str, Any]] | None = None,
        colour: str = "#ef6c00",
    ) -> MapRoute:
        """Add a candidate route, optionally coloured by a per-vertex value."""
        line = tuple(normalize_polyline(coords))
        vals: tuple[float | None, ...] | None = None
        statuses: tuple[str, ...] | None = None
        if values is not None:
            vals = tuple(None if v is None else float(v) for v in values)
            if len(vals) != len(line):
                raise ValueError("values must have one entry per route coordinate")
            statuses = tuple(classify(v, thresholds, higher_is_better) for v in vals)
        info = None
        if vertex_info is not None:
            info = tuple(dict(item) for item in vertex_info)
            if len(info) != len(line):
                raise ValueError("vertex_info must have one entry per route coordinate")
        route = MapRoute(
            name=name,
            coords=line,
            values=vals,
            statuses=statuses,
            value_label=value_label,
            vertex_info=info,
            length_km=round(polyline_length_m(line) / 1000.0, 3),
            colour=colour,
        )
        self.routes.append(route)
        return route

    def use_emodnet(self) -> FieldMapBuilder:
        """Record that EMODnet bathymetry is shown or used (adds attribution)."""
        self.uses_emodnet = True
        return self

    # ------------------------------------------------------------------ queries

    def all_points(self) -> list[LonLat]:
        pts: list[LonLat] = [(f.lon, f.lat) for f in self.facilities]
        pts += [(n.lon, n.lat) for n in self.nodes]
        for route in self.routes:
            pts += list(route.coords)
        for pipe in self.pipelines:
            for path in pipe.paths:
                pts += list(path)
        for fld in self.fields:
            for ring in fld.rings:
                pts += list(ring)
        return pts

    def focus_points(self) -> list[LonLat]:
        """Points that should be in view: nodes, routes and highlighted facilities."""
        pts: list[LonLat] = [(n.lon, n.lat) for n in self.nodes]
        for route in self.routes:
            pts += list(route.coords)
        pts += [(f.lon, f.lat) for f in self.facilities if f.name.upper() in self.highlight]
        return pts or self.all_points()

    def attributions(self) -> tuple[str, ...]:
        out = []
        if self.uses_sodir:
            out.append(SODIR_ATTRIBUTION)
        if self.uses_emodnet:
            out.append(EMODNET_ATTRIBUTION)
        return tuple(out)

    @staticmethod
    def _segment_status(route: MapRoute, index: int) -> str:
        if route.statuses is None:
            return "unknown"
        a, b = route.statuses[index], route.statuses[index + 1]
        return a if _STATUS_RANK[a] >= _STATUS_RANK[b] else b

    def summary(self) -> MapSummary:
        warnings = list(self.warnings)
        highlighted = {f.name.upper() for f in self.facilities}
        for name in sorted(self.highlight - highlighted):
            warnings.append(f"highlighted facility {name!r} not found in the facility layer")
        worst: dict[str, str] = {}
        for route in self.routes:
            if route.statuses:
                worst[route.name] = max(route.statuses, key=lambda s: _STATUS_RANK[s])
        points = self.all_points()
        return MapSummary(
            facility_count=len(self.facilities),
            pipeline_count=len(self.pipelines),
            field_count=len(self.fields),
            node_count=len(self.nodes),
            route_count=len(self.routes),
            bbox=bbox(points) if points else None,
            route_lengths_km={r.name: r.length_km for r in self.routes},
            worst_route_status=worst,
            attributions=self.attributions(),
            warnings=tuple(warnings),
            neqsim_available=find_spec("neqsim") is not None,
            assumptions=(
                "Coordinates are WGS84 longitude/latitude (EPSG:4326).",
                "Route lengths are great-circle (haversine) screening lengths between supplied vertices.",
                "Route colouring classifies supplied values only; the values must come from validated NeqSim calculations.",
                "Sodir pipeline layer holds main pipelines only; infield lines are not included.",
                "Maps are for communication and screening, not for navigation, survey or design.",
            ),
        )

    # ---------------------------------------------------------------- GeoJSON

    def to_geojson(self) -> dict[str, Any]:
        """All layers as one GeoJSON FeatureCollection with a ``layer`` property."""
        feats: list[dict[str, Any]] = []
        for fld in self.fields:
            feats.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "MultiPolygon", "coordinates": [[[list(p) for p in ring]] for ring in fld.rings]},
                    "properties": {"layer": "field", "name": fld.name, "status": fld.status, "hc_type": fld.hc_type, "operator": fld.operator},
                }
            )
        for pipe in self.pipelines:
            feats.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "MultiLineString", "coordinates": [[list(p) for p in path] for path in pipe.paths]},
                    "properties": {
                        "layer": "pipeline",
                        "name": pipe.name,
                        "from": pipe.from_facility,
                        "to": pipe.to_facility,
                        "medium": pipe.medium,
                        "diameter_inch": pipe.diameter_inch,
                        "max_water_depth_m": pipe.max_water_depth_m,
                        "phase": pipe.phase,
                        "stroke": medium_colour(pipe.medium),
                    },
                }
            )
        for fac in self.facilities:
            feats.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [fac.lon, fac.lat]},
                    "properties": {
                        "layer": "facility",
                        "name": fac.name,
                        "kind": fac.kind,
                        "phase": fac.phase,
                        "water_depth_m": fac.water_depth_m,
                        "belongs_to": fac.belongs_to,
                        "highlight": fac.name.upper() in self.highlight,
                    },
                }
            )
        for node in self.nodes:
            feats.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [node.lon, node.lat]},
                    "properties": {"layer": "node", "name": node.name, "kind": node.kind, "water_depth_m": node.water_depth_m, **dict(node.info)},
                }
            )
        for route in self.routes:
            for i in range(len(route.coords) - 1):
                status = self._segment_status(route, i)
                feats.append(
                    {
                        "type": "Feature",
                        "geometry": {"type": "LineString", "coordinates": [list(route.coords[i]), list(route.coords[i + 1])]},
                        "properties": {
                            "layer": "route",
                            "name": route.name,
                            "segment": i,
                            "status": status,
                            "stroke": route.colour if route.statuses is None else STATUS_COLOURS[status],
                            "value_label": route.value_label,
                            "value_start": None if route.values is None else route.values[i],
                            "value_end": None if route.values is None else route.values[i + 1],
                        },
                    }
                )
        return {"type": "FeatureCollection", "features": feats, "attribution": list(self.attributions())}

    # ------------------------------------------------------------------ folium

    def to_folium(
        self,
        *,
        bathymetry: str | None = "multicolour",
        bathymetry_opacity: float = 0.55,
        basemap: str = "OpenStreetMap",
        zoom_start: int | None = None,
        legend: bool = True,
    ):
        """Render an interactive folium (Leaflet) map. Requires ``folium``."""
        try:
            import folium
        except ImportError as exc:  # pragma: no cover - exercised when folium missing
            raise ImportError("folium is required for to_folium(); pip install folium") from exc

        focus = self.focus_points()
        if not focus:
            raise ValueError("the map has no layers to show")
        min_lon, min_lat, max_lon, max_lat = bbox(focus)
        centre = [(min_lat + max_lat) / 2.0, (min_lon + max_lon) / 2.0]
        fmap = folium.Map(location=centre, zoom_start=zoom_start or 8, tiles=basemap, control_scale=True)

        if bathymetry:
            spec = wms_overlay(bathymetry, bathymetry_opacity)
            self.uses_emodnet = True
            folium.raster_layers.WmsTileLayer(
                url=spec.url,
                layers=spec.layers,
                fmt=spec.fmt,
                transparent=spec.transparent,
                name=spec.name,
                attr=spec.attribution,
                overlay=True,
                control=True,
                opacity=spec.opacity,
            ).add_to(fmap)
            folium.raster_layers.WmsTileLayer(
                url=spec.url,
                layers=wms_overlay("contours").layers,
                fmt="image/png",
                transparent=True,
                name="EMODnet depth contours",
                attr=spec.attribution,
                overlay=True,
                control=True,
                show=False,
            ).add_to(fmap)

        if self.fields:
            group = folium.FeatureGroup(name="Fields (Sodir)")
            for fld in self.fields:
                for ring in fld.rings:
                    folium.Polygon(
                        locations=[[lat, lon] for lon, lat in ring],
                        color="#2e7d32",
                        weight=1,
                        fill=True,
                        fill_opacity=0.15,
                        tooltip=html.escape(f"{fld.name} ({fld.hc_type}, {fld.status})"),
                    ).add_to(group)
            group.add_to(fmap)

        if self.pipelines:
            group = folium.FeatureGroup(name="Pipelines (Sodir)")
            for pipe in self.pipelines:
                tip = f"{pipe.name}: {pipe.from_facility} -> {pipe.to_facility}, {pipe.medium}"
                if pipe.diameter_inch:
                    tip += f', {pipe.diameter_inch:g}"'
                for path in pipe.paths:
                    folium.PolyLine(
                        [[lat, lon] for lon, lat in path],
                        color=medium_colour(pipe.medium),
                        weight=2,
                        opacity=0.8,
                        tooltip=html.escape(tip),
                    ).add_to(group)
            group.add_to(fmap)

        if self.facilities:
            group = folium.FeatureGroup(name="Facilities (Sodir)")
            for fac in self.facilities:
                hl = fac.name.upper() in self.highlight
                depth = "" if fac.water_depth_m is None else f", {fac.water_depth_m:g} m WD"
                folium.CircleMarker(
                    [fac.lat, fac.lon],
                    radius=7 if hl else 3,
                    color="#000000" if hl else "#37474f",
                    fill=True,
                    fill_opacity=0.9,
                    weight=2 if hl else 1,
                    tooltip=html.escape(f"{fac.name} ({fac.kind}{depth})"),
                ).add_to(group)
                if hl:
                    folium.Marker(
                        [fac.lat, fac.lon],
                        icon=folium.DivIcon(html=f'<div style="font-weight:600;font-size:11px;white-space:nowrap;transform:translate(10px,-6px)">{html.escape(fac.name)}</div>'),
                    ).add_to(group)
            group.add_to(fmap)

        if self.nodes:
            group = folium.FeatureGroup(name="New wells / nodes")
            for node in self.nodes:
                depth = "" if node.water_depth_m is None else f", {node.water_depth_m:g} m WD"
                folium.CircleMarker(
                    [node.lat, node.lon],
                    radius=6,
                    color=NODE_COLOURS.get(node.kind, "#d81b60"),
                    fill=True,
                    fill_opacity=1.0,
                    tooltip=html.escape(f"{node.name} ({node.kind}{depth})"),
                ).add_to(group)
            group.add_to(fmap)

        for route in self.routes:
            group = folium.FeatureGroup(name=f"Route: {route.name} ({route.length_km:.1f} km)")
            for i in range(len(route.coords) - 1):
                status = self._segment_status(route, i)
                colour = route.colour if route.statuses is None else STATUS_COLOURS[status]
                tip = route.name
                if route.values is not None:
                    tip += f" | {route.value_label}: {route.values[i]} -> {route.values[i + 1]} ({status})"
                folium.PolyLine(
                    [[route.coords[i][1], route.coords[i][0]], [route.coords[i + 1][1], route.coords[i + 1][0]]],
                    color=colour,
                    weight=5,
                    opacity=0.95,
                    tooltip=html.escape(tip),
                ).add_to(group)
            if route.vertex_info is not None:
                for (lon, lat), info in zip(route.coords, route.vertex_info):
                    text = "<br>".join(f"{html.escape(str(k))}: {html.escape(_fmt(v))}" for k, v in info.items())
                    folium.CircleMarker([lat, lon], radius=2, color="#263238", fill=True, tooltip=text).add_to(group)
            group.add_to(fmap)

        fmap.fit_bounds([[min_lat, min_lon], [max_lat, max_lon]], padding=(30, 30))
        folium.LayerControl(collapsed=False).add_to(fmap)
        fmap.get_root().html.add_child(folium.Element(self._legend_html(legend)))
        return fmap

    def _legend_html(self, legend: bool) -> str:
        sources = [*self.attributions()]
        rows = []
        if legend and any(r.statuses for r in self.routes):
            label = next(r.value_label for r in self.routes if r.statuses)
            rows.append(f"<b>{html.escape(label)}</b>")
            for status, text in (("ok", "ok"), ("watch", "watch"), ("high", "high / inside limit")):
                rows.append(f'<span style="display:inline-block;width:18px;height:4px;background:{STATUS_COLOURS[status]};margin-right:6px;vertical-align:middle"></span>{text}')
        if legend and self.pipelines:
            rows.append("<b>Pipeline medium</b>")
            for medium in ("gas", "oil", "condensate", "water"):
                rows.append(f'<span style="display:inline-block;width:18px;height:3px;background:{MEDIUM_COLOURS[medium]};margin-right:6px;vertical-align:middle"></span>{medium}')
        rows += [f'<span style="color:#555">{html.escape(s)}</span>' for s in sources]
        rows.append('<span style="color:#555">Screening illustration - not for navigation or design</span>')
        body = "<br>".join(rows)
        return (
            '<div style="position:fixed;bottom:24px;left:12px;z-index:9999;background:rgba(255,255,255,0.92);'
            'padding:8px 10px;border-radius:6px;font:12px/1.45 sans-serif;box-shadow:0 1px 4px rgba(0,0,0,.3);max-width:340px">'
            f"<div style='font-weight:600;margin-bottom:4px'>{html.escape(self.title)}</div>{body}</div>"
        )

    def save_html(self, path: str, **kwargs: Any) -> str:
        """Render with :meth:`to_folium` and save a standalone HTML file."""
        self.to_folium(**kwargs).save(path)
        return path

    # -------------------------------------------------------------- matplotlib

    def plot_static(
        self,
        ax=None,
        *,
        label_nodes: bool = True,
        margin_km: float = 5.0,
        show_all: bool = False,
        title: bool = True,
        attribution: bool = True,
    ):
        """Draw a static planform on a matplotlib axes (no basemap tiles)."""
        import matplotlib.pyplot as plt
        from matplotlib.lines import Line2D

        from .geometry import bbox_around

        if ax is None:
            _, ax = plt.subplots(figsize=(7, 6))
        pts = self.all_points() if show_all else self.focus_points()
        if not pts:
            raise ValueError("the map has no layers to show")
        min_lon, min_lat, max_lon, max_lat = bbox_around(pts, margin_km)

        for fld in self.fields:
            for ring in fld.rings:
                ax.fill([p[0] for p in ring], [p[1] for p in ring], color="#2e7d32", alpha=0.12, lw=0.6, ec="#2e7d32")
            # Label at the top-left corner of the field's visible extent.
            lx = max(min(p[0] for p in fld.rings[0]), min_lon)
            ly = min(max(p[1] for p in fld.rings[0]), max_lat)
            if lx <= max_lon and ly >= min_lat:
                ax.annotate(fld.name, (lx, ly), xytext=(3, -3), textcoords="offset points", fontsize=7,
                            color="#2e7d32", ha="left", va="top", style="italic")
        for pipe in self.pipelines:
            for path in pipe.paths:
                ax.plot([p[0] for p in path], [p[1] for p in path], color=medium_colour(pipe.medium), lw=1.0, alpha=0.75)
        for fac in self.facilities:
            hl = fac.name.upper() in self.highlight
            if not (min_lon <= fac.lon <= max_lon and min_lat <= fac.lat <= max_lat):
                continue
            ax.plot(fac.lon, fac.lat, "s" if hl else ".", color="black" if hl else "#455a64", ms=7 if hl else 4, zorder=4)
            if hl:
                ax.annotate(fac.name, (fac.lon, fac.lat), xytext=(5, 4), textcoords="offset points", fontsize=8, weight="bold")
        for route in self.routes:
            for i in range(len(route.coords) - 1):
                status = self._segment_status(route, i)
                colour = route.colour if route.statuses is None else STATUS_COLOURS[status]
                ax.plot(
                    [route.coords[i][0], route.coords[i + 1][0]],
                    [route.coords[i][1], route.coords[i + 1][1]],
                    color=colour,
                    lw=3.2,
                    solid_capstyle="round",
                    zorder=5,
                )
        for node in self.nodes:
            ax.plot(node.lon, node.lat, "o", color=NODE_COLOURS.get(node.kind, "#d81b60"), ms=6, mec="white", zorder=6)
            if label_nodes:
                ax.annotate(node.name, (node.lon, node.lat), xytext=(5, -10), textcoords="offset points", fontsize=8)

        ax.set_xlim(min_lon, max_lon)
        ax.set_ylim(min_lat, max_lat)
        ax.set_aspect(1.0 / max(0.05, cos(radians((min_lat + max_lat) / 2.0))))
        ax.set_xlabel("Longitude [deg E]")
        ax.set_ylabel("Latitude [deg N]")
        if title:
            ax.set_title(self.title)
        ax.grid(True, lw=0.3, alpha=0.5)

        handles = []
        if any(r.statuses for r in self.routes):
            label = next(r.value_label for r in self.routes if r.statuses)
            for status in ("ok", "watch", "high"):
                handles.append(Line2D([], [], color=STATUS_COLOURS[status], lw=3, label=f"{label}: {status}"))
        if handles:
            ax.legend(handles=handles, loc="best", fontsize=7, framealpha=0.85)
        if attribution and self.attributions():
            ax.text(0.0, -0.12, "; ".join(self.attributions()), transform=ax.transAxes, fontsize=6, color="#555", va="top")
        return ax


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)
