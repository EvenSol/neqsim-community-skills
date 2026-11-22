"""From a list of equipment and connections to a drawn process area.

A process model or a P&ID says what is connected to what, not where it stands.
This module supplies the missing part for a figure: it places the equipment in
flow order, routes each connection over a pipe rack and returns an ordinary
:class:`PlantSpec`. Positions from a layout study are used instead whenever
they are given.

The result is a schematic arrangement and is declared as such: an automatic
placement is not a plot plan, and the notes returned with the plant say which
positions, sizes and diameters were supplied and which were assumed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .mesh import Vec
from .model import Deck, _positive
from .plant import (
    EQUIPMENT_KINDS,
    STATUSES,
    VALVE_KINDS,
    Equipment,
    InlineValve,
    PipeRun,
    PlantSpec,
)

DEFAULT_SIZES: dict[str, tuple[float, ...]] = {
    "horizontal_vessel": (2.0, 6.0),
    "vertical_vessel": (1.5, 4.5),
    "column": (1.5, 12.0),
    "heat_exchanger": (0.8, 4.5),
    "pump": (1.8,),
    "compressor": (4.0,),
    "box": (2.5, 2.0, 2.0),
}


@dataclass(frozen=True)
class TopologyItem:
    """One equipment item of a process topology; ``size_m`` may be unknown."""

    tag: str
    kind: str
    size_m: tuple[float, ...] | None = None
    utilisation: float | None = None
    status: str = "existing"

    def __post_init__(self) -> None:
        if self.kind not in EQUIPMENT_KINDS:
            raise ValueError(f"item kind must be one of {', '.join(EQUIPMENT_KINDS)}")
        if self.status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")


@dataclass(frozen=True)
class TopologyConnection:
    """A line between two items. A missing end is a feed from, or a product to, the battery limit."""

    name: str
    source: str | None
    target: str | None
    diameter_m: float | None = None
    value: float | None = None
    valves: tuple[tuple[str, str], ...] = ()  # (tag, kind)
    status: str = "existing"

    def __post_init__(self) -> None:
        if self.source is None and self.target is None:
            raise ValueError(f"connection {self.name} has neither a source nor a target")
        if self.status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")
        for _tag, kind in self.valves:
            if kind not in VALVE_KINDS:
                raise ValueError(f"valve kind must be one of {', '.join(VALVE_KINDS)}")
        if self.diameter_m is not None:
            _positive("diameter_m", self.diameter_m)


@dataclass(frozen=True)
class ArrangedPlant:
    """A drawable plant plus the list of what was assumed to draw it."""

    plant: PlantSpec
    notes: tuple[str, ...]
    assumed_positions: tuple[str, ...] = field(default_factory=tuple)
    assumed_sizes: tuple[str, ...] = field(default_factory=tuple)
    assumed_diameters: tuple[str, ...] = field(default_factory=tuple)

    def scene(self, **options):
        """The scene of this plant, with every assumption carried into the caption.

        ``options`` are those of :func:`build_plant_scene`.
        """
        from .plant import build_plant_scene

        return build_plant_scene(
            self.plant,
            extra_notes=self.notes,
            true_scale=not (self.assumed_sizes or self.assumed_diameters),
            **options,
        )


def flow_levels(tags: Sequence[str], edges: Sequence[tuple[str, str]]) -> dict[str, int]:
    """Column index of each item in flow order (longest path, recycles ignored)."""
    outgoing: dict[str, list[str]] = {tag: [] for tag in tags}
    for source, target in edges:
        if source in outgoing and target in outgoing and source != target:
            outgoing[source].append(target)
    # Depth-first search marks back edges (recycles), which must not push items downstream.
    state: dict[str, int] = {}
    back: set[tuple[str, str]] = set()
    for root in tags:
        if root in state:
            continue
        stack = [(root, iter(outgoing[root]))]
        state[root] = 1
        while stack:
            node, children = stack[-1]
            for child in children:
                if state.get(child) == 1:
                    back.add((node, child))
                elif child not in state:
                    state[child] = 1
                    stack.append((child, iter(outgoing[child])))
                    break
            else:
                state[node] = 2
                stack.pop()
    level = {tag: 0 for tag in tags}
    for _ in range(len(tags)):
        changed = False
        for source in tags:
            for target in outgoing[source]:
                if (source, target) not in back and level[target] < level[source] + 1:
                    level[target] = level[source] + 1
                    changed = True
        if not changed:
            break
    return level


def _normal(item: Equipment, side: str) -> Vec:
    d, a = item.direction, item.across
    return {
        "top": (0.0, 0.0, 1.0),
        "bottom": (0.0, 0.0, -1.0),
        "inlet": (-d[0], -d[1], 0.0),
        "outlet": d,
        "front": (-a[0], -a[1], 0.0),
        "back": a,
    }[side]


def _is_vessel(item: Equipment) -> bool:
    return item.kind in ("horizontal_vessel", "vertical_vessel", "column")


def plant_from_topology(
    name: str,
    items: Sequence[TopologyItem],
    connections: Sequence[TopologyConnection],
    *,
    positions: Mapping[str, Sequence[float]] | None = None,
    default_pipe_diameter_m: float = 0.25,
    gap_m: float = 4.0,
    value_name: str | None = None,
    value_unit: str | None = None,
    deck: bool = True,
    notes: Sequence[str] = (),
) -> ArrangedPlant:
    """Place the items, route the connections and return a drawable plant.

    ``positions`` maps a tag to ``(x, y, z)`` or ``(x, y, z, rotation_deg)`` -
    the footprint centre at base level, for example from a layout study. Items
    without a position are placed in flow order, one column per step and
    stacked across the flow, ``gap_m`` apart. Each connection leaves its source,
    rises to a rack above the tallest item, crosses, and drops to its target.
    ``notes`` (the source of the topology, anything left out) lead the caption notes.
    """
    positions = dict(positions or {})
    tags = [item.tag for item in items]
    if len(set(tags)) != len(tags):
        raise ValueError("item tags must be unique")
    known = set(tags)
    for connection in connections:
        for end in (connection.source, connection.target):
            if end is not None and end not in known:
                raise ValueError(f"connection {connection.name} refers to unknown item {end!r}")
    _positive("default_pipe_diameter_m", default_pipe_diameter_m)

    assumed_sizes = tuple(item.tag for item in items if item.size_m is None)
    sizes = {item.tag: item.size_m or DEFAULT_SIZES[item.kind] for item in items}
    edges = [(c.source, c.target) for c in connections if c.source and c.target]
    level = flow_levels(tags, edges)

    # Automatic placement: columns in flow order, items of one column stacked across the flow.
    draft = {
        item.tag: Equipment(item.tag, item.kind, (0.0, 0.0, 0.0), sizes[item.tag]) for item in items
    }
    columns: dict[int, list[str]] = {}
    for tag in tags:
        columns.setdefault(level[tag], []).append(tag)
    placed: dict[str, tuple[float, float, float, float]] = {}
    x_cursor = 0.0
    for index in sorted(columns):
        members = columns[index]
        width = max(draft[tag].envelope()[0] for tag in members)
        y_cursor = 0.0
        for tag in members:
            depth = draft[tag].envelope()[1]
            placed[tag] = (x_cursor + width / 2.0, y_cursor + depth / 2.0, 0.0, 0.0)
            y_cursor += depth + gap_m
        x_cursor += width + gap_m
    assumed_positions = []
    for tag in tags:
        if tag in positions:
            given = [float(v) for v in positions[tag]]
            if len(given) not in (3, 4):
                raise ValueError(f"position of {tag} must be (x, y, z) or (x, y, z, rotation_deg)")
            placed[tag] = (given[0], given[1], given[2], given[3] if len(given) == 4 else 0.0)
        else:
            assumed_positions.append(tag)

    equipment = {
        item.tag: Equipment(
            item.tag,
            item.kind,
            placed[item.tag][:3],
            sizes[item.tag],
            placed[item.tag][3],
            item.utilisation,
            item.status,
        )
        for item in items
    }

    tops = [e.position[2] + e.envelope()[2] for e in equipment.values()]
    rack = (max(tops) if tops else 0.0) + 1.0
    xs = [e.position[0] for e in equipment.values()] or [0.0]
    ys = [e.position[1] for e in equipment.values()] or [0.0]
    reach = max((max(e.envelope()[0], e.envelope()[1]) for e in equipment.values()), default=2.0)
    limit_low, limit_high = min(xs) - reach / 2.0 - gap_m, max(xs) + reach / 2.0 + gap_m

    leaving: dict[str, int] = {}
    arriving: dict[str, int] = {}
    pipes = []
    assumed_diameters = []
    for index, connection in enumerate(connections):
        diameter = connection.diameter_m
        if diameter is None:
            diameter = default_pipe_diameter_m
            assumed_diameters.append(connection.name)
        lane = rack + 0.6 * (index % 4)
        stub = max(1.0, 3.0 * diameter)

        def end_point(tag: str, outgoing: bool) -> tuple[Vec, Vec]:
            item = equipment[tag]
            counts = leaving if outgoing else arriving
            order = counts.get(tag, 0)
            counts[tag] = order + 1
            if outgoing:
                side = ("top" if order == 0 else "outlet") if _is_vessel(item) else "outlet"
                along = 0.8
            else:
                side = "inlet" if order == 0 or not _is_vessel(item) else "top"
                along = 0.5 if order == 0 else 0.2
            port = item.port(side, along)
            normal = _normal(item, side)
            if side == "top":
                return port, (port[0], port[1], lane)
            return port, (port[0] + normal[0] * stub, port[1] + normal[1] * stub, port[2])

        path: list[Vec] = []
        if connection.source is not None:
            start, start_out = end_point(connection.source, True)
            path += [start, start_out, (start_out[0], start_out[1], lane)]
        if connection.target is not None:
            end, end_in = end_point(connection.target, False)
        if connection.source is None:
            path += [(limit_low, end_in[1], lane)]
        if connection.target is None:
            last = path[-1]
            path += [(limit_high, last[1], lane)]
        else:
            last = path[-1]
            path += [(end_in[0], last[1], lane), (end_in[0], end_in[1], lane), end_in, end]

        run = PipeRun(
            connection.name, tuple(path), diameter, connection.value, (), connection.status
        )
        valves = _place_valves(run, connection.valves)
        pipes.append(
            PipeRun(
                connection.name, run.points, diameter, connection.value, valves, connection.status
            )
        )

    decks: tuple[Deck, ...] = ()
    if deck and equipment:
        base = min(e.position[2] for e in equipment.values())
        halves = [max(e.envelope()[0], e.envelope()[1]) / 2.0 for e in equipment.values()]
        low_y = min(y - half for y, half in zip(ys, halves))
        high_y = max(y + half for y, half in zip(ys, halves))
        decks = (
            Deck(
                "Deck",
                limit_low - gap_m / 2.0,
                limit_high + gap_m / 2.0,
                low_y - gap_m,
                high_y + gap_m,
                base,
            ),
        )

    source_notes = tuple(notes)
    notes = list(source_notes)
    if assumed_positions:
        notes.append(
            f"{len(assumed_positions)} of {len(tags)} items placed automatically in flow order - "
            "a schematic arrangement, not a plot plan"
        )
    if assumed_sizes:
        notes.append(f"{len(assumed_sizes)} items drawn at a default envelope size")
    if assumed_diameters:
        notes.append(
            f"{len(assumed_diameters)} lines drawn at an assumed "
            f"{default_pipe_diameter_m * 1000.0:.0f} mm diameter"
        )
    notes.append("Lines are routed automatically over a rack; routes are schematic")
    plant = PlantSpec(
        name,
        tuple(equipment[tag] for tag in tags),
        tuple(pipes),
        decks,
        value_name if any(p.value is not None for p in pipes) else None,
        value_unit if any(p.value is not None for p in pipes) else None,
    )
    return ArrangedPlant(
        plant,
        tuple(notes),
        tuple(assumed_positions),
        assumed_sizes,
        tuple(assumed_diameters),
    )


def _place_valves(run: PipeRun, valves: Sequence[tuple[str, str]]) -> tuple[InlineValve, ...]:
    """Spread valves along the longest straight leg of a run, clear of the bends."""
    if not valves:
        return ()
    total = run.length_m
    best_start, best_length, travelled = 0.0, 0.0, 0.0
    for a, b in zip(run.points[:-1], run.points[1:]):
        length = sum((b[i] - a[i]) ** 2 for i in range(3)) ** 0.5
        if length > best_length:
            best_start, best_length = travelled, length
        travelled += length
    placed = []
    for index, (tag, kind) in enumerate(valves):
        offset = best_length * (index + 1) / (len(valves) + 1)
        fraction = min(max((best_start + offset) / total, 0.01), 0.99)
        placed.append(InlineValve(tag, fraction, kind))
    return tuple(placed)
