"""Dependency-free tests for the process-area scene and the OpenFOAM link."""

from pathlib import Path

import pytest

from engineering_3d_illustration import (
    Equipment,
    InlineValve,
    PipeRun,
    PlantSpec,
    VesselSpec,
    build_plant_scene,
    colormap,
    find_openfoam_output,
    render_openfoam_case,
    route,
    tessellate,
    vessel_fluid_volume_stl,
    write_stl,
)
from engineering_3d_illustration import mesh


def _plant():
    separator = Equipment("20-VA-001", "horizontal_vessel", (6, 5, 0), (2.6, 8.0), 0.0, 0.82)
    scrubber = Equipment("23-VG-001", "vertical_vessel", (15, 5, 0), (1.6, 5.0))
    pump = Equipment("21-PA-001", "pump", (6, 13, 0), (2.4,))
    cooler = Equipment("23-HA-001", "heat_exchanger", (20, 13, 0), (1.0, 6.0), 180.0)
    compressor = Equipment("23-KA-001", "compressor", (22, 5, 0), (5.0,))
    pipes = (
        PipeRun(
            "Gas",
            route(separator.port("top", 0.9), scrubber.port("inlet", 0.5), "zxy"),
            0.4,
            value=58.0,
            valves=(InlineValve("20-PV-001", 0.5, "control"),),
        ),
        PipeRun(
            "Hot gas",
            route(compressor.port("top"), cooler.port("inlet"), "zyx"),
            0.3,
            value=142.0,
            valves=(InlineValve("23-HV-001", 0.5, "manual"),),
        ),
        PipeRun(
            "Drain",
            (pump.port("outlet"), (12.0, 13.0, 0.7)),
            0.2,
            valves=(InlineValve("21-NRV-001", 0.5, "check"),),
        ),
    )
    return PlantSpec(
        "Area",
        (separator, scrubber, pump, cooler, compressor),
        pipes,
        value_name="Temperature",
        value_unit="C",
    )


def test_route_is_axis_parallel_and_follows_the_order():
    assert route((0, 0, 0), (3, 4, 5), "zxy") == ((0, 0, 0), (0, 0, 5), (3, 0, 5), (3, 4, 5))
    assert route((0, 0, 0), (3, 0, 0)) == ((0, 0, 0), (3, 0, 0))
    with pytest.raises(ValueError):
        route((0, 0, 0), (1, 1, 1), "xyy")


def test_ports_sit_on_the_equipment_envelope():
    vessel = Equipment("V", "horizontal_vessel", (10, 5, 0), (2.0, 6.0))
    assert vessel.port("inlet") == pytest.approx((10 - 3.5, 5, 1.6))
    assert vessel.port("top")[2] == pytest.approx(2.6)
    assert vessel.port("bottom")[2] == pytest.approx(0.6)  # underside of the shell
    turned = Equipment("W", "horizontal_vessel", (10, 5, 0), (2.0, 6.0), 90.0)
    assert turned.port("outlet") == pytest.approx((10, 5 + 3.5, 1.6))
    column = Equipment("C", "column", (0, 0, 0), (1.0, 12.0))
    assert column.port("top") == (0, 0, 12.0)
    assert column.port("inlet", 0.25) == pytest.approx((-0.5, 0, 3.0))


def test_plant_scene_is_to_scale_and_every_solid_is_closed():
    scene = build_plant_scene(_plant())
    assert scene.true_scale
    assert all(tessellate(p).is_closed() for p in scene.primitives)
    assert "5 equipment items, 3 pipe runs, 3 valves" in scene.caption()
    names = [p.name for p in scene.primitives]
    for expected in (
        "20-PV-001 actuator",
        "23-HV-001 handwheel",
        "21-NRV-001 body",
        "23-HA-001 flange 1",
    ):
        assert expected in names
    assert "21-NRV-001 stem" not in names  # a check valve has no operator
    labels = [label.text for label in scene.labels]
    assert "20-VA-001  82 %" in labels and "20-PV-001" in labels and "142 C" in labels


def test_pipe_runs_share_one_colour_scale_and_keep_their_true_diameter():
    scene = build_plant_scene(_plant(), colormap_name="coolwarm")
    tubes = {p.name: p for p in scene.primitives if p.kind == "tube"}
    assert tubes["Gas"].scalar_range == tubes["Hot gas"].scalar_range == (58.0, 142.0)
    assert tubes["Gas"].params["radius"] == pytest.approx(0.2)
    assert tubes["Hot gas"].color == colormap(142.0, 58.0, 142.0, "coolwarm")
    assert tubes["Drain"].scalars is None  # no value, drawn neutral
    assert "Pipe colour: Temperature [C], 58 to 142" in scene.caption()
    # Bends are rounded: more points than the corners that were given.
    assert len(tubes["Gas"].params["points"]) > 4


def test_valve_sits_on_the_pipe_at_the_stated_fraction():
    run = PipeRun("R", ((0, 0, 0), (10, 0, 0), (10, 10, 0)), 0.3)
    point, direction = run.point_at(0.75)
    assert point == pytest.approx((10, 5, 0)) and direction == pytest.approx((0, 1, 0))
    assert run.length_m == pytest.approx(20.0)


def test_plant_inputs_are_validated():
    with pytest.raises(ValueError, match="size value"):
        Equipment("P", "pump", (0, 0, 0), (1.0, 2.0))
    with pytest.raises(ValueError, match="kind"):
        Equipment("P", "turbine", (0, 0, 0), (1.0,))
    with pytest.raises(ValueError, match="fraction"):
        InlineValve("V", 1.0)
    with pytest.raises(ValueError, match="two distinct points"):
        PipeRun("R", ((0, 0, 0), (0, 0, 0)), 0.2)
    with pytest.raises(ValueError, match="value_name"):
        PlantSpec("A", (), (PipeRun("R", ((0, 0, 0), (1, 0, 0)), 0.2, value=10.0),))
    pump = Equipment("P", "pump", (0, 0, 0), (1.0,))
    with pytest.raises(ValueError, match="unique"):
        PlantSpec("A", (pump, pump))


# --------------------------------------------------------------------- OpenFOAM


def test_openfoam_output_prefers_the_latest_vtk_export(tmp_path: Path):
    assert find_openfoam_output(tmp_path / "missing").kind == "none"
    case = tmp_path / "bend"
    (case / "VTK").mkdir(parents=True)
    assert find_openfoam_output(case).kind == "none"
    for index in (0, 150, 1000):
        (case / "VTK" / f"bend_{index}.vtm").write_text("")
    latest = find_openfoam_output(case)
    assert (latest.kind, latest.time, latest.path.name) == ("vtk", "1000", "bend_1000.vtm")
    assert find_openfoam_output(case, "150").path.name == "bend_150.vtm"
    assert "available" in find_openfoam_output(case, "7").message


def test_openfoam_output_falls_back_to_native_time_folders(tmp_path: Path):
    case = tmp_path / "pipe"
    (case / "constant" / "polyMesh").mkdir(parents=True)
    for name in ("0", "250", "500", "system"):
        (case / name).mkdir()
    found = find_openfoam_output(case)
    assert (found.kind, found.time) == ("native", "500")
    unsolved = tmp_path / "unsolved"
    (unsolved / "0").mkdir(parents=True)
    assert "run the case" in find_openfoam_output(unsolved).message


def test_rendering_an_unsolved_case_reports_instead_of_raising(tmp_path: Path):
    outcome = render_openfoam_case(tmp_path, tmp_path / "out")
    assert not outcome.completed and outcome.status in ("not_executed", "failed")
    with pytest.raises(ValueError):
        render_openfoam_case(tmp_path, tmp_path / "out", views=("contours",))


def test_stl_export_is_a_closed_named_solid_of_the_vessel_volume(tmp_path: Path):
    spec = VesselSpec("20-VA-001", 3.0, 10.0)
    path = vessel_fluid_volume_stl(spec, tmp_path / "geometry" / "vessel.stl")
    text = path.read_text()
    assert text.startswith("solid walls") and text.rstrip().endswith("endsolid walls")
    facets = text.count("facet normal")
    assert facets == text.count("endfacet") > 1000
    # Read the facets back and check the enclosed volume against the closed form.
    vertices = [
        tuple(float(v) for v in line.split()[1:]) for line in text.splitlines() if "vertex" in line
    ]
    volume = 0.0
    for a, b, c in zip(vertices[0::3], vertices[1::3], vertices[2::3]):
        volume += (
            a[0] * (b[1] * c[2] - b[2] * c[1])
            - a[1] * (b[0] * c[2] - b[2] * c[0])
            + a[2] * (b[0] * c[1] - b[1] * c[0])
        ) / 6.0
    assert volume == pytest.approx(spec.total_volume_m3, rel=0.005)
    with pytest.raises(ValueError):
        write_stl(mesh.box((0, 0, 0), (1, 1, 1)), tmp_path / "bad.stl", "inlet patch")
