"""Automatic arrangement, tie-in status, and the adapters to NeqSim's own data."""

from importlib.util import find_spec
from pathlib import Path

import pytest

from engineering_3d_illustration import (
    Equipment,
    PipeRun,
    PlantSpec,
    TopologyConnection,
    TopologyItem,
    build_plant_scene,
    equipment_kind,
    flow_levels,
    nominal_diameter_m,
    plant_from_layout_study,
    plant_from_neqsim_process,
    plant_from_topology,
    positions_from_layout_study,
    tessellate,
    valve_kind,
    vessel_from_design_data,
)
from engineering_3d_illustration.plant import STATUS_COLORS


def _topology():
    items = [
        TopologyItem("V-1", "horizontal_vessel", (2.6, 8.0), 0.8),
        TopologyItem("K-1", "compressor", None, None, "new"),
        TopologyItem("E-1", "heat_exchanger", None, None, "new"),
        TopologyItem("P-1", "pump"),
    ]
    connections = [
        TopologyConnection("Feed", None, "V-1", 0.4, 60.0, (("HV-1", "control"),)),
        TopologyConnection("Gas", "V-1", "K-1", None, 55.0, (), "new"),
        TopologyConnection("Hot gas", "K-1", "E-1", None, 140.0, (("NRV-1", "check"),), "new"),
        TopologyConnection("Oil", "V-1", "P-1", 0.2, 55.0),
        TopologyConnection("Export", "E-1", None, None, 35.0, (), "new"),
    ]
    return items, connections


def test_flow_levels_follow_the_flow_and_ignore_recycles():
    levels = flow_levels(["A", "B", "C", "D"], [("A", "B"), ("B", "C"), ("C", "A"), ("A", "D")])
    assert levels == {"A": 0, "B": 1, "C": 2, "D": 1}
    assert flow_levels(["X"], []) == {"X": 0}


def test_automatic_arrangement_places_in_flow_order_and_declares_every_assumption():
    items, connections = _topology()
    arranged = plant_from_topology(
        "Area", items, connections, value_name="Temperature", value_unit="C"
    )
    x = {e.tag: e.position[0] for e in arranged.plant.equipment}
    assert x["V-1"] < x["K-1"] < x["E-1"] and x["P-1"] == x["K-1"]
    assert arranged.assumed_positions == ("V-1", "K-1", "E-1", "P-1")
    assert arranged.assumed_sizes == ("K-1", "E-1", "P-1")
    assert arranged.assumed_diameters == ("Gas", "Hot gas", "Export")
    caption = arranged.scene().caption()
    assert "4 of 4 items placed automatically in flow order" in caption
    assert "3 items drawn at a default envelope size" in caption
    assert "3 lines drawn at an assumed 250 mm diameter" in caption
    assert "Not to scale." in caption and "not a plot plan" in caption


def test_lines_run_between_ports_over_the_rack_with_valves_on_a_straight_leg():
    items, connections = _topology()
    arranged = plant_from_topology(
        "Area", items, connections, value_name="Temperature", value_unit="C"
    )
    equipment = {e.tag: e for e in arranged.plant.equipment}
    pipes = {p.name: p for p in arranged.plant.pipes}
    gas = pipes["Gas"]
    assert gas.points[0] == pytest.approx(equipment["V-1"].port("top", 0.8))
    assert gas.points[-1] == pytest.approx(equipment["K-1"].port("inlet"))
    tallest = max(e.position[2] + e.envelope()[2] for e in equipment.values())
    assert max(p[2] for p in gas.points) > tallest
    # Every leg is parallel to an axis.
    for a, b in zip(gas.points[:-1], gas.points[1:]):
        assert sum(1 for i in range(3) if abs(a[i] - b[i]) > 1e-9) == 1
    feed, export = pipes["Feed"], pipes["Export"]
    assert feed.points[0][0] < min(e.position[0] for e in equipment.values())
    assert export.points[-1][0] > max(e.position[0] for e in equipment.values())
    assert [v.tag for v in feed.valves] == ["HV-1"] and feed.valves[0].kind == "control"
    assert all(tessellate(p).is_closed() for p in arranged.scene().primitives)


def test_supplied_positions_replace_the_automatic_ones():
    items, connections = _topology()
    arranged = plant_from_topology(
        "Area",
        items,
        connections,
        positions={"K-1": (30.0, 12.0, 5.0, 90.0)},
        value_name="Temperature",
        value_unit="C",
    )
    compressor = arranged.plant.equipment_by_tag("K-1")
    assert compressor.position == (30.0, 12.0, 5.0) and compressor.rotation_deg == 90.0
    assert "K-1" not in arranged.assumed_positions
    with pytest.raises(ValueError, match="unknown item"):
        plant_from_topology("A", items, [TopologyConnection("X", "V-1", "nowhere")])
    with pytest.raises(ValueError, match="neither"):
        TopologyConnection("X", None, None)


def test_tie_in_scope_is_coloured_by_status_and_results_stay_as_labels():
    items, connections = _topology()
    arranged = plant_from_topology(
        "Area", items, connections, value_name="Temperature", value_unit="C"
    )
    scope = arranged.scene()  # auto: something is new, so status colouring
    colours = {p.name: p.color for p in scope.primitives}
    assert colours["K-1"] == STATUS_COLORS["new"]
    assert colours["V-1"] == STATUS_COLORS["existing"]
    assert (
        colours["Hot gas"] == STATUS_COLORS["new"] and colours["Oil"] == STATUS_COLORS["existing"]
    )
    assert colours["NRV-1 body"] == STATUS_COLORS["new"]
    assert all(p.scalars is None for p in scope.primitives)
    labels = [label.text for label in scope.labels]
    assert "K-1  (new)" in labels and "V-1  80 %" in labels and "140 C" in labels
    caption = scope.caption()
    assert "new in blue, modified in orange, existing in grey" in caption
    assert "2 new and 0 modified equipment items, 3 new or modified lines" in caption

    results = arranged.scene(color_by="results")
    tubes = {p.name: p for p in results.primitives if p.kind == "tube"}
    assert tubes["Hot gas"].scalar_range == (35.0, 140.0)
    assert "Pipe colour: Temperature [C], 35 to 140" in results.caption()
    with pytest.raises(ValueError):
        arranged.scene(color_by="rainbow")


def test_status_is_validated_and_existing_plants_are_unchanged():
    with pytest.raises(ValueError, match="status"):
        Equipment("P", "pump", (0, 0, 0), (1.0,), status="planned")
    with pytest.raises(ValueError, match="status"):
        PipeRun("R", ((0, 0, 0), (1, 0, 0)), 0.2, status="planned")
    plain = PlantSpec("A", (Equipment("P", "pump", (0, 0, 0), (1.0,)),))
    scene = build_plant_scene(plain)
    assert "Colour by status" not in scene.caption() and scene.true_scale


def test_class_names_map_to_drawing_kinds():
    assert equipment_kind("Separator") == "horizontal_vessel"
    assert equipment_kind("ThreePhaseSeparator", "vertical") == "vertical_vessel"
    assert equipment_kind("GasScrubber") == "vertical_vessel"
    assert equipment_kind("Tank") == "vertical_vessel"
    assert equipment_kind("DistillationColumn") == "column"
    assert equipment_kind("CentrifugalCompressor") == "compressor"
    assert equipment_kind("ReciprocatingPump") == "pump"
    assert equipment_kind("PlateHeatExchanger") == equipment_kind("Cooler") == "heat_exchanger"
    assert equipment_kind("ThrottlingValve") == equipment_kind("SwingCheckValve") == "valve"
    assert equipment_kind("Stream") is None and equipment_kind("Mixer") is None
    assert valve_kind("SwingCheckValve") == "check"
    assert valve_kind("ThrottlingValve") == "control"
    assert valve_kind("BallValve") == "manual"
    assert nominal_diameter_m("DN 80") == pytest.approx(0.08)
    assert nominal_diameter_m('6"') == pytest.approx(0.1524)
    assert nominal_diameter_m("") is None and nominal_diameter_m("75HB13") is None


# --------------------------------------------------- a stand-in NeqSim process graph


class _Stream:
    def __init__(self, temperature):
        self._temperature = temperature

    def getTemperature(self, unit):
        assert unit == "C"
        return self._temperature


class _Unit:
    def __init__(self, diameter=None, length=None, utilisation=None, orientation=None):
        self._d, self._l, self._u, self._o = diameter, length, utilisation, orientation
        if diameter is not None:
            self.getInternalDiameter = lambda: diameter
            self.getSeparatorLength = lambda: length
        if utilisation is not None:
            self.getMaxUtilization = lambda: utilisation
        if orientation is not None:
            self.getOrientation = lambda: orientation


class _Node:
    def __init__(self, name, kind, unit=None):
        self._name, self._kind, self._unit = name, kind, unit or _Unit()
        self.outgoing, self.incoming = [], []

    def getName(self):
        return self._name

    def getEquipmentType(self):
        return self._kind

    def getEquipment(self):
        return self._unit

    def getOutgoingEdges(self):
        return self.outgoing

    def getInDegree(self):
        return len(self.incoming)


class _Edge:
    def __init__(self, source, target, temperature):
        self._source, self._target, self._stream = source, target, _Stream(temperature)
        source.outgoing.append(self)
        target.incoming.append(self)

    def getSource(self):
        return self._source

    def getTarget(self):
        return self._target

    def getStream(self):
        return self._stream

    def getName(self):
        return f"{self._source.getName()}->{self._target.getName()}"


class _Process:
    def __init__(self, nodes):
        self._nodes = nodes

    def getName(self):
        return "Fake process"

    def buildGraph(self):
        return self

    def getNodes(self):
        return self._nodes


def _fake_process():
    feed = _Node("Feed", "Stream")
    choke = _Node("HV-1", "ThrottlingValve")
    separator = _Node("V-1", "Separator", _Unit(2.6, 8.0, 0.82, "horizontal"))
    gas = _Node("Gas", "Stream")
    compressor = _Node("K-1", "Compressor")
    cooler = _Node("E-1", "Cooler")
    mixer = _Node("M-1", "Mixer")
    level_valve = _Node("LV-1", "ThrottlingValve")
    pump = _Node("P-1", "Pump")
    export = _Node("Export", "Stream")
    _Edge(feed, choke, 60.0)
    _Edge(choke, separator, 52.0)
    _Edge(separator, gas, 52.0)
    _Edge(gas, compressor, 52.0)
    _Edge(compressor, cooler, 140.0)
    _Edge(cooler, mixer, 35.0)
    _Edge(separator, level_valve, 52.0)
    _Edge(level_valve, pump, 50.0)
    _Edge(pump, mixer, 51.0)
    _Edge(mixer, export, 40.0)
    return _Process(
        [feed, choke, separator, gas, compressor, cooler, mixer, level_valve, pump, export]
    )


def test_process_graph_is_reduced_to_equipment_lines_and_inline_valves():
    arranged = plant_from_neqsim_process(_fake_process(), new_tags=("K-1", "E-1"))
    plant = arranged.plant
    assert [e.tag for e in plant.equipment] == ["V-1", "K-1", "E-1", "P-1"]
    separator = plant.equipment_by_tag("V-1")
    assert separator.size_m == (2.6, 8.0) and separator.utilisation == 0.82
    assert plant.equipment_by_tag("K-1").status == "new"
    lines = {p.name: p for p in plant.pipes}
    assert set(lines) == {
        "feed to V-1",
        "V-1 to K-1",
        "K-1 to E-1",
        "V-1 to P-1",
        "E-1 to product",
        "P-1 to product",
    }
    assert [v.tag for v in lines["feed to V-1"].valves] == ["HV-1"]
    assert [(v.tag, v.kind) for v in lines["V-1 to P-1"].valves] == [("LV-1", "control")]
    assert lines["K-1 to E-1"].value == 140.0 and lines["feed to V-1"].value == 60.0
    assert lines["K-1 to E-1"].status == "new" and lines["V-1 to P-1"].status == "existing"
    assert (plant.value_name, plant.value_unit) == ("Temperature", "C")
    assert arranged.assumed_sizes == ("K-1", "E-1", "P-1")


def test_process_without_results_or_with_no_value_draws_plain_lines():
    arranged = plant_from_neqsim_process(_fake_process(), value=None)
    assert all(p.value is None for p in arranged.plant.pipes)
    assert arranged.plant.value_name is None
    with pytest.raises(ValueError):
        plant_from_neqsim_process(_fake_process(), value="viscosity")


# ------------------------------------------------ design data and layout study


def _design_data(**overrides):
    def quantity(value):
        return {"value": value, "unit": "m", "status": "available"}

    data = {
        "schemaVersion": "1.0",
        "geometryKind": "cylindrical_shell",
        "geometryConsistency": "consistent",
        "orientation": "horizontal",
        "geometry": {
            "innerDiameter": quantity(3.0),
            "outerDiameter": quantity(3.09),
            "wallThickness": quantity(0.045),
            "tangentLength": quantity(10.0),
        },
    }
    data.update(overrides)
    return data


def test_vessel_from_design_data_reads_the_shell_and_requires_a_stated_head():
    vessel = vessel_from_design_data(
        {"designData": _design_data()},
        head_type="elliptical_2_1",
        tag="20-VA-001",
        liquid_level_m=1.5,
    )
    assert (vessel.inside_diameter_m, vessel.tan_tan_length_m) == (3.0, 10.0)
    assert vessel.wall_thickness_m == 0.045 and vessel.liquid_level_m == 1.5
    with pytest.raises(TypeError):
        vessel_from_design_data(_design_data())  # the head shape is not in the data
    with pytest.raises(ValueError, match="schema"):
        vessel_from_design_data(_design_data(schemaVersion="2.0"), head_type="flat")
    with pytest.raises(ValueError, match="cylindrical shell"):
        vessel_from_design_data(_design_data(geometryKind="envelope"), head_type="flat")
    missing = _design_data()
    missing["geometry"]["tangentLength"] = {"value": None, "unit": "m", "status": "missing"}
    with pytest.raises(ValueError, match="tangentLength"):
        vessel_from_design_data(missing, head_type="flat")


def test_layout_study_positions_follow_the_dataset_convention():
    study = {
        "decks": [{"id": "cellar", "elevation_m": 20.0}, {"id": "main", "elevation_m": 28.0}],
        "equipment": [
            {"tag": "V-1", "size_m": [10.0, 3.0, 3.5]},
            {"tag": "K-1", "size_m": [5.0, 2.0, 2.5]},
            {"tag": "unplaced", "size_m": [1.0, 1.0, 1.0]},
        ],
    }
    alternative = {
        "placements": [
            {"tag": "V-1", "deck": "cellar", "x_m": 4.0, "y_m": 6.0},
            {"tag": "K-1", "deck": "main", "x_m": 10.0, "y_m": 2.0, "rotation_deg": 90},
            {"tag": "ghost", "deck": "main", "x_m": 0.0, "y_m": 0.0},
        ]
    }
    positions = positions_from_layout_study(study, alternative)
    assert positions == {"V-1": (9.0, 7.5, 20.0, 0.0), "K-1": (11.0, 4.5, 28.0, 90.0)}
    alternative["placements"][0]["rotation_deg"] = 45
    with pytest.raises(ValueError, match="orthogonal"):
        positions_from_layout_study(study, alternative)


def test_layout_study_alternative_is_drawn_where_it_was_placed_with_its_route_estimates():
    study = {
        "project": {"id": "SYN-1", "title": "Synthetic module"},
        "decks": [
            {"id": "LOWER", "elevation_m": 0.0, "width_m": 30.0, "depth_m": 20.0},
            {"id": "MAIN", "elevation_m": 8.0, "width_m": 30.0, "depth_m": 20.0},
            {"id": "UNUSED", "elevation_m": 16.0, "width_m": 30.0, "depth_m": 20.0},
        ],
        "equipment": [
            {"tag": "V-101", "kind": "separator", "size_m": [6.0, 3.0, 4.0]},
            {"tag": "K-101", "kind": "compressor", "size_m": [6.0, 4.0, 4.0]},
            {"tag": "U-101", "kind": "utility_package", "size_m": [5.0, 3.0, 3.0]},
        ],
    }
    alternative = {
        "id": "ALT-01",
        "placements": [
            {"tag": "V-101", "deck": "LOWER", "x_m": 2.0, "y_m": 4.0},
            {"tag": "K-101", "deck": "MAIN", "x_m": 2.0, "y_m": 4.0, "rotation_deg": 90},
            {"tag": "U-101", "deck": "LOWER", "x_m": 12.0, "y_m": 4.0},
        ],
        "route_estimates": {
            "routes": [
                {
                    "connection_id": "L1",
                    "from_tag": "V-101",
                    "to_tag": "K-101",
                    "points_m": [[5.0, 5.5, 4.0], [5.0, 5.5, 8.0]],
                },
                {"connection_id": "L2", "from_tag": "V-101", "to_tag": "U-101", "points_m": []},
            ]
        },
    }
    arranged = plant_from_layout_study(
        study, alternative, new_tags=("K-101",), utilisation={"V-101": 0.8}
    )
    plant = arranged.plant
    vessel, compressor, package = (plant.equipment_by_tag(t) for t in ("V-101", "K-101", "U-101"))
    assert vessel.kind == "horizontal_vessel" and vessel.position == (5.0, 5.5, 0.0)
    assert vessel.envelope()[0] == pytest.approx(6.0)  # the vessel fills the length of its box
    assert vessel.utilisation == 0.8
    assert compressor.position == (4.0, 7.0, 8.0) and compressor.rotation_deg == 90.0
    assert compressor.status == "new"
    assert package.kind == "box" and package.size_m == (5.0, 3.0, 3.0)
    assert [d.name for d in plant.decks] == ["LOWER", "MAIN"]
    assert [p.name for p in plant.pipes] == ["L1"] and plant.pipes[0].status == "new"
    caption = arranged.scene().caption()
    assert "Positions from layout study SYN-1 alternative ALT-01" in caption
    assert "they are not physical routes" in caption
    assert "1 connections between touching or unrouted items are not drawn" in caption
    assert arranged.assumed_positions == ()

    plain = plant_from_layout_study(
        study, {"id": "ALT-02", "placements": alternative["placements"]}
    )
    assert plain.plant.pipes == () and "no route estimates" in plain.scene().caption()


# ------------------------------------------------------------- with NeqSim itself


@pytest.mark.skipif(find_spec("neqsim") is None, reason="NeqSim not installed")
def test_a_neqsim_process_survives_the_dexpi_round_trip_into_a_drawing(tmp_path: Path):
    import jpype
    from neqsim import jneqsim

    from engineering_3d_illustration import plant_from_dexpi

    fluid = jneqsim.thermo.system.SystemSrkEos(273.15 + 60.0, 60.0)
    for component, moles in (("methane", 0.7), ("n-heptane", 0.2), ("water", 0.1)):
        fluid.addComponent(component, moles)
    fluid.setMixingRule("classic")
    fluid.setMultiPhaseCheck(True)
    equipment = jneqsim.process.equipment
    feed = equipment.stream.Stream("Feed", fluid)
    feed.setFlowRate(50000.0, "kg/hr")
    separator = equipment.separator.Separator("20-VA-001", feed)
    separator.setInternalDiameter(2.6)
    separator.setSeparatorLength(8.0)
    compressor = equipment.compressor.Compressor("23-KA-001", separator.getGasOutStream())
    compressor.setOutletPressure(110.0)
    valve = equipment.valve.ThrottlingValve("20-LV-001", separator.getLiquidOutStream())
    valve.setOutletPressure(10.0)
    second = equipment.separator.Separator("20-VA-002", valve.getOutletStream())
    process = jneqsim.process.processmodel.ProcessSystem()
    for unit in (feed, separator, compressor, valve, second):
        process.add(unit)
    process.run()

    direct = plant_from_neqsim_process(process, new_tags=("23-KA-001",))
    assert {e.tag for e in direct.plant.equipment} == {"20-VA-001", "23-KA-001", "20-VA-002"}
    assert direct.plant.equipment_by_tag("20-VA-001").size_m == (2.6, 8.0)
    liquid = next(p for p in direct.plant.pipes if p.name == "20-VA-001 to 20-VA-002")
    assert [v.tag for v in liquid.valves] == ["20-LV-001"]
    gas = next(p for p in direct.plant.pipes if p.name == "20-VA-001 to 23-KA-001")
    assert gas.value == pytest.approx(60.0, abs=1.0) and gas.status == "new"

    pid = tmp_path / "process.xml"
    jneqsim.process.processmodel.dexpi.DexpiXmlWriter.write(
        process, jpype.JClass("java.io.File")(str(pid))
    )
    drawn = plant_from_dexpi(str(pid), new_tags=("23-KA-001",))
    assert {e.tag for e in drawn.plant.equipment} == {"20-VA-001", "23-KA-001", "20-VA-002"}
    lines = {p.name: p for p in drawn.plant.pipes}
    assert set(lines) == {"20-VA-001 to 23-KA-001", "20-VA-001 to 20-VA-002"}
    assert len(lines["20-VA-001 to 20-VA-002"].valves) == 1
    assert lines["20-VA-001 to 23-KA-001"].status == "new"
    assert "From DEXPI P&ID process.xml" in drawn.scene().caption()
