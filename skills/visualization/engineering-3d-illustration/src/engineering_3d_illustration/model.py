"""Parametric equipment, pipeline and layout specifications, and the scene they become.

The module is dependency-free. It turns engineering numbers - a vessel diameter
and level, a pipeline profile with a computed temperature, a list of equipment
with a utilisation each - into a backend-neutral :class:`Scene` of a few
primitive kinds (``revolved``, ``cylinder``, ``box``, ``tube``, ``ribbon``).
The backends in this package (PyVista, CadQuery, OpenSCAD, Blender) all consume
the same scene, so a figure, a STEP file and a rendered image show one geometry.

Two rules are enforced here rather than left to the caller:

* Anything drawn out of scale is recorded in ``Scene.notes`` (vertical
  exaggeration, enlarged pipe diameter, an assumed wall thickness), and the
  notes travel into ``Scene.caption()``.
* Quantities shown in labels are computed from the same specification that is
  drawn - the liquid inventory label uses the closed-form partial volume of the
  vessel at the level that the fill is clipped to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib.util import find_spec
from math import acos, cos, isfinite, pi, sin, sqrt
from shutil import which
from typing import Any, Mapping, Sequence

from . import mesh as _mesh
from .mesh import TriMesh, Vec

Bounds = tuple[float | None, float | None, float | None, float | None, float | None, float | None]
Color = tuple[float, float, float]

HEAD_TYPES = ("elliptical_2_1", "hemispherical", "flat")
ORIENTATIONS = ("horizontal", "vertical")
NOZZLE_LOCATIONS = ("top", "bottom", "side", "end_inlet", "end_outlet")
INTERNAL_KINDS = ("weir", "baffle", "demister", "inlet_device")
BLOCK_KINDS = ("box", "horizontal_vessel", "vertical_vessel")

# One palette for every backend, so figures from different tools match.
PALETTE: dict[str, Color] = {
    "shell": (0.62, 0.65, 0.69),
    "nozzle": (0.42, 0.45, 0.50),
    "support": (0.35, 0.37, 0.40),
    "oil": (0.62, 0.42, 0.14),
    "water": (0.20, 0.47, 0.75),
    "liquid": (0.25, 0.55, 0.70),
    "internal": (0.88, 0.56, 0.16),
    "deck": (0.82, 0.82, 0.80),
    "equipment": (0.45, 0.55, 0.65),
    "pipeline": (0.30, 0.32, 0.36),
    "seabed": (0.78, 0.72, 0.58),
}

_COLORMAPS: dict[str, tuple[Color, ...]] = {
    "viridis": (
        (0.267, 0.005, 0.329),
        (0.229, 0.322, 0.546),
        (0.128, 0.567, 0.551),
        (0.369, 0.789, 0.383),
        (0.993, 0.906, 0.144),
    ),
    "inferno": (
        (0.001, 0.000, 0.014),
        (0.342, 0.062, 0.429),
        (0.735, 0.216, 0.330),
        (0.978, 0.557, 0.035),
        (0.988, 0.998, 0.645),
    ),
    "coolwarm": (
        (0.230, 0.299, 0.754),
        (0.553, 0.690, 0.996),
        (0.865, 0.865, 0.865),
        (0.957, 0.604, 0.482),
        (0.706, 0.016, 0.150),
    ),
}


def _finite(name: str, value: float) -> float:
    value = float(value)
    if not isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return value


def _positive(name: str, value: float) -> float:
    value = _finite(name, value)
    if value <= 0.0:
        raise ValueError(f"{name} must be positive")
    return value


def colormap(value: float, vmin: float, vmax: float, name: str = "viridis") -> Color:
    """Map ``value`` to an RGB colour on a named five-anchor colour map."""
    if name not in _COLORMAPS:
        raise ValueError(f"colormap must be one of {', '.join(_COLORMAPS)}")
    anchors = _COLORMAPS[name]
    fraction = 0.5 if vmax <= vmin else (value - vmin) / (vmax - vmin)
    fraction = max(0.0, min(1.0, fraction))
    position = fraction * (len(anchors) - 1)
    index = min(int(position), len(anchors) - 2)
    t = position - index
    a, b = anchors[index], anchors[index + 1]
    return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]), a[2] + t * (b[2] - a[2]))


def utilisation_color(utilisation: float) -> Color:
    """Green up to 0.7, amber at 0.9, red from 1.0 - a fixed, stated legend."""
    green, amber, red = (0.30, 0.65, 0.35), (0.95, 0.70, 0.15), (0.82, 0.22, 0.18)
    u = _finite("utilisation", utilisation)
    if u <= 0.7:
        return green
    if u >= 1.0:
        return red
    a, b, t = (green, amber, (u - 0.7) / 0.2) if u < 0.9 else (amber, red, (u - 0.9) / 0.1)
    return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]), a[2] + t * (b[2] - a[2]))


UTILISATION_LEGEND = "Colour by utilisation: green <= 0.70, amber 0.90, red >= 1.00"


# --------------------------------------------------------------------------- scene


@dataclass(frozen=True)
class Primitive:
    """One drawable solid or surface.

    ``clip`` keeps only the part inside an axis-aligned box in scene
    coordinates (``None`` on a side means unbounded). It is how a cutaway, a
    liquid fill and a plate internal are all cut from the same vessel profile.
    ``scalar_range`` fixes the colour scale, so several primitives showing the
    same quantity are comparable; without it the range is the primitive's own.
    """

    name: str
    kind: str
    role: str
    color: Color
    params: Mapping[str, Any]
    opacity: float = 1.0
    clip: Bounds | None = None
    scalars: tuple[float, ...] | None = None
    scalar_name: str | None = None
    scalar_unit: str | None = None
    scalar_range: tuple[float, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "role": self.role,
            "color": list(self.color),
            "opacity": self.opacity,
            "params": _jsonable(self.params),
            "clip": list(self.clip) if self.clip is not None else None,
            "scalars": list(self.scalars) if self.scalars is not None else None,
            "scalar_name": self.scalar_name,
            "scalar_unit": self.scalar_unit,
            "scalar_range": list(self.scalar_range) if self.scalar_range is not None else None,
        }


@dataclass(frozen=True)
class Label:
    """A text annotation anchored at a point in scene coordinates."""

    text: str
    position: Vec
    kind: str = "annotation"


@dataclass(frozen=True)
class Scene:
    """Backend-neutral description of one illustration."""

    name: str
    title: str
    primitives: tuple[Primitive, ...]
    labels: tuple[Label, ...] = ()
    notes: tuple[str, ...] = ()
    true_scale: bool = True
    facts: Mapping[str, float] = field(default_factory=dict)

    def bounds(self) -> tuple[float, float, float, float, float, float]:
        """Axis-aligned bounds of everything drawn, after clipping."""
        low = [float("inf")] * 3
        high = [float("-inf")] * 3
        for primitive in self.primitives:
            b = list(tessellate(primitive).bounds())
            if primitive.clip is not None:
                for axis in range(3):
                    cmin, cmax = primitive.clip[2 * axis], primitive.clip[2 * axis + 1]
                    if cmin is not None:
                        b[2 * axis] = max(b[2 * axis], cmin)
                    if cmax is not None:
                        b[2 * axis + 1] = min(b[2 * axis + 1], cmax)
            for axis in range(3):
                low[axis] = min(low[axis], b[2 * axis])
                high[axis] = max(high[axis], b[2 * axis + 1])
        return (low[0], high[0], low[1], high[1], low[2], high[2])

    def caption(self) -> str:
        """Figure caption: the title, every out-of-scale note, and the status."""
        parts = [self.title.rstrip(".") + "."]
        parts.extend(note.rstrip(".") + "." for note in self.notes)
        parts.append("Drawn to scale." if self.true_scale else "Not to scale.")
        parts.append("Illustration of calculated results - not a design or fabrication drawing.")
        return " ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "true_scale": self.true_scale,
            "notes": list(self.notes),
            "caption": self.caption(),
            "bounds": list(self.bounds()),
            "facts": dict(self.facts),
            "primitives": [p.to_dict() for p in self.primitives],
            "labels": [
                {"text": label.text, "position": list(label.position), "kind": label.kind}
                for label in self.labels
            ],
        }


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def tessellate(primitive: Primitive) -> TriMesh:
    """Triangles for a primitive, before its ``clip`` is applied."""
    p = primitive.params
    if primitive.kind == "revolved":
        return _mesh.revolve(p["profile"], p["origin"], p["axis"], p.get("segments", 72))
    if primitive.kind == "cylinder":
        return _mesh.cylinder(p["base"], p["axis"], p["radius"], p["height"])
    if primitive.kind == "box":
        return _mesh.box(p["center"], p["size"], p.get("rotation_z_deg", 0.0))
    if primitive.kind == "tube":
        return _mesh.tube(p["points"], p["radius"], primitive.scalars)
    if primitive.kind == "ribbon":
        return _mesh.ribbon(p["points"], p["width"])
    raise ValueError(f"unknown primitive kind {primitive.kind!r}")


@dataclass(frozen=True)
class RenderOutcome:
    """Result of asking a backend to draw or export a scene.

    ``status`` is ``completed``, ``not_executed`` (the tool is not installed;
    any generated script is still listed in ``files`` with the ``command`` to
    run it elsewhere) or ``failed``.
    """

    backend: str
    status: str
    files: tuple[Any, ...]
    command: str
    message: str
    caption: str = ""

    @property
    def completed(self) -> bool:
        return self.status == "completed" and bool(self.files)


# -------------------------------------------------------------------------- vessel


@dataclass(frozen=True)
class Nozzle:
    """A nozzle stub. ``position_fraction`` runs 0-1 along the tan-tan length."""

    name: str
    location: str = "top"
    position_fraction: float = 0.5
    diameter_m: float = 0.3
    projection_m: float | None = None

    def __post_init__(self) -> None:
        if self.location not in NOZZLE_LOCATIONS:
            raise ValueError(f"nozzle location must be one of {', '.join(NOZZLE_LOCATIONS)}")
        if not 0.0 <= _finite("position_fraction", self.position_fraction) <= 1.0:
            raise ValueError("nozzle position_fraction must be between 0 and 1")
        _positive("nozzle diameter_m", self.diameter_m)
        if self.projection_m is not None:
            _positive("nozzle projection_m", self.projection_m)


@dataclass(frozen=True)
class Internal:
    """A plate or pad internal perpendicular to the vessel axis.

    In a horizontal vessel it stands at ``position_fraction`` of the tan-tan
    length and spans ``bottom_m`` to ``top_m`` above the vessel bottom (a weir
    is ``bottom_m = 0``). In a vertical vessel it is a horizontal slab at
    ``position_fraction`` of the tan-tan length and the height limits are unused.
    """

    name: str
    kind: str = "weir"
    position_fraction: float = 0.75
    thickness_m: float = 0.02
    bottom_m: float = 0.0
    top_m: float | None = None

    def __post_init__(self) -> None:
        if self.kind not in INTERNAL_KINDS:
            raise ValueError(f"internal kind must be one of {', '.join(INTERNAL_KINDS)}")
        if not 0.0 <= _finite("position_fraction", self.position_fraction) <= 1.0:
            raise ValueError("internal position_fraction must be between 0 and 1")
        _positive("internal thickness_m", self.thickness_m)
        if _finite("bottom_m", self.bottom_m) < 0.0:
            raise ValueError("internal bottom_m must not be negative")
        if self.top_m is not None and self.top_m <= self.bottom_m:
            raise ValueError("internal top_m must be above bottom_m")


@dataclass(frozen=True)
class VesselSpec:
    """A horizontal or vertical pressure vessel with levels, nozzles and internals.

    Levels are heights in metres above the lowest inside point of the vessel.
    ``interface_level_m`` is the water/oil interface; when it is omitted the
    liquid is drawn as a single phase.
    """

    tag: str
    inside_diameter_m: float
    tan_tan_length_m: float
    orientation: str = "horizontal"
    head_type: str = "elliptical_2_1"
    wall_thickness_m: float | None = None
    liquid_level_m: float | None = None
    interface_level_m: float | None = None
    level_marks_m: Mapping[str, float] = field(default_factory=dict)
    nozzles: tuple[Nozzle, ...] = ()
    internals: tuple[Internal, ...] = ()

    def __post_init__(self) -> None:
        _positive("inside_diameter_m", self.inside_diameter_m)
        _positive("tan_tan_length_m", self.tan_tan_length_m)
        if self.orientation not in ORIENTATIONS:
            raise ValueError(f"orientation must be one of {', '.join(ORIENTATIONS)}")
        if self.head_type not in HEAD_TYPES:
            raise ValueError(f"head_type must be one of {', '.join(HEAD_TYPES)}")
        if self.wall_thickness_m is not None:
            _positive("wall_thickness_m", self.wall_thickness_m)
        height = self.inside_height_m
        if self.liquid_level_m is not None:
            if not 0.0 <= _finite("liquid_level_m", self.liquid_level_m) <= height + 1e-9:
                raise ValueError(
                    f"liquid_level_m must be between 0 and the inside height {height:.3f} m"
                )
        if self.interface_level_m is not None:
            if self.liquid_level_m is None:
                raise ValueError("interface_level_m needs liquid_level_m")
            if (
                not 0.0
                <= _finite("interface_level_m", self.interface_level_m)
                <= self.liquid_level_m
            ):
                raise ValueError("interface_level_m must be between 0 and liquid_level_m")
        for name, level in self.level_marks_m.items():
            if not 0.0 <= _finite(f"level mark {name}", level) <= height + 1e-9:
                raise ValueError(f"level mark {name} is outside the vessel")
        object.__setattr__(self, "nozzles", tuple(self.nozzles))
        object.__setattr__(self, "internals", tuple(self.internals))

    @property
    def radius_m(self) -> float:
        return self.inside_diameter_m / 2.0

    @property
    def head_depth_m(self) -> float:
        if self.head_type == "elliptical_2_1":
            return self.inside_diameter_m / 4.0
        if self.head_type == "hemispherical":
            return self.inside_diameter_m / 2.0
        return 0.0

    @property
    def inside_height_m(self) -> float:
        """Vertical extent of the inside volume - the range a level can take."""
        if self.orientation == "horizontal":
            return self.inside_diameter_m
        return self.tan_tan_length_m + 2.0 * self.head_depth_m

    @property
    def total_volume_m3(self) -> float:
        r, c = self.radius_m, self.head_depth_m
        return pi * r * r * self.tan_tan_length_m + 4.0 / 3.0 * pi * r * r * c

    def liquid_volume_m3(self, level_m: float | None = None) -> float:
        """Closed-form volume below ``level_m`` (default: the liquid level)."""
        if level_m is None:
            level_m = self.liquid_level_m
        if level_m is None:
            return 0.0
        h = min(max(_finite("level_m", level_m), 0.0), self.inside_height_m)
        r, c, length = self.radius_m, self.head_depth_m, self.tan_tan_length_m
        if self.orientation == "horizontal":
            segment = r * r * acos((r - h) / r) - (r - h) * sqrt(max(2.0 * r * h - h * h, 0.0))
            # Both heads together are a spheroid: a sphere scaled by c/r along the axis.
            heads = (c / r) * pi * h * h * (3.0 * r - h) / 3.0
            return segment * length + heads
        if c <= 0.0:
            return pi * r * r * h
        volume = 0.0
        low = min(h, c)
        volume += pi * r * r * low * low * (3.0 * c - low) / (3.0 * c * c)
        if h > c:
            volume += pi * r * r * (min(h, c + length) - c)
        if h > c + length:
            top = h - c - length  # height into the top head above its tangent line
            volume += pi * r * r * (top - top**3 / (3.0 * c * c))
        return volume


def vessel_profile(
    radius: float,
    length: float,
    head_depth: float,
    offset: float = 0.0,
    points_per_head: int = 24,
) -> list[tuple[float, float]]:
    """``(axial, radius)`` outline from pole to pole; axial 0 is the first tangent line."""
    r = radius + offset
    if head_depth <= 0.0:
        return [(-offset, 0.0), (-offset, r), (length + offset, r), (length + offset, 0.0)]
    c = head_depth + offset
    outline = []
    for i in range(points_per_head + 1):
        theta = (pi / 2.0) * i / points_per_head
        outline.append((-c * cos(theta), 0.0 if i == 0 else r * sin(theta)))
    for i in range(points_per_head + 1):
        theta = (pi / 2.0) * (1.0 - i / points_per_head)
        outline.append((length + c * cos(theta), 0.0 if i == points_per_head else r * sin(theta)))
    return outline


def build_vessel_scene(
    spec: VesselSpec,
    *,
    cutaway: bool = True,
    supports: bool = True,
    title: str | None = None,
) -> Scene:
    """Scene for a vessel: shell (cut open), liquid phases, internals, nozzles.

    The vessel sits with its lowest inside point at ``z = 0`` so a level in
    metres is a height in the scene. A horizontal vessel runs along ``x``; the
    cutaway removes the half facing the default camera (``y < 0``).
    """
    horizontal = spec.orientation == "horizontal"
    r, c, length = spec.radius_m, spec.head_depth_m, spec.tan_tan_length_m
    notes: list[str] = []
    if spec.wall_thickness_m is None:
        thickness = max(0.01 * spec.inside_diameter_m, 0.008)
        notes.append(
            f"Wall thickness not specified - drawn as {thickness * 1000:.0f} mm for visibility"
        )
    else:
        thickness = spec.wall_thickness_m

    if horizontal:
        origin: Vec = (0.0, 0.0, r)
        axis: Vec = (1.0, 0.0, 0.0)
    else:
        origin = (0.0, 0.0, c)
        axis = (0.0, 0.0, 1.0)
    cut: Bounds | None = (None, None, 0.0, None, None, None) if cutaway else None

    def clipped(
        x: tuple[float | None, float | None] = (None, None),
        z: tuple[float | None, float | None] = (None, None),
    ) -> Bounds:
        return (x[0], x[1], 0.0 if cutaway else None, None, z[0], z[1])

    inner = vessel_profile(r, length, c)
    outer = vessel_profile(r, length, c, offset=thickness)
    # Liquid and internals are drawn a hair inside the wall to avoid coincident faces.
    inside = vessel_profile(r * 0.998, length, c * 0.998 if c > 0.0 else 0.0)
    revolve_params = {"origin": origin, "axis": axis}

    primitives: list[Primitive] = [
        Primitive(
            name="shell",
            kind="revolved",
            role="shell",
            color=PALETTE["shell"],
            params={"profile": outer + inner[::-1], **revolve_params},
            clip=cut,
        )
    ]
    labels: list[Label] = []
    facts: dict[str, float] = {"total_volume_m3": spec.total_volume_m3}

    # Liquid phases, clipped from the inside profile between the level planes.
    if spec.liquid_level_m is not None and spec.liquid_level_m > 0.0:
        level = spec.liquid_level_m
        interface = spec.interface_level_m
        phases: list[tuple[str, str, float, float]] = []
        if interface is not None and interface > 0.0:
            phases.append(("water", "water", 0.0, interface))
            if level > interface:
                phases.append(("oil", "oil", interface, level))
        else:
            phases.append(("liquid", "liquid", 0.0, level))
        weir_x = None
        if horizontal:
            weirs = [i for i in spec.internals if i.kind == "weir"]
            if weirs:
                weir_x = weirs[0].position_fraction * length
        for name, role, z0, z1 in phases:
            x_range: tuple[float | None, float | None] = (None, None)
            if weir_x is not None:
                # Liquid is drawn on the inlet side of the weir only; the level
                # downstream of a weir is a separate controlled level.
                x_range = (None, weir_x)
            primitives.append(
                Primitive(
                    name=name,
                    kind="revolved",
                    role=role,
                    color=PALETTE[role],
                    params={"profile": inside, **revolve_params},
                    opacity=0.9,
                    clip=clipped(x=x_range, z=(z0, z1)),
                )
            )
        if weir_x is not None:
            notes.append("Liquid shown on the inlet side of the weir only")
        liquid_volume = spec.liquid_volume_m3()
        facts["liquid_volume_m3"] = liquid_volume
        facts["liquid_fill_fraction"] = liquid_volume / spec.total_volume_m3
        label_x = -c - thickness if horizontal else r + thickness
        labels.append(Label(f"Liquid level {level:.2f} m", (label_x, 0.0, level), "level"))
        if interface is not None and 0.0 < interface < level:
            facts["water_volume_m3"] = spec.liquid_volume_m3(interface)
            labels.append(Label(f"Interface {interface:.2f} m", (label_x, 0.0, interface), "level"))
        if weir_x is None:
            notes.append(
                f"Liquid inventory {liquid_volume:.1f} m3 "
                f"({100.0 * liquid_volume / spec.total_volume_m3:.0f} % of {spec.total_volume_m3:.1f} m3)"
            )

    mark_x = length + c + thickness if horizontal else -(r + thickness)
    for name, level in sorted(spec.level_marks_m.items(), key=lambda item: item[1]):
        labels.append(Label(f"{name} {level:.2f} m", (mark_x, 0.0, level), "level"))

    for internal in spec.internals:
        position = internal.position_fraction * length
        if horizontal:
            top = internal.top_m if internal.top_m is not None else spec.inside_diameter_m
            clip = clipped(
                x=(position, position + internal.thickness_m), z=(internal.bottom_m, top)
            )
            anchor: Vec = (position, 0.0, top)
        else:
            z = c + position
            clip = clipped(z=(z, z + internal.thickness_m))
            anchor = (r, 0.0, z + internal.thickness_m)
        primitives.append(
            Primitive(
                name=internal.name,
                kind="revolved",
                role="internal",
                color=PALETTE["internal"],
                params={"profile": inside, **revolve_params},
                clip=clip,
            )
        )
        labels.append(Label(internal.name, anchor, "internal"))

    for nozzle in spec.nozzles:
        radius = nozzle.diameter_m / 2.0
        projection = nozzle.projection_m or max(0.15 * spec.inside_diameter_m, 2.0 * radius)
        embed = min(0.5 * radius, 0.05 * spec.inside_diameter_m) + thickness
        position = nozzle.position_fraction * length
        if horizontal:
            if nozzle.location == "top":
                base, direction = (position, 0.0, 2.0 * r + thickness - embed), (0.0, 0.0, 1.0)
            elif nozzle.location == "bottom":
                base, direction = (position, 0.0, -thickness + embed), (0.0, 0.0, -1.0)
            elif nozzle.location == "side":
                base, direction = (position, r + thickness - embed, r), (0.0, 1.0, 0.0)
            elif nozzle.location == "end_inlet":
                base, direction = (-c - thickness + embed, 0.0, r), (-1.0, 0.0, 0.0)
            else:
                base, direction = (length + c + thickness - embed, 0.0, r), (1.0, 0.0, 0.0)
        else:
            top_z = length + 2.0 * c
            if nozzle.location in ("top", "end_outlet"):
                base, direction = (0.0, 0.0, top_z + thickness - embed), (0.0, 0.0, 1.0)
            elif nozzle.location in ("bottom", "end_inlet"):
                base, direction = (0.0, 0.0, -thickness + embed), (0.0, 0.0, -1.0)
            else:
                base, direction = (r + thickness - embed, 0.0, c + position), (1.0, 0.0, 0.0)
        height = projection + embed
        primitives.append(
            Primitive(
                name=nozzle.name,
                kind="cylinder",
                role="nozzle",
                color=PALETTE["nozzle"],
                params={"base": base, "axis": direction, "radius": radius, "height": height},
                clip=cut,
            )
        )
        tip = (
            base[0] + direction[0] * height,
            base[1] + direction[1] * height,
            base[2] + direction[2] * height,
        )
        labels.append(Label(nozzle.name, tip, "nozzle"))

    if supports:
        d = spec.inside_diameter_m
        if horizontal:
            saddle = (min(0.08 * length, 0.6), 0.7 * d, 0.3 * d)
            for fraction in (0.2, 0.8):
                primitives.append(
                    Primitive(
                        name=f"saddle-{fraction:.1f}",
                        kind="box",
                        role="support",
                        color=PALETTE["support"],
                        params={
                            "center": (fraction * length, 0.0, -thickness - saddle[2] / 2.0),
                            "size": saddle,
                        },
                        clip=cut,
                    )
                )
        else:
            skirt_bottom = -0.3 * d - c  # relative to the bottom tangent line
            ring = [
                (skirt_bottom, r + thickness),
                (skirt_bottom, r + 2.0 * thickness),
                (0.0, r + 2.0 * thickness),
                (0.0, r + thickness),
                (skirt_bottom, r + thickness),
            ]
            primitives.append(
                Primitive(
                    name="skirt",
                    kind="revolved",
                    role="support",
                    color=PALETTE["support"],
                    params={"profile": ring, **revolve_params},
                    clip=cut,
                )
            )

    if horizontal:
        labels.append(Label(spec.tag, (length / 2.0, 0.0, 2.0 * r + thickness), "tag"))
    else:
        labels.append(Label(spec.tag, (0.0, 0.0, length + 2.0 * c + thickness), "tag"))
    dimension = f"ID {spec.inside_diameter_m:.2f} m x T/T {length:.2f} m"
    head = spec.head_type.replace("_", " ").replace("2 1", "2:1")
    notes.insert(0, f"{dimension}, {head} heads")
    if cutaway:
        notes.append("Front half cut away to show the inside")
    if spec.nozzles:
        notes.append("Nozzles shown as stubs at schematic positions")

    return Scene(
        name=_slug(spec.tag),
        title=title or f"{spec.tag} - {spec.orientation} vessel",
        primitives=tuple(primitives),
        labels=tuple(labels),
        notes=tuple(notes),
        true_scale=spec.wall_thickness_m is not None,
        facts=facts,
    )


# ------------------------------------------------------------------------ pipeline


@dataclass(frozen=True)
class FieldSeries:
    """One calculated quantity along a pipeline, one value per profile point."""

    name: str
    unit: str
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        values = tuple(_finite(f"field {self.name}", v) for v in self.values)
        if not values:
            raise ValueError(f"field {self.name} has no values")
        object.__setattr__(self, "values", values)


@dataclass(frozen=True)
class PipelineSpec:
    """A pipeline centreline in metres with calculated fields along it."""

    name: str
    points: tuple[Vec, ...]
    outside_diameter_m: float
    fields: tuple[FieldSeries, ...] = ()

    def __post_init__(self) -> None:
        points = tuple(
            (_finite("x", p[0]), _finite("y", p[1]), _finite("z", p[2])) for p in self.points
        )
        if len(points) < 2:
            raise ValueError("a pipeline needs at least two points")
        for a, b in zip(points[:-1], points[1:]):
            if a == b:
                raise ValueError("consecutive pipeline points must differ")
        _positive("outside_diameter_m", self.outside_diameter_m)
        fields = tuple(self.fields)
        for series in fields:
            if len(series.values) != len(points):
                raise ValueError(
                    f"field {series.name} has {len(series.values)} values for {len(points)} points"
                )
        if len({f.name for f in fields}) != len(fields):
            raise ValueError("field names must be unique")
        object.__setattr__(self, "points", points)
        object.__setattr__(self, "fields", fields)

    @classmethod
    def from_profile(
        cls,
        name: str,
        distance_m: Sequence[float],
        elevation_m: Sequence[float],
        outside_diameter_m: float,
        fields: Sequence[FieldSeries] = (),
        heading_deg: float = 0.0,
    ) -> "PipelineSpec":
        """Build from along-route distance and elevation on a straight heading.

        ``distance_m`` is the horizontal (plan) distance from the start. Use the
        constructor with real ``(x, y, z)`` points when the route bends in plan.
        """
        if len(distance_m) != len(elevation_m):
            raise ValueError("distance_m and elevation_m must have the same length")
        cx, sy = cos(heading_deg * pi / 180.0), sin(heading_deg * pi / 180.0)
        points = tuple(
            (float(d) * cx, float(d) * sy, float(z)) for d, z in zip(distance_m, elevation_m)
        )
        return cls(name, points, outside_diameter_m, tuple(fields))

    def chainage_m(self) -> tuple[float, ...]:
        """Cumulative true length along the pipe at each point."""
        total = [0.0]
        for a, b in zip(self.points[:-1], self.points[1:]):
            total.append(
                total[-1] + sqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2 + (b[2] - a[2]) ** 2)
            )
        return tuple(total)

    def field(self, name: str) -> FieldSeries:
        for series in self.fields:
            if series.name == name:
                return series
        raise KeyError(f"no field named {name!r}; available: {[f.name for f in self.fields]}")

    def low_points(self, max_count: int = 3) -> tuple[int, ...]:
        """Indices of interior local elevation minima, deepest first.

        A minimum counts only if the pipe rises on both sides by at least 2 %
        of the elevation range - liquid collects there, so it is worth a label.
        """
        z = [p[2] for p in self.points]
        span = max(z) - min(z)
        if span <= 0.0:
            return ()
        found = []
        for i in range(1, len(z) - 1):
            if z[i] <= z[i - 1] and z[i] < z[i + 1]:
                left = max(z[: i + 1]) - z[i]
                right = max(z[i:]) - z[i]
                if min(left, right) >= 0.02 * span:
                    found.append(i)
        found.sort(key=lambda index: z[index])
        return tuple(found[:max_count])

    def suggested_vertical_exaggeration(self) -> float:
        """A round factor that makes the profile relief readable, or 1.0."""
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        zs = [p[2] for p in self.points]
        horizontal = sqrt((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2)
        vertical = max(zs) - min(zs)
        if vertical <= 0.0 or horizontal <= 0.0:
            return 1.0
        raw = 0.2 * horizontal / vertical
        if raw < 1.5:
            return 1.0
        for step in (2, 5, 10, 20, 50, 100, 200, 500):
            if raw <= step * 1.5:
                return float(step)
        return 500.0


def build_pipeline_scene(
    spec: PipelineSpec,
    *,
    color_by: str | None = None,
    vertical_exaggeration: float | None = None,
    display_diameter_m: float | None = None,
    terrain: bool = True,
    title: str | None = None,
) -> Scene:
    """Scene for a pipeline: a tube coloured by a calculated field.

    ``vertical_exaggeration=None`` picks a round factor from the profile;
    ``display_diameter_m=None`` enlarges the pipe just enough to be visible.
    Both are recorded in the scene notes and therefore in the caption.
    """
    if vertical_exaggeration is None:
        vertical_exaggeration = spec.suggested_vertical_exaggeration()
    ve = _positive("vertical_exaggeration", vertical_exaggeration)
    display = tuple((p[0], p[1], p[2] * ve) for p in spec.points)
    xs, ys, zs = ([p[i] for p in display] for i in range(3))
    diagonal = sqrt((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2 + (max(zs) - min(zs)) ** 2)
    if display_diameter_m is None:
        display_diameter_m = max(spec.outside_diameter_m, 0.012 * diagonal)
    radius = _positive("display_diameter_m", display_diameter_m) / 2.0

    notes: list[str] = []
    chainage = spec.chainage_m()
    notes.append(
        f"Length {chainage[-1] / 1000.0:.2f} km, OD {spec.outside_diameter_m * 1000.0:.0f} mm"
    )
    if ve != 1.0:
        notes.append(f"Vertical exaggeration x{ve:g}")
    diameter_factor = display_diameter_m / spec.outside_diameter_m
    if diameter_factor > 1.05:
        notes.append(f"Pipe diameter drawn x{diameter_factor:.0f} for visibility")

    scalars = None
    scalar_name = scalar_unit = None
    labels: list[Label] = []

    def above(index: int) -> Vec:
        p = display[index]
        return (p[0], p[1], p[2] + 1.5 * radius)

    if color_by is not None:
        series = spec.field(color_by)
        scalars, scalar_name, scalar_unit = series.values, series.name, series.unit
        low, high = min(series.values), max(series.values)
        notes.append(f"Colour: {series.name} [{series.unit}], {low:.4g} to {high:.4g}")
        i_max = series.values.index(high)
        i_min = series.values.index(low)
        if high > low:
            labels.append(
                Label(
                    f"max {high:.4g} {series.unit} @ KP {chainage[i_max] / 1000.0:.1f}",
                    above(i_max),
                    "field",
                )
            )
            labels.append(
                Label(
                    f"min {low:.4g} {series.unit} @ KP {chainage[i_min] / 1000.0:.1f}",
                    above(i_min),
                    "field",
                )
            )

    primitives = [
        Primitive(
            name=spec.name,
            kind="tube",
            role="pipeline",
            color=PALETTE["pipeline"],
            params={"points": display, "radius": radius},
            scalars=scalars,
            scalar_name=scalar_name,
            scalar_unit=scalar_unit,
        )
    ]
    if terrain:
        primitives.append(
            Primitive(
                name="terrain",
                kind="ribbon",
                role="seabed",
                color=PALETTE["seabed"],
                params={
                    "points": tuple((p[0], p[1], p[2] - 1.05 * radius) for p in display),
                    "width": 14.0 * radius,
                },
            )
        )
        notes.append("Terrain strip follows the pipe profile and is schematic")

    labelled = {label.position for label in labels}
    for index, text in ((0, "KP 0.0"), (len(display) - 1, f"KP {chainage[-1] / 1000.0:.1f}")):
        if above(index) not in labelled:  # a field label already marks this end
            labels.append(Label(text, above(index), "end"))
    for index in spec.low_points():
        labels.append(
            Label(
                f"low point {spec.points[index][2]:.0f} m @ KP {chainage[index] / 1000.0:.1f}",
                (display[index][0], display[index][1], display[index][2] - 3.0 * radius),
                "low_point",
            )
        )

    return Scene(
        name=_slug(spec.name),
        title=title or f"{spec.name} - pipeline profile",
        primitives=tuple(primitives),
        labels=tuple(labels),
        notes=tuple(notes),
        true_scale=ve == 1.0 and diameter_factor <= 1.05,
        facts={"length_m": chainage[-1], "vertical_exaggeration": ve},
    )


# -------------------------------------------------------------------------- layout


@dataclass(frozen=True)
class EquipmentBlock:
    """A piece of equipment on a layout, as a box or a simple vessel.

    ``position`` is the centre of the footprint at the base elevation.
    ``size_m`` is ``(length, width, height)`` for a box, ``(diameter, length)``
    for a horizontal vessel and ``(diameter, height)`` for a vertical one.
    ``utilisation`` (for example a calculated capacity utilisation, 1.0 = at
    the limit) colours the block on the fixed green-amber-red legend.
    """

    tag: str
    kind: str
    position: Vec
    size_m: tuple[float, ...]
    rotation_deg: float = 0.0
    utilisation: float | None = None

    def __post_init__(self) -> None:
        if self.kind not in BLOCK_KINDS:
            raise ValueError(f"block kind must be one of {', '.join(BLOCK_KINDS)}")
        expected = 3 if self.kind == "box" else 2
        if len(self.size_m) != expected:
            raise ValueError(f"{self.kind} needs {expected} size values")
        for value in self.size_m:
            _positive("size_m", value)
        for value in self.position:
            _finite("position", value)
        if self.utilisation is not None and _finite("utilisation", self.utilisation) < 0.0:
            raise ValueError("utilisation must not be negative")


@dataclass(frozen=True)
class Deck:
    """A rectangular deck or skid base at an elevation."""

    name: str
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    elevation_m: float = 0.0
    thickness_m: float = 0.2

    def __post_init__(self) -> None:
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ValueError("deck max must exceed min")
        _positive("deck thickness_m", self.thickness_m)


@dataclass(frozen=True)
class LayoutSpec:
    """Equipment blocks on decks - a module, a skid or a platform level."""

    name: str
    blocks: tuple[EquipmentBlock, ...]
    decks: tuple[Deck, ...] = ()

    def __post_init__(self) -> None:
        blocks = tuple(self.blocks)
        if not blocks:
            raise ValueError("a layout needs at least one equipment block")
        if len({b.tag for b in blocks}) != len(blocks):
            raise ValueError("equipment tags must be unique")
        object.__setattr__(self, "blocks", blocks)
        object.__setattr__(self, "decks", tuple(self.decks))


def build_layout_scene(spec: LayoutSpec, *, title: str | None = None) -> Scene:
    """Scene for a layout, with blocks coloured by utilisation when given."""
    primitives: list[Primitive] = []
    labels: list[Label] = []
    for deck in spec.decks:
        primitives.append(
            Primitive(
                name=deck.name,
                kind="box",
                role="deck",
                color=PALETTE["deck"],
                params={
                    "center": (
                        (deck.x_min + deck.x_max) / 2.0,
                        (deck.y_min + deck.y_max) / 2.0,
                        deck.elevation_m - deck.thickness_m / 2.0,
                    ),
                    "size": (deck.x_max - deck.x_min, deck.y_max - deck.y_min, deck.thickness_m),
                },
            )
        )
    coloured = False
    for block in spec.blocks:
        color = PALETTE["equipment"]
        text = block.tag
        if block.utilisation is not None:
            color = utilisation_color(block.utilisation)
            text = f"{block.tag}  {100.0 * block.utilisation:.0f} %"
            coloured = True
        x, y, z = block.position
        if block.kind == "box":
            length, width, height = block.size_m
            params: dict[str, Any] = {
                "center": (x, y, z + height / 2.0),
                "size": (length, width, height),
                "rotation_z_deg": block.rotation_deg,
            }
            kind, top = "box", z + height
        elif block.kind == "horizontal_vessel":
            diameter, length = block.size_m
            direction = (
                cos(block.rotation_deg * pi / 180.0),
                sin(block.rotation_deg * pi / 180.0),
                0.0,
            )
            params = {
                "profile": vessel_profile(
                    diameter / 2.0, length, diameter / 4.0, points_per_head=10
                ),
                "origin": (
                    x - direction[0] * length / 2.0,
                    y - direction[1] * length / 2.0,
                    z + diameter / 2.0,
                ),
                "axis": direction,
                "segments": 40,
            }
            kind, top = "revolved", z + diameter
        else:
            diameter, height = block.size_m
            depth = diameter / 4.0
            params = {
                "profile": vessel_profile(
                    diameter / 2.0, max(height - 2.0 * depth, 1e-6), depth, points_per_head=10
                ),
                "origin": (x, y, z + depth),
                "axis": (0.0, 0.0, 1.0),
                "segments": 40,
            }
            kind, top = "revolved", z + height
        primitives.append(
            Primitive(name=block.tag, kind=kind, role="equipment", color=color, params=params)
        )
        labels.append(Label(text, (x, y, top), "tag"))
    notes = [f"{len(spec.blocks)} equipment items, positions and envelope sizes as supplied"]
    if coloured:
        notes.append(UTILISATION_LEGEND)
    notes.append("Equipment shown as envelope shapes")
    return Scene(
        name=_slug(spec.name),
        title=title or f"{spec.name} - equipment layout",
        primitives=tuple(primitives),
        labels=tuple(labels),
        notes=tuple(notes),
        true_scale=True,
    )


def _slug(text: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in text)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-") or "scene"


# ------------------------------------------------------------- NeqSim adapters


def vessel_from_neqsim_separator(
    separator: Any,
    *,
    tag: str | None = None,
    head_type: str = "elliptical_2_1",
    nozzles: Sequence[Nozzle] = (),
    internals: Sequence[Internal] = (),
    interface_level_m: float | None = None,
) -> VesselSpec:
    """Read geometry and level from a NeqSim ``Separator`` after it has run.

    Uses ``getInternalDiameter()``, ``getSeparatorLength()``, ``getOrientation()``
    and ``getLiquidLevel()``. NeqSim reports the level as a fraction of the
    maximum liquid height (the inside diameter for a horizontal separator, the
    tan-tan length for a vertical one); it is converted to metres here. Head
    type, nozzles and internals are not held by the process model and must be
    supplied.
    """
    diameter = float(separator.getInternalDiameter())
    length = float(separator.getSeparatorLength())
    orientation = str(separator.getOrientation()).lower()
    if orientation not in ORIENTATIONS:
        orientation = "horizontal"
    fraction = float(separator.getLiquidLevel())
    max_height = diameter if orientation == "horizontal" else length
    level = max(0.0, min(fraction, 1.0)) * max_height
    return VesselSpec(
        tag=tag or str(separator.getName()),
        inside_diameter_m=diameter,
        tan_tan_length_m=length,
        orientation=orientation,
        head_type=head_type,
        liquid_level_m=level if level > 0.0 else None,
        interface_level_m=interface_level_m,
        nozzles=tuple(nozzles),
        internals=tuple(internals),
    )


def pipeline_from_neqsim_pipe(
    pipe: Any, *, name: str | None = None, outside_diameter_m: float | None = None
) -> PipelineSpec:
    """Read the profile and results from a NeqSim ``PipeBeggsAndBrills`` after it has run.

    Uses ``getLengthProfile()`` and ``getElevationProfile()`` for the geometry
    and ``getPressureProfile()`` (bara), ``getTemperatureProfile()`` (converted
    from K to C) and ``getLiquidHoldupProfile()`` for the fields. NeqSim holds
    the inside diameter (``getDiameter()``); pass ``outside_diameter_m`` when
    it is known. The pipe is laid out on a straight heading - the process
    model has no plan-view route.
    """
    length = [float(v) for v in pipe.getLengthProfile()]
    elevation = [float(v) for v in pipe.getElevationProfile()]
    count = min(len(length), len(elevation))
    if count < 2:
        raise ValueError("the pipe has no profile - run it before reading results")
    distance = [0.0]
    for i in range(1, count):
        run = length[i] - length[i - 1]
        rise = elevation[i] - elevation[i - 1]
        distance.append(distance[-1] + sqrt(max(run * run - rise * rise, 0.0)))
    fields = []
    for field_name, unit, getter, convert in (
        ("Pressure", "bara", "getPressureProfile", lambda v: v),
        ("Temperature", "C", "getTemperatureProfile", lambda v: v - 273.15),
        ("Liquid holdup", "-", "getLiquidHoldupProfile", lambda v: v),
    ):
        try:
            values = [convert(float(v)) for v in getattr(pipe, getter)()]
        except Exception:  # noqa: BLE001 - a missing profile only drops that field
            continue
        if len(values) >= count:
            fields.append(FieldSeries(field_name, unit, tuple(values[:count])))
    return PipelineSpec.from_profile(
        name or str(pipe.getName()),
        distance,
        elevation[:count],
        outside_diameter_m or float(pipe.getDiameter()),
        fields,
    )


# ------------------------------------------------------------ backend selection


@dataclass(frozen=True)
class BackendRecommendation:
    """Which tool to draw with, why, and what else would work."""

    backend: str
    rationale: str
    alternatives: tuple[str, ...]
    install: str
    available: bool


_BACKENDS: dict[str, tuple[str, str]] = {
    "pyvista": (
        "Results on geometry: scalar colouring, labels, cut views, off-screen PNG. "
        "The default for report figures.",
        "pip install pyvista",
    ),
    "cadquery": (
        "Exact solids exported as STEP for exchange with CAD and layout tools, plus STL and glTF.",
        "pip install cadquery",
    ),
    "openscad": (
        "A small readable .scad file that anyone can open and edit; no Python "
        "packages needed to write it.",
        "install OpenSCAD (openscad.org) and put it on PATH",
    ),
    "blender": (
        "Presentation render with materials, shadows and depth - for a front "
        "page or a slide, after the numbers are final.",
        "install Blender (blender.org) or pip install bpy",
    ),
}

PURPOSES = ("results_figure", "cad_exchange", "editable_model", "presentation_render")


def detect_backends() -> dict[str, bool]:
    """Which backends can run in this environment."""
    return {
        "pyvista": find_spec("pyvista") is not None,
        "cadquery": find_spec("cadquery") is not None,
        "openscad": which("openscad") is not None,
        "blender": which("blender") is not None or find_spec("bpy") is not None,
    }


def recommend_backend(purpose: str, *, has_field: bool = False) -> BackendRecommendation:
    """Pick the backend for a purpose; a calculated field always goes to PyVista first."""
    if purpose not in PURPOSES:
        raise ValueError(f"purpose must be one of {', '.join(PURPOSES)}")
    choice = {
        "results_figure": "pyvista",
        "cad_exchange": "cadquery",
        "editable_model": "openscad",
        "presentation_render": "blender",
    }[purpose]
    rationale, install = _BACKENDS[choice]
    if has_field and choice in ("cadquery", "openscad"):
        rationale += (
            " CAD solids carry no field values - render the coloured result with "
            "PyVista and export the plain geometry here."
        )
    alternatives = tuple(name for name in _BACKENDS if name != choice)
    return BackendRecommendation(
        backend=choice,
        rationale=rationale,
        alternatives=alternatives,
        install=install,
        available=detect_backends()[choice],
    )
