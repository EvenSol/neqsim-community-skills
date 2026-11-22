"""Adapters from NeqSim's own data to a drawable plant or vessel.

Everything here reads what the NeqSim main repository already produces, so the
figure follows the model instead of a second, hand-typed description of it:

* a ``ProcessSystem`` (``buildGraph()``) - equipment, connections, valves,
  stream conditions and capacity utilisation;
* a DEXPI P&ID, through ``DexpiXmlReader`` and ``DexpiTopologyResolver`` -
  tagged equipment, piping segments, inline valves and nominal diameters;
* the design-data JSON of ``MechanicalDesign.toDesignDataJson()`` - vessel
  diameters, wall thickness and tangent length;
* the layout dataset of ``neqsim layout-study`` - real equipment positions.

NeqSim itself is optional: the functions that need it import it when called,
and the ones that read plain JSON or dictionaries need nothing.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from .model import VesselSpec
from .topology import ArrangedPlant, TopologyConnection, TopologyItem, plant_from_topology

# Unit conversions and names for the stream value shown on the lines.
STREAM_VALUES = {
    "temperature": ("Temperature", "C", lambda s: float(s.getTemperature("C"))),
    "pressure": ("Pressure", "bara", lambda s: float(s.getPressure("bara"))),
    "mass_flow": ("Mass flow", "kg/hr", lambda s: float(s.getFlowRate("kg/hr"))),
}


def equipment_kind(type_name: str, orientation: str | None = None) -> str | None:
    """Drawing kind for a NeqSim equipment or DEXPI class name; ``None`` if it is not drawn.

    Streams, mixers, splitters, recycles and other flowsheet logic have no
    body of their own and return ``None``; valves return ``"valve"``.
    """
    name = type_name.lower()
    if "valve" in name:
        return "valve"
    if any(word in name for word in ("column", "absorber", "stripper", "distillation", "tower")):
        return "column"
    if any(word in name for word in ("compressor", "expander", "turbine", "blower", "fan")):
        return "compressor"
    if "pump" in name:
        return "pump"
    if any(
        word in name
        for word in ("heatexchanger", "heater", "cooler", "exchanger", "reboiler", "condenser")
    ):
        return "heat_exchanger"
    if any(word in name for word in ("scrubber", "tank", "drum", "vessel")):
        return "horizontal_vessel" if orientation == "horizontal" else "vertical_vessel"
    if "separator" in name:
        return "vertical_vessel" if orientation == "vertical" else "horizontal_vessel"
    if any(
        word in name
        for word in ("filter", "reactor", "electrolyzer", "ejector", "flare", "adsorber")
    ):
        return "box"
    return None


def valve_kind(type_name: str) -> str:
    """``check``, ``control`` or ``manual`` from a valve class name."""
    name = type_name.lower()
    if "check" in name or "nonreturn" in name:
        return "check"
    if any(word in name for word in ("control", "throttling", "operated", "choke", "actuated")):
        return "control"
    return "manual"


def nominal_diameter_m(text: str | None) -> float | None:
    """Metres from a nominal-diameter string such as ``DN 80`` or ``6"``; ``None`` if unreadable.

    The nominal size is used as the drawn diameter. It is a designation, not
    the outside diameter, which is close enough for a figure and said so.
    """
    if not text:
        return None
    text = str(text)  # a java.lang.String when it comes straight from NeqSim
    metric = re.search(r"DN\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if metric:
        return float(metric.group(1)) / 1000.0
    inches = re.search(r"(\d+(?:\.\d+)?)\s*(?:\"|in\b|inch)", text, re.IGNORECASE)
    if inches:
        return float(inches.group(1)) * 0.0254
    return None


def _statuses(tag: str, new: Sequence[str], modified: Sequence[str]) -> str:
    if tag in new:
        return "new"
    if tag in modified:
        return "modified"
    return "existing"


def _line_status(source, target, valves, new: Sequence[str], modified: Sequence[str]) -> str:
    """A line is new when it serves a new item or carries a new valve.

    A line to equipment that is only modified stays existing unless one of
    its own valves is marked - changing a vessel does not replace its piping.
    """
    valve_tags = [tag for tag, _kind in valves]
    if any(tag in new for tag in [source, target, *valve_tags] if tag is not None):
        return "new"
    if any(tag in modified for tag in valve_tags):
        return "modified"
    return "existing"


# ------------------------------------------------------------- ProcessSystem


def plant_from_neqsim_process(
    process: Any,
    *,
    name: str | None = None,
    value: str | None = "temperature",
    positions: Mapping[str, Sequence[float]] | None = None,
    new_tags: Sequence[str] = (),
    modified_tags: Sequence[str] = (),
    **arrange: Any,
) -> ArrangedPlant:
    """Draw a NeqSim ``ProcessSystem``: equipment, lines, valves and stream results.

    The process graph from ``ProcessSystem.buildGraph()`` is reduced to what
    has a body: vessels, columns, exchangers, pumps and compressors become
    equipment; valves sit on the line they are in; streams, mixers, splitters
    and recycles are passed through. Each line carries the chosen stream
    ``value`` (``temperature``, ``pressure``, ``mass_flow`` or ``None``) when
    the process has been run. Separator dimensions come from
    ``getInternalDiameter()`` / ``getSeparatorLength()`` and utilisation from
    ``getMaxUtilization()`` where the equipment reports them. ``new_tags`` and
    ``modified_tags`` mark the tie-in scope. ``arrange`` options go to
    :func:`plant_from_topology`.
    """
    if value is not None and value not in STREAM_VALUES:
        raise ValueError(f"value must be one of {', '.join(STREAM_VALUES)} or None")
    graph = process.buildGraph()
    nodes = list(graph.getNodes())
    kinds: dict[str, str | None] = {}
    items: list[TopologyItem] = []
    for node in nodes:
        tag = str(node.getName())
        unit = node.getEquipment()
        orientation = None
        if hasattr(unit, "getOrientation"):
            try:
                orientation = str(unit.getOrientation()).lower()
            except Exception:  # noqa: BLE001 - orientation is optional information
                orientation = None
        kind = equipment_kind(str(node.getEquipmentType()), orientation)
        kinds[tag] = kind
        if kind is None or kind == "valve":
            continue
        size = None
        if kind in ("horizontal_vessel", "vertical_vessel") and hasattr(
            unit, "getInternalDiameter"
        ):
            try:
                diameter, length = (
                    float(unit.getInternalDiameter()),
                    float(unit.getSeparatorLength()),
                )
                if diameter > 0.0 and length > 0.0:
                    size = (diameter, length)
            except Exception:  # noqa: BLE001 - fall back to the default envelope
                size = None
        utilisation = None
        if hasattr(unit, "getMaxUtilization"):
            try:
                candidate = float(unit.getMaxUtilization())
                if candidate == candidate and 0.0 < candidate < 1.0e6:
                    utilisation = candidate
            except Exception:  # noqa: BLE001 - no capacity constraints defined
                utilisation = None
        items.append(
            TopologyItem(tag, kind, size, utilisation, _statuses(tag, new_tags, modified_tags))
        )

    def stream_value(edge: Any) -> float | None:
        if value is None:
            return None
        try:
            result = STREAM_VALUES[value][2](edge.getStream())
        except Exception:  # noqa: BLE001 - not run, or not a material stream
            return None
        return result if result == result else None

    connections: list[TopologyConnection] = []
    seen: set[tuple[str | None, str | None, tuple[str, ...]]] = set()

    def walk(start: Any, source: str | None) -> None:
        """Follow the flow from ``start`` through undrawn nodes to the next drawn item."""
        stack = [(edge, (), None) for edge in start.getOutgoingEdges()]
        visited: set[str] = set()
        while stack:
            edge, valves, first_value = stack.pop()
            if first_value is None:
                first_value = stream_value(edge)
            target = edge.getTarget()
            tag = str(target.getName())
            kind = kinds.get(tag)
            if kind is not None and kind != "valve":
                finish(source, tag, valves, first_value, str(edge.getName()))
                continue
            if tag in visited:
                continue
            visited.add(tag)
            if kind == "valve":
                valves = valves + ((tag, valve_kind(str(target.getEquipmentType()))),)
            onward = list(target.getOutgoingEdges())
            if not onward:
                if source is not None:
                    finish(source, None, valves, first_value, tag)
                continue
            stack.extend((nxt, valves, first_value) for nxt in onward)

    def finish(source, target, valves, line_value, label) -> None:
        key = (source, target, tuple(tag for tag, _kind in valves))
        if key in seen or (source is None and target is None):
            return
        seen.add(key)
        line = f"{source or 'feed'} to {target or 'product'}"
        if any(c.name == line for c in connections):
            line = f"{line} ({label})"
        status = _line_status(source, target, valves, new_tags, modified_tags)
        connections.append(
            TopologyConnection(line, source, target, None, line_value, valves, status)
        )

    for node in nodes:
        tag = str(node.getName())
        kind = kinds[tag]
        if kind is not None and kind != "valve":
            walk(node, tag)
        elif node.getInDegree() == 0:
            walk(node, None)

    label, unit_label = (
        (STREAM_VALUES[value][0], STREAM_VALUES[value][1]) if value else (None, None)
    )
    return plant_from_topology(
        name or str(process.getName()),
        items,
        connections,
        positions=positions,
        value_name=label,
        value_unit=unit_label,
        **arrange,
    )


# ---------------------------------------------------------------------- DEXPI


def plant_from_dexpi(
    path: str,
    *,
    name: str | None = None,
    positions: Mapping[str, Sequence[float]] | None = None,
    sizes: Mapping[str, Sequence[float]] | None = None,
    new_tags: Sequence[str] = (),
    modified_tags: Sequence[str] = (),
    **arrange: Any,
) -> ArrangedPlant:
    """Draw a DEXPI P&ID in 3D, using the DEXPI reader of the NeqSim main repository.

    ``DexpiXmlReader.readWithDiagnostics`` supplies the tagged items with
    their DEXPI class and sizing attributes, and ``DexpiTopologyResolver``
    the equipment-to-equipment connections with their piping segment. Inline
    valves are put on the segment they belong to and a line's diameter is
    taken from the nominal diameter of its components. A P&ID holds no
    equipment sizes or positions: give ``sizes`` and ``positions`` (keyed by
    tag) where they are known, and the rest is drawn at default sizes in flow
    order and declared in the caption. Needs ``neqsim`` and a Java runtime.
    """
    import jpype
    from neqsim import jneqsim

    dexpi = jneqsim.process.processmodel.dexpi
    file = jpype.JClass("java.io.File")(str(path))
    if not file.isFile():
        raise FileNotFoundError(str(path))
    result = dexpi.DexpiXmlReader.readWithDiagnostics(file)
    factory = jpype.JClass("javax.xml.parsers.DocumentBuilderFactory").newInstance()
    factory.setNamespaceAware(False)
    topology = dexpi.DexpiTopologyResolver.resolve(factory.newDocumentBuilder().parse(file))

    by_id: dict[str, Any] = {}
    for unit in result.getProcessSystem().getUnitOperations():
        if hasattr(unit, "getDexpiId") and unit.getDexpiId() is not None:
            by_id[str(unit.getDexpiId())] = unit

    def tag_of(dexpi_id: str) -> str:
        unit = by_id.get(dexpi_id)
        return str(unit.getName()) if unit is not None else dexpi_id

    def class_of(dexpi_id: str) -> str:
        unit = by_id.get(dexpi_id)
        if unit is not None:
            return str(unit.getDexpiClass())
        return str(elements.get(dexpi_id).getAttribute("ComponentClass"))

    def kind_of(dexpi_id: str) -> str | None:
        """Drawing kind, from NeqSim's own DEXPI class mapping first, then the class name."""
        unit = by_id.get(dexpi_id)
        mapped = str(unit.getMappedEquipment()) if unit is not None else ""
        return equipment_kind(mapped) or equipment_kind(class_of(dexpi_id))

    sizes = dict(sizes or {})
    items = []
    elements = topology.getEquipmentElements()
    drawn = [str(dexpi_id) for dexpi_id in topology.getOrderedEquipmentIds()]
    for dexpi_id in drawn:
        tag = tag_of(dexpi_id)
        kind = kind_of(dexpi_id)
        if kind is None or kind == "valve":
            kind = "box"
        size = tuple(float(v) for v in sizes[tag]) if tag in sizes else None
        items.append(TopologyItem(tag, kind, size, None, _statuses(tag, new_tags, modified_tags)))

    # The file itself says which nozzle belongs to which item and which inline
    # components sit inside which piping segment.
    import xml.etree.ElementTree as ElementTree

    owner: dict[str, str] = {}
    segment_members: dict[str, list[str]] = {}
    for element in ElementTree.parse(str(path)).iter():
        identifier = element.get("ID", "")
        local = element.tag.rsplit("}", 1)[-1]
        if local == "PipingNetworkSegment":
            segment_members[identifier] = [
                child.get("ID", "") for child in element if child.get("ID", "") in by_id
            ]
        if identifier in by_id or identifier in drawn:
            for child in element.iter():
                if child.tag.rsplit("}", 1)[-1] == "Nozzle" and child.get("ID"):
                    owner[child.get("ID")] = identifier
    for nozzle, item in dict(topology.getNozzleToEquipment()).items():
        owner.setdefault(str(nozzle), str(item))

    # Follow the piping from each item, through valves, reducers and tees, to the next item.
    onward: dict[str, list[tuple[str, str]]] = {}
    for connection in result.getConnections():
        if not connection.getFromId() or not connection.getToId():
            continue
        start = owner.get(str(connection.getFromId()), str(connection.getFromId()))
        end = owner.get(str(connection.getToId()), str(connection.getToId()))
        onward.setdefault(start, []).append((end, str(connection.getSegmentId() or "")))

    def is_valve(dexpi_id: str) -> bool:
        return dexpi_id in by_id and kind_of(dexpi_id) == "valve"

    connections = []
    drawn_members: set[str] = set()
    names: set[str] = set()
    for source_id in drawn:
        stack = [(end, (segment,), ()) for end, segment in onward.get(source_id, [])]
        visited: set[str] = set()
        while stack:
            node, segments, passed = stack.pop()
            if node in drawn:
                members = []
                for part in segments:
                    members += [m for m in segment_members.get(part, []) if m not in members]
                members += [m for m in passed if m not in members]
                valves = tuple((tag_of(m), valve_kind(class_of(m))) for m in members if is_valve(m))
                diameter = None
                for member in members:
                    unit = by_id[member]
                    if diameter is None and hasattr(unit, "getSizingAttribute"):
                        diameter = nominal_diameter_m(
                            unit.getSizingAttribute("NominalDiameterRepresentationAssignmentClass")
                        )
                source, target = tag_of(source_id), tag_of(node)
                line = f"{source} to {target}"
                if line in names:
                    line = f"{line} ({segments[0]})"
                if line in names:
                    continue
                names.add(line)
                drawn_members.update(members)
                status = _line_status(source, target, valves, new_tags, modified_tags)
                connections.append(
                    TopologyConnection(line, source, target, diameter, None, valves, status)
                )
                continue
            if node in visited:
                continue
            visited.add(node)
            through = passed + ((node,) if node in by_id else ())
            stack.extend(
                (end, segments + (segment,), through) for end, segment in onward.get(node, [])
            )

    all_valves = {
        dexpi_id
        for dexpi_id, unit in by_id.items()
        if equipment_kind(str(unit.getDexpiClass())) == "valve"
    }
    hidden = len(all_valves - drawn_members)
    notes = [f"From DEXPI P&ID {file.getName()}"]
    if hidden:
        notes.append(
            f"{hidden} of {len(all_valves)} valves are on branches, drains or off-page lines "
            "and are not drawn"
        )
    return plant_from_topology(
        name or str(file.getName()),
        items,
        connections,
        positions=positions,
        notes=notes,
        **arrange,
    )


# ------------------------------------------------- design data and layout study


def _quantity(data: Mapping[str, Any], name: str) -> float:
    entry = data["geometry"][name]
    if entry.get("status") != "available" or entry.get("unit") != "m":
        raise ValueError(f"geometry.{name} is unavailable or is not in metres")
    value = entry.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not value > 0:
        raise ValueError(f"geometry.{name} must be a positive number")
    return float(value)


def vessel_from_design_data(
    document: Mapping[str, Any], *, head_type: str, tag: str | None = None, **vessel: Any
) -> VesselSpec:
    """A vessel from NeqSim design-data JSON (``MechanicalDesign.toDesignDataJson()``).

    Reads schema 1.0 with a consistent ``cylindrical_shell``: inner diameter,
    wall thickness, tangent length and orientation. The design data carries no
    head shape, so ``head_type`` has to be stated. Levels, nozzles and
    internals are passed through ``vessel`` as for :class:`VesselSpec`.
    """
    data = document.get("designData", document)
    if data.get("schemaVersion") != "1.0":
        raise ValueError("expected NeqSim design-data schema 1.0")
    if data.get("geometryKind") != "cylindrical_shell":
        raise ValueError("this equipment has no cylindrical shell in its design data")
    if data.get("geometryConsistency") != "consistent":
        raise ValueError("shell diameters and thickness are incomplete or inconsistent")
    orientation = data.get("orientation")
    if orientation not in ("horizontal", "vertical"):
        raise ValueError("the design data does not state a horizontal or vertical orientation")
    return VesselSpec(
        tag=tag or str(data.get("tag") or data.get("name") or "vessel"),
        inside_diameter_m=_quantity(data, "innerDiameter"),
        tan_tan_length_m=_quantity(data, "tangentLength"),
        orientation=orientation,
        head_type=head_type,
        wall_thickness_m=_quantity(data, "wallThickness"),
        **vessel,
    )


def positions_from_layout_study(
    study: Mapping[str, Any], alternative: Mapping[str, Any]
) -> dict[str, tuple[float, float, float, float]]:
    """Footprint centres ``{tag: (x, y, z, rotation_deg)}`` from a ``neqsim layout-study`` dataset.

    Follows the dataset's own convention: ``placement.x_m/y_m`` is the
    lower-left corner of the rotated footprint, rotations are multiples of 90
    degrees and the deck supplies the base elevation. Pass the result as
    ``positions`` to the plant builders so the figure shows the studied
    arrangement instead of an automatic one.
    """
    decks = {deck["id"]: deck for deck in study["decks"]}
    equipment = {item["tag"]: item for item in study["equipment"]}
    positions = {}
    for placement in alternative.get("placements", []):
        tag = placement.get("tag")
        if tag not in equipment or placement.get("deck") not in decks:
            continue
        length, width, _height = (float(v) for v in equipment[tag]["size_m"])
        rotation = placement.get("rotation_deg", 0)
        if rotation not in (0, 90, 180, 270):
            raise ValueError("only orthogonal equipment rotations are supported")
        span_x, span_y = (length, width) if rotation in (0, 180) else (width, length)
        positions[tag] = (
            float(placement["x_m"]) + span_x / 2.0,
            float(placement["y_m"]) + span_y / 2.0,
            float(decks[placement["deck"]]["elevation_m"]),
            float(rotation),
        )
    return positions
