"""A process plant in 3D: equipment, valves and routed piping carrying results.

Equipment is drawn as recognisable envelope shapes (a vessel with heads, an
exchanger with its flanges, a pump with casing and motor), valves as a flanged
body with a handwheel or actuator, and piping as true-diameter tubes with
rounded bends. Each pipe run can carry one calculated value - a temperature, a
pressure, a velocity - and all runs share one colour scale.

Everything is composed from the same primitive kinds as the rest of the skill,
so every backend draws it without knowing what a valve is.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, pi, sin, sqrt
from typing import Any, Sequence

from .mesh import Vec
from .model import (
    PALETTE,
    UTILISATION_LEGEND,
    Deck,
    Label,
    Primitive,
    Scene,
    _finite,
    _positive,
    _slug,
    colormap,
    utilisation_color,
    vessel_profile,
)

EQUIPMENT_KINDS = (
    "horizontal_vessel",
    "vertical_vessel",
    "column",
    "heat_exchanger",
    "pump",
    "compressor",
    "box",
)
VALVE_KINDS = ("manual", "control", "check")
STATUSES = ("existing", "new", "modified")
# Tie-in colouring: what is there today stays neutral, what the solution adds stands out.
STATUS_COLORS = {
    "existing": (0.66, 0.68, 0.71),
    "new": (0.10, 0.45, 0.85),
    "modified": (0.93, 0.55, 0.10),
}
STATUS_LEGEND = "Colour by status: new in blue, modified in orange, existing in grey"
PORT_SIDES = ("top", "bottom", "inlet", "outlet", "front", "back")
_SIZE_COUNT = {
    "horizontal_vessel": 2,  # diameter, tan-tan length
    "vertical_vessel": 2,  # diameter, overall height
    "column": 2,  # diameter, overall height
    "heat_exchanger": 2,  # shell diameter, overall length
    "pump": 1,  # overall length
    "compressor": 1,  # overall length
    "box": 3,  # length, width, height
}


def _add(a: Sequence[float], b: Sequence[float], scale: float = 1.0) -> Vec:
    return (a[0] + scale * b[0], a[1] + scale * b[1], a[2] + scale * b[2])


def _length(a: Sequence[float], b: Sequence[float]) -> float:
    return sqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2 + (b[2] - a[2]) ** 2)


@dataclass(frozen=True)
class Equipment:
    """One equipment item. ``position`` is the centre of its footprint at base level.

    ``size_m`` depends on ``kind``: ``(diameter, length)`` for a horizontal
    vessel or heat exchanger, ``(diameter, height)`` for a vertical vessel or
    column, ``(length,)`` for a pump or compressor and ``(length, width,
    height)`` for a box. ``rotation_deg`` turns the item about the vertical;
    at zero its long axis runs along ``x`` with the inlet end at low ``x``.
    ``status`` marks the item as ``existing``, ``new`` or ``modified`` for a
    tie-in or modification figure.
    """

    tag: str
    kind: str
    position: Vec
    size_m: tuple[float, ...]
    rotation_deg: float = 0.0
    utilisation: float | None = None
    status: str = "existing"

    def __post_init__(self) -> None:
        if self.kind not in EQUIPMENT_KINDS:
            raise ValueError(f"equipment kind must be one of {', '.join(EQUIPMENT_KINDS)}")
        if self.status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")
        if len(self.size_m) != _SIZE_COUNT[self.kind]:
            raise ValueError(f"{self.kind} needs {_SIZE_COUNT[self.kind]} size value(s)")
        for value in self.size_m:
            _positive("size_m", value)
        for value in self.position:
            _finite("position", value)
        if self.utilisation is not None and _finite("utilisation", self.utilisation) < 0.0:
            raise ValueError("utilisation must not be negative")

    @property
    def direction(self) -> Vec:
        """Unit vector of the long axis."""
        return (cos(self.rotation_deg * pi / 180.0), sin(self.rotation_deg * pi / 180.0), 0.0)

    @property
    def across(self) -> Vec:
        d = self.direction
        return (-d[1], d[0], 0.0)

    def envelope(self) -> tuple[float, float, float, float]:
        """``(length, width, height, axis height)`` of the drawn envelope."""
        s = self.size_m
        if self.kind == "horizontal_vessel":
            return s[1] + s[0] / 2.0, s[0], 1.3 * s[0], 0.8 * s[0]
        if self.kind == "heat_exchanger":
            return s[1], 1.25 * s[0], 1.3 * s[0] + 0.125 * s[0], 0.8 * s[0]
        if self.kind in ("vertical_vessel", "column"):
            return s[0], s[0], s[1], s[1] / 2.0
        if self.kind in ("pump", "compressor"):
            return s[0], 0.45 * s[0], 0.56 * s[0], 0.31 * s[0]
        return s[0], s[1], s[2], s[2] / 2.0

    def port(self, side: str, along: float = 0.5) -> Vec:
        """A connection point on the envelope, for starting or ending a pipe run.

        ``top`` and ``bottom`` sit on the centreline at ``along`` (0 = inlet
        end, 1 = outlet end); ``inlet`` and ``outlet`` are the two ends at axis
        height; ``front`` and ``back`` are the two sides at axis height. For a
        vertical item ``along`` is the height fraction of a side connection.
        """
        if side not in PORT_SIDES:
            raise ValueError(f"port side must be one of {', '.join(PORT_SIDES)}")
        if not 0.0 <= along <= 1.0:
            raise ValueError("along must be between 0 and 1")
        length, width, height, axis_height = self.envelope()
        d, a, p = self.direction, self.across, self.position
        vertical = self.kind in ("vertical_vessel", "column")
        if vertical:
            if side == "top":
                return (p[0], p[1], p[2] + height)
            if side == "bottom":
                return (p[0], p[1], p[2])
            z = p[2] + along * height
            offset = {"inlet": (d, -1.0), "outlet": (d, 1.0), "front": (a, -1.0), "back": (a, 1.0)}
            vector, sign = offset[side]
            return _add((p[0], p[1], z), vector, sign * width / 2.0)
        station = _add(p, d, (along - 0.5) * length * 0.8)
        if side == "top":
            return (station[0], station[1], p[2] + height)
        if side == "bottom":
            base = p[2] + (axis_height - (height - axis_height) if self.kind != "box" else 0.0)
            return (station[0], station[1], max(base, p[2]))
        centre = (p[0], p[1], p[2] + axis_height)
        if side == "inlet":
            return _add(centre, d, -length / 2.0)
        if side == "outlet":
            return _add(centre, d, length / 2.0)
        mid = (station[0], station[1], p[2] + axis_height)
        return _add(mid, a, (-1.0 if side == "front" else 1.0) * width / 2.0)


@dataclass(frozen=True)
class InlineValve:
    """A valve on a pipe run at ``fraction`` of the run's routed length."""

    tag: str
    fraction: float = 0.5
    kind: str = "manual"

    def __post_init__(self) -> None:
        if self.kind not in VALVE_KINDS:
            raise ValueError(f"valve kind must be one of {', '.join(VALVE_KINDS)}")
        if not 0.0 < _finite("fraction", self.fraction) < 1.0:
            raise ValueError("valve fraction must be between 0 and 1")


@dataclass(frozen=True)
class PipeRun:
    """A pipe from point to point through its corners, with an optional result value."""

    name: str
    points: tuple[Vec, ...]
    outside_diameter_m: float
    value: float | None = None
    valves: tuple[InlineValve, ...] = ()
    status: str = "existing"

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")
        points = tuple(
            (_finite("x", p[0]), _finite("y", p[1]), _finite("z", p[2])) for p in self.points
        )
        cleaned = [points[0]] if points else []
        for point in points[1:]:
            if _length(cleaned[-1], point) > 1e-9:
                cleaned.append(point)
        if len(cleaned) < 2:
            raise ValueError(f"pipe run {self.name} needs at least two distinct points")
        _positive("outside_diameter_m", self.outside_diameter_m)
        if self.value is not None:
            _finite("value", self.value)
        object.__setattr__(self, "points", tuple(cleaned))
        object.__setattr__(self, "valves", tuple(self.valves))

    @property
    def length_m(self) -> float:
        return sum(_length(a, b) for a, b in zip(self.points[:-1], self.points[1:]))

    def point_at(self, fraction: float) -> tuple[Vec, Vec]:
        """Position and unit direction at a fraction of the routed length."""
        target = fraction * self.length_m
        for a, b in zip(self.points[:-1], self.points[1:]):
            segment = _length(a, b)
            if target <= segment or b == self.points[-1]:
                t = min(max(target / segment, 0.0), 1.0)
                direction = (
                    (b[0] - a[0]) / segment,
                    (b[1] - a[1]) / segment,
                    (b[2] - a[2]) / segment,
                )
                return _add(a, direction, t * segment), direction
            target -= segment
        raise AssertionError("unreachable")


def route(start: Sequence[float], end: Sequence[float], order: str = "zxy") -> tuple[Vec, ...]:
    """An axis-parallel route from ``start`` to ``end``, moving along the axes in ``order``.

    ``order="zxy"`` rises (or drops) first, then runs along ``x``, then ``y`` -
    a pipe leaving the top of a vessel. Use two calls through a pipe-rack
    elevation for anything more elaborate.
    """
    if sorted(order) != ["x", "y", "z"]:
        raise ValueError("order must be a permutation of 'xyz'")
    current = [float(start[0]), float(start[1]), float(start[2])]
    points: list[Vec] = [(current[0], current[1], current[2])]
    for axis in order:
        index = "xyz".index(axis)
        if abs(end[index] - current[index]) > 1e-9:
            current[index] = float(end[index])
            points.append((current[0], current[1], current[2]))
    return tuple(points)


def _rounded(points: Sequence[Vec], bend_radius: float, steps: int = 6) -> tuple[Vec, ...]:
    """Replace each corner with a short arc so a tube shows a bend, not a mitre."""
    if len(points) < 3:
        return tuple(points)
    result: list[Vec] = [points[0]]
    for before, corner, after in zip(points[:-2], points[1:-1], points[2:]):
        length_in, length_out = _length(before, corner), _length(corner, after)
        cut = min(bend_radius, 0.45 * length_in, 0.45 * length_out)
        if cut <= 1e-9:
            result.append(corner)
            continue
        start = _add(corner, [(before[i] - corner[i]) / length_in for i in range(3)], cut)
        end = _add(corner, [(after[i] - corner[i]) / length_out for i in range(3)], cut)
        for k in range(steps + 1):
            t = k / steps
            # Quadratic Bezier through the corner: tangent to both legs.
            result.append(
                tuple(
                    (1 - t) ** 2 * start[i] + 2 * (1 - t) * t * corner[i] + t * t * end[i]
                    for i in range(3)
                )  # type: ignore[arg-type]
            )
    result.append(points[-1])
    return tuple(result)


@dataclass(frozen=True)
class PlantSpec:
    """Equipment and piping of a process area, with one result value shown on the pipes."""

    name: str
    equipment: tuple[Equipment, ...]
    pipes: tuple[PipeRun, ...] = ()
    decks: tuple[Deck, ...] = ()
    value_name: str | None = None
    value_unit: str | None = None

    def __post_init__(self) -> None:
        equipment, pipes = tuple(self.equipment), tuple(self.pipes)
        if not equipment and not pipes:
            raise ValueError("a plant needs at least one equipment item or pipe run")
        tags = [e.tag for e in equipment] + [v.tag for p in pipes for v in p.valves]
        if len(set(tags)) != len(tags):
            raise ValueError("equipment and valve tags must be unique")
        if len({p.name for p in pipes}) != len(pipes):
            raise ValueError("pipe run names must be unique")
        if any(p.value is not None for p in pipes) and not self.value_name:
            raise ValueError("value_name is required when pipe runs carry a value")
        object.__setattr__(self, "equipment", equipment)
        object.__setattr__(self, "pipes", pipes)
        object.__setattr__(self, "decks", tuple(self.decks))

    def equipment_by_tag(self, tag: str) -> Equipment:
        for item in self.equipment:
            if item.tag == tag:
                return item
        raise KeyError(f"no equipment tagged {tag!r}")


def _horizontal_cylinder(
    name: str, role: str, color: Any, start: Vec, direction: Vec, radius: float, length: float
) -> Primitive:
    return Primitive(
        name=name,
        kind="cylinder",
        role=role,
        color=color,
        params={"base": start, "axis": direction, "radius": radius, "height": length},
    )


def _equipment_primitives(item: Equipment, color: Any) -> list[Primitive]:
    p, d = item.position, item.direction
    length, width, height, axis_height = item.envelope()
    centre = (p[0], p[1], p[2] + axis_height)
    parts: list[Primitive] = []

    def box(name: str, role: str, tint: Any, middle: Vec, size: tuple[float, float, float]) -> None:
        parts.append(
            Primitive(
                name=f"{item.tag} {name}",
                kind="box",
                role=role,
                color=tint,
                params={"center": middle, "size": size, "rotation_z_deg": item.rotation_deg},
            )
        )

    if item.kind == "box":
        box("body", "equipment", color, centre, (length, width, height))
    elif item.kind in ("vertical_vessel", "column"):
        diameter, overall = item.size_m
        depth = diameter / 4.0
        parts.append(
            Primitive(
                name=item.tag,
                kind="revolved",
                role="equipment",
                color=color,
                params={
                    "profile": vessel_profile(
                        diameter / 2.0, max(overall - 2.0 * depth, 1e-6), depth, points_per_head=10
                    ),
                    "origin": (p[0], p[1], p[2] + depth),
                    "axis": (0.0, 0.0, 1.0),
                    "segments": 40,
                },
            )
        )
    elif item.kind == "horizontal_vessel":
        diameter, tan_tan = item.size_m
        parts.append(
            Primitive(
                name=item.tag,
                kind="revolved",
                role="equipment",
                color=color,
                params={
                    "profile": vessel_profile(
                        diameter / 2.0, tan_tan, diameter / 4.0, points_per_head=10
                    ),
                    "origin": _add(centre, d, -tan_tan / 2.0),
                    "axis": d,
                    "segments": 40,
                },
            )
        )
        for index, fraction in enumerate((-0.3, 0.3)):
            foot = _add(p, d, fraction * tan_tan)
            box(
                f"saddle {index + 1}",
                "support",
                PALETTE["support"],
                (foot[0], foot[1], p[2] + 0.2 * diameter),
                (min(0.08 * tan_tan, 0.5), 0.7 * diameter, 0.4 * diameter),
            )
    elif item.kind == "heat_exchanger":
        diameter, overall = item.size_m
        radius = diameter / 2.0
        start = _add(centre, d, -overall / 2.0)
        parts.append(_horizontal_cylinder(item.tag, "equipment", color, start, d, radius, overall))
        for index, fraction in enumerate((0.14, 0.86)):
            parts.append(
                _horizontal_cylinder(
                    f"{item.tag} flange {index + 1}",
                    "nozzle",
                    PALETTE["nozzle"],
                    _add(start, d, fraction * overall - 0.02 * overall),
                    d,
                    1.25 * radius,
                    0.04 * overall,
                )
            )
        for index, fraction in enumerate((-0.28, 0.28)):
            foot = _add(p, d, fraction * overall)
            box(
                f"saddle {index + 1}",
                "support",
                PALETTE["support"],
                (foot[0], foot[1], p[2] + 0.2 * diameter),
                (min(0.06 * overall, 0.4), 0.7 * diameter, 0.4 * diameter),
            )
    else:  # pump or compressor: casing, coupling, driver, baseplate
        casing_radius = 0.25 * length if item.kind == "compressor" else 0.22 * length
        casing_length = 0.42 * length if item.kind == "compressor" else 0.2 * length
        driver_radius = 0.17 * length
        start = _add(centre, d, -length / 2.0)
        parts.append(
            _horizontal_cylinder(
                item.tag, "equipment", color, start, d, casing_radius, casing_length
            )
        )
        parts.append(
            _horizontal_cylinder(
                f"{item.tag} coupling",
                "nozzle",
                PALETTE["nozzle"],
                _add(start, d, casing_length),
                d,
                0.05 * length,
                0.12 * length,
            )
        )
        parts.append(
            _horizontal_cylinder(
                f"{item.tag} driver",
                "support",
                PALETTE["nozzle"],
                _add(start, d, casing_length + 0.12 * length),
                d,
                driver_radius,
                length - casing_length - 0.12 * length,
            )
        )
        box(
            "baseplate",
            "support",
            PALETTE["support"],
            (p[0], p[1], p[2] + 0.03 * length),
            (length, width, 0.06 * length),
        )
    return parts


def _valve_primitives(
    valve: InlineValve, centre: Vec, direction: Vec, pipe_radius: float, body_color: Any = None
) -> tuple[list[Primitive], Vec]:
    """Body, flanges and operator of a valve; returns the parts and the label anchor."""
    body_color = body_color or PALETTE["internal"]
    body_half = 2.2 * pipe_radius
    body_radius = 1.9 * pipe_radius
    start = _add(centre, direction, -body_half)
    parts = [
        Primitive(
            name=f"{valve.tag} body",
            kind="revolved",
            role="internal",
            color=body_color,
            params={
                # Two cones meeting at the seat - the valve symbol turned into a solid.
                "profile": [
                    (0.0, 0.0),
                    (0.0, body_radius),
                    (body_half, 1.05 * pipe_radius),
                    (2.0 * body_half, body_radius),
                    (2.0 * body_half, 0.0),
                ],
                "origin": start,
                "axis": direction,
                "segments": 32,
            },
        )
    ]
    for index, offset in enumerate((-body_half - 0.3 * pipe_radius, body_half)):
        parts.append(
            Primitive(
                name=f"{valve.tag} flange {index + 1}",
                kind="cylinder",
                role="nozzle",
                color=PALETTE["nozzle"],
                params={
                    "base": _add(centre, direction, offset),
                    "axis": direction,
                    "radius": 2.1 * pipe_radius,
                    "height": 0.3 * pipe_radius,
                },
            )
        )
    # The operator points up, or sideways when the pipe itself is vertical.
    up: Vec = (0.0, 0.0, 1.0) if abs(direction[2]) < 0.9 else (0.0, 1.0, 0.0)
    anchor = _add(centre, up, body_radius)
    if valve.kind != "check":
        stem = 3.0 * pipe_radius
        parts.append(
            Primitive(
                name=f"{valve.tag} stem",
                kind="cylinder",
                role="nozzle",
                color=PALETTE["nozzle"],
                params={
                    "base": centre,
                    "axis": up,
                    "radius": 0.3 * pipe_radius,
                    "height": stem + pipe_radius,
                },
            )
        )
        top = _add(centre, up, stem + pipe_radius)
        if valve.kind == "control":
            parts.append(
                Primitive(
                    name=f"{valve.tag} actuator",
                    kind="revolved",
                    role="internal",
                    color=body_color,
                    params={
                        "profile": vessel_profile(
                            2.4 * pipe_radius,
                            0.6 * pipe_radius,
                            1.0 * pipe_radius,
                            points_per_head=8,
                        ),
                        "origin": _add(top, up, 1.0 * pipe_radius),
                        "axis": up,
                        "segments": 32,
                    },
                )
            )
            anchor = _add(top, up, 2.7 * pipe_radius)
        else:
            parts.append(
                Primitive(
                    name=f"{valve.tag} handwheel",
                    kind="cylinder",
                    role="nozzle",
                    color=PALETTE["nozzle"],
                    params={
                        "base": top,
                        "axis": up,
                        "radius": 2.0 * pipe_radius,
                        "height": 0.25 * pipe_radius,
                    },
                )
            )
            anchor = _add(top, up, 0.4 * pipe_radius)
    return parts, anchor


def build_plant_scene(
    spec: PlantSpec,
    *,
    colormap_name: str = "viridis",
    bend_radius_diameters: float = 1.5,
    label_pipes: bool = True,
    color_by: str = "auto",
    extra_notes: Sequence[str] = (),
    true_scale: bool = True,
    title: str | None = None,
) -> Scene:
    """Scene for a process area, drawn to scale unless ``true_scale`` is cleared.

    ``extra_notes`` are added to the caption - an automatic arrangement uses
    them to say which positions, sizes and diameters were assumed.

    ``color_by="results"`` colours pipe runs by their value on one shared scale
    (named by ``spec.value_name``) and equipment by utilisation on the fixed
    green-amber-red legend. ``color_by="status"`` shows a tie-in or
    modification instead: new items in blue, modified in orange, existing in
    grey, with values and utilisation kept as labels. ``"auto"`` picks
    ``status`` as soon as anything is marked new or modified.
    """
    if color_by not in ("auto", "results", "status"):
        raise ValueError("color_by must be 'auto', 'results' or 'status'")
    changed = [e.tag for e in spec.equipment if e.status != "existing"] + [
        p.name for p in spec.pipes if p.status != "existing"
    ]
    by_status = color_by == "status" or (color_by == "auto" and bool(changed))
    primitives: list[Primitive] = []
    labels: list[Label] = []
    notes = [
        f"{len(spec.equipment)} equipment items, {len(spec.pipes)} pipe runs, "
        f"{sum(len(p.valves) for p in spec.pipes)} valves"
    ]
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

    utilised = False
    for item in spec.equipment:
        color = PALETTE["equipment"]
        text = item.tag
        if item.utilisation is not None:
            text = f"{item.tag}  {100.0 * item.utilisation:.0f} %"
            if not by_status:
                color = utilisation_color(item.utilisation)
                utilised = True
        if by_status:
            color = STATUS_COLORS[item.status]
            if item.status != "existing":
                text += f"  ({item.status})"
        primitives.extend(_equipment_primitives(item, color))
        _length_, _width, height, _axis = item.envelope()
        labels.append(
            Label(text, (item.position[0], item.position[1], item.position[2] + height), "tag")
        )

    values = [p.value for p in spec.pipes if p.value is not None]
    value_range = (min(values), max(values)) if values else None
    for pipe in spec.pipes:
        radius = pipe.outside_diameter_m / 2.0
        path = _rounded(pipe.points, bend_radius_diameters * pipe.outside_diameter_m)
        scalars = None
        color = PALETTE["pipeline"]
        if by_status:
            color = STATUS_COLORS[pipe.status]
        elif pipe.value is not None and value_range is not None:
            scalars = tuple(pipe.value for _ in path)
            color = colormap(pipe.value, value_range[0], value_range[1], colormap_name)
        primitives.append(
            Primitive(
                name=pipe.name,
                kind="tube",
                role="pipeline",
                color=color,
                params={"points": path, "radius": radius},
                scalars=scalars,
                scalar_name=spec.value_name if scalars else None,
                scalar_unit=spec.value_unit if scalars else None,
                scalar_range=value_range if scalars else None,
            )
        )
        if label_pipes and pipe.value is not None:
            middle, _direction = pipe.point_at(0.5 if not pipe.valves else 0.25)
            unit = f" {spec.value_unit}" if spec.value_unit else ""
            labels.append(
                Label(
                    f"{pipe.value:.4g}{unit}",
                    (middle[0], middle[1], middle[2] + 1.5 * radius),
                    "field",
                )
            )
        for valve in pipe.valves:
            centre, direction = pipe.point_at(valve.fraction)
            parts, anchor = _valve_primitives(
                valve, centre, direction, radius, STATUS_COLORS[pipe.status] if by_status else None
            )
            primitives.extend(parts)
            labels.append(Label(valve.tag, anchor, "valve"))

    if by_status:
        notes.append(STATUS_LEGEND)
        new = sum(1 for e in spec.equipment if e.status == "new")
        modified = sum(1 for e in spec.equipment if e.status == "modified")
        lines = sum(1 for p in spec.pipes if p.status != "existing")
        notes.append(
            f"{new} new and {modified} modified equipment items, {lines} new or modified lines"
        )
        if value_range is not None:
            notes.append(f"Line labels show {spec.value_name} [{spec.value_unit or '-'}]")
    elif value_range is not None:
        unit = f" [{spec.value_unit}]" if spec.value_unit else ""
        notes.append(
            f"Pipe colour: {spec.value_name}{unit}, {value_range[0]:.4g} to {value_range[1]:.4g}"
        )
    if utilised:
        notes.append(UTILISATION_LEGEND)
    notes.extend(extra_notes)
    notes.append(
        "Equipment and valves shown as envelope shapes"
        + ("" if extra_notes else "; pipe routes as supplied")
    )
    return Scene(
        name=_slug(spec.name),
        title=title or f"{spec.name} - process area",
        primitives=tuple(primitives),
        labels=tuple(labels),
        notes=tuple(notes),
        true_scale=true_scale,
    )
