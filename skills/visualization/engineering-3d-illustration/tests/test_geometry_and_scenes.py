"""Dependency-free tests: geometry, volumes, scene rules and generated scripts."""

import json
from math import pi

import pytest

from engineering_3d_illustration import (
    Deck,
    EquipmentBlock,
    FieldSeries,
    Internal,
    LayoutSpec,
    Nozzle,
    PipelineSpec,
    VesselSpec,
    blender_job,
    build_layout_scene,
    build_pipeline_scene,
    build_vessel_scene,
    cadquery_script,
    colormap,
    openscad_script,
    pipeline_from_neqsim_pipe,
    recommend_backend,
    tessellate,
    utilisation_color,
    vessel_from_neqsim_separator,
)
from engineering_3d_illustration import mesh
from engineering_3d_illustration.blender_backend import BLENDER_SCRIPT


def _separator(**overrides):
    values = dict(
        tag="20-VA-001",
        inside_diameter_m=3.0,
        tan_tan_length_m=10.0,
        wall_thickness_m=0.045,
        liquid_level_m=1.5,
        interface_level_m=0.6,
        nozzles=(Nozzle("Inlet", "top", 0.1, 0.5), Nozzle("Oil out", "bottom", 0.9, 0.3)),
    )
    values.update(overrides)
    return VesselSpec(**values)


# ------------------------------------------------------------------- primitives


def test_cylinder_and_box_meshes_are_closed_with_the_right_volume():
    cylinder = mesh.cylinder((0, 0, 0), (0, 0, 1), 0.5, 2.0, segments=180)
    assert cylinder.is_closed()
    assert cylinder.signed_volume() == pytest.approx(pi * 0.25 * 2.0, rel=1e-3)
    box = mesh.box((1, 2, 3), (2.0, 3.0, 4.0), rotation_z_deg=30.0)
    assert box.is_closed()
    assert box.signed_volume() == pytest.approx(24.0)


def test_tube_is_closed_and_carries_one_scalar_per_vertex():
    points = [(0, 0, 0), (5, 0, 0), (5, 5, 0), (5, 5, 5)]
    tube = mesh.tube(points, 0.2, scalars=[1.0, 2.0, 3.0, 4.0], sides=12)
    assert tube.is_closed()
    assert tube.signed_volume() > 0.0
    assert len(tube.scalars) == len(tube.vertices)
    assert min(tube.scalars) == 1.0 and max(tube.scalars) == 4.0


def test_mesh_inputs_are_validated():
    with pytest.raises(ValueError):
        mesh.cylinder((0, 0, 0), (0, 0, 1), -1.0, 1.0)
    with pytest.raises(ValueError):
        mesh.tube([(0, 0, 0)], 0.1)
    with pytest.raises(ValueError):
        mesh.tube([(0, 0, 0), (1, 0, 0)], 0.1, scalars=[1.0])
    with pytest.raises(ValueError):
        mesh.revolve([(0.0, 0.0), (1.0, -0.5)], (0, 0, 0), (0, 0, 1))


# ---------------------------------------------------------------------- vessels


@pytest.mark.parametrize("head_type", ["elliptical_2_1", "hemispherical", "flat"])
@pytest.mark.parametrize("orientation", ["horizontal", "vertical"])
def test_liquid_volume_is_zero_empty_total_full_and_half_at_mid_height(head_type, orientation):
    spec = VesselSpec("V", 2.0, 6.0, orientation=orientation, head_type=head_type)
    assert spec.liquid_volume_m3(0.0) == pytest.approx(0.0, abs=1e-12)
    assert spec.liquid_volume_m3(spec.inside_height_m) == pytest.approx(spec.total_volume_m3)
    assert spec.liquid_volume_m3(spec.inside_height_m / 2.0) == pytest.approx(
        spec.total_volume_m3 / 2.0
    )
    levels = [spec.inside_height_m * i / 20.0 for i in range(21)]
    volumes = [spec.liquid_volume_m3(level) for level in levels]
    assert volumes == sorted(volumes)


def test_total_volume_matches_the_cylinder_plus_spheroid_formula():
    spec = VesselSpec("V", 3.0, 10.0)
    expected = pi * 1.5**2 * 10.0 + 4.0 / 3.0 * pi * 1.5**2 * 0.75
    assert spec.total_volume_m3 == pytest.approx(expected)


def test_the_drawn_shell_and_fill_enclose_the_closed_form_volumes():
    spec = _separator(liquid_level_m=None, interface_level_m=None, nozzles=())
    scene = build_vessel_scene(spec, cutaway=False, supports=False)
    shell = tessellate(scene.primitives[0])
    assert shell.is_closed()
    # The wall is offset by its thickness everywhere, heads included.
    outer = pi * 1.545**2 * 10.0 + 4.0 / 3.0 * pi * 1.545**2 * (0.75 + 0.045)
    assert shell.signed_volume() == pytest.approx(outer - spec.total_volume_m3, rel=0.01)

    filled = build_vessel_scene(_separator(interface_level_m=None), cutaway=False)
    liquid = next(p for p in filled.primitives if p.role == "liquid")
    assert tessellate(liquid).signed_volume() == pytest.approx(spec.total_volume_m3, rel=0.01)
    assert liquid.clip[4:] == (0.0, 1.5)


def test_levels_become_clip_planes_and_labels_and_the_inventory_is_stated():
    spec = _separator()
    scene = build_vessel_scene(spec)
    roles = {p.role: p for p in scene.primitives}
    assert roles["water"].clip[4:] == (0.0, 0.6)
    assert roles["oil"].clip[4:] == (0.6, 1.5)
    assert roles["shell"].clip[2] == 0.0  # the cutaway plane
    texts = [label.text for label in scene.labels]
    assert "Liquid level 1.50 m" in texts and "Interface 0.60 m" in texts
    assert scene.facts["liquid_volume_m3"] == pytest.approx(spec.total_volume_m3 / 2.0)
    assert "Liquid inventory 38.9 m3 (50 % of 77.8 m3)" in scene.caption()
    assert scene.true_scale


def test_an_assumed_wall_thickness_is_declared_and_the_scene_is_not_to_scale():
    scene = build_vessel_scene(_separator(wall_thickness_m=None))
    assert not scene.true_scale
    assert "Wall thickness not specified" in scene.caption()
    assert "Not to scale." in scene.caption()


def test_a_weir_confines_the_drawn_liquid_to_the_inlet_side():
    spec = _separator(internals=(Internal("Weir", "weir", 0.8, 0.03, 0.0, 1.3),))
    scene = build_vessel_scene(spec)
    oil = next(p for p in scene.primitives if p.role == "oil")
    assert oil.clip[1] == pytest.approx(8.0)
    weir = next(p for p in scene.primitives if p.role == "internal")
    assert weir.clip[0:2] == (pytest.approx(8.0), pytest.approx(8.03))
    assert weir.clip[4:] == (0.0, 1.3)
    assert "inlet side of the weir" in scene.caption()


def test_vertical_vessel_gets_a_skirt_and_axial_nozzles():
    spec = VesselSpec(
        "23-VG-001",
        1.8,
        4.0,
        orientation="vertical",
        liquid_level_m=1.2,
        nozzles=(Nozzle("Gas out", "top"), Nozzle("Inlet", "side", 0.5, 0.3)),
        internals=(Internal("Demister", "demister", 0.85, 0.15),),
    )
    scene = build_vessel_scene(spec)
    names = [p.name for p in scene.primitives]
    assert "skirt" in names and "Demister" in names
    gas = next(p for p in scene.primitives if p.name == "Gas out")
    assert gas.params["axis"] == (0.0, 0.0, 1.0)
    assert all(tessellate(p).is_closed() for p in scene.primitives)


def test_vessel_inputs_are_validated():
    with pytest.raises(ValueError, match="liquid_level_m"):
        VesselSpec("V", 2.0, 6.0, liquid_level_m=2.5)
    with pytest.raises(ValueError, match="interface_level_m"):
        VesselSpec("V", 2.0, 6.0, liquid_level_m=1.0, interface_level_m=1.5)
    with pytest.raises(ValueError, match="head_type"):
        VesselSpec("V", 2.0, 6.0, head_type="torispherical")
    with pytest.raises(ValueError, match="inside_diameter_m"):
        VesselSpec("V", float("nan"), 6.0)
    with pytest.raises(ValueError, match="location"):
        Nozzle("N", "underneath")


# -------------------------------------------------------------------- pipelines


def _pipeline():
    distance = [1000.0 * i for i in range(11)]
    elevation = [-300, -310, -330, -320, -300, -305, -340, -330, -250, -150, -20]
    temperature = tuple(60.0 - 5.0 * i for i in range(11))
    return PipelineSpec.from_profile(
        "Flowline", distance, elevation, 0.3239, [FieldSeries("Temperature", "C", temperature)]
    )


def test_pipeline_chainage_low_points_and_exaggeration():
    spec = _pipeline()
    assert spec.chainage_m()[-1] > 10_000.0
    assert spec.low_points() == (6, 2)  # deepest first
    assert spec.suggested_vertical_exaggeration() == 5.0
    flat = PipelineSpec("Flat", ((0, 0, 0), (100, 0, 0)), 0.2)
    assert flat.suggested_vertical_exaggeration() == 1.0
    assert flat.low_points() == ()


def test_pipeline_scene_states_every_out_of_scale_choice():
    scene = build_pipeline_scene(_pipeline(), color_by="Temperature")
    caption = scene.caption()
    assert "Vertical exaggeration x5" in caption
    assert "Pipe diameter drawn x" in caption
    assert "Colour: Temperature [C], 10 to 60" in caption
    assert not scene.true_scale
    tube = scene.primitives[0]
    assert tube.scalars[0] == 60.0 and tube.scalar_unit == "C"
    assert tube.params["points"][2][2] == pytest.approx(-330.0 * 5.0)
    assert any(label.text.startswith("low point -340 m") for label in scene.labels)
    assert any(label.text.startswith("max 60 C @ KP 0.0") for label in scene.labels)


def test_true_scale_pipeline_has_no_exaggeration_notes():
    spec = PipelineSpec("Spool", ((0, 0, 0), (2, 0, 0), (2, 0, 1.5)), 0.3)
    scene = build_pipeline_scene(spec, vertical_exaggeration=1.0, terrain=False)
    assert scene.true_scale
    assert "exaggeration" not in scene.caption() and "for visibility" not in scene.caption()


def test_pipeline_inputs_are_validated():
    with pytest.raises(ValueError, match="values for"):
        PipelineSpec("P", ((0, 0, 0), (1, 0, 0)), 0.2, (FieldSeries("T", "C", (1.0,)),))
    with pytest.raises(ValueError, match="at least two"):
        PipelineSpec("P", ((0, 0, 0),), 0.2)
    with pytest.raises(KeyError):
        build_pipeline_scene(_pipeline(), color_by="Pressure")


# ---------------------------------------------------------------------- layouts


def test_layout_colours_blocks_on_the_fixed_utilisation_legend():
    layout = LayoutSpec(
        "Module",
        (
            EquipmentBlock("A", "box", (0, 0, 0), (2, 2, 2), utilisation=0.5),
            EquipmentBlock("B", "horizontal_vessel", (6, 0, 0), (2, 6), 45.0, 1.1),
            EquipmentBlock("C", "vertical_vessel", (12, 0, 0), (1.5, 5)),
        ),
        (Deck("Deck", -2, 15, -3, 3),),
    )
    scene = build_layout_scene(layout)
    colours = {p.name: p.color for p in scene.primitives}
    assert colours["A"] == utilisation_color(0.0)
    assert colours["B"] == utilisation_color(2.0)
    assert "green <= 0.70" in scene.caption()
    assert any(label.text == "B  110 %" for label in scene.labels)
    assert all(tessellate(p).is_closed() for p in scene.primitives)
    with pytest.raises(ValueError, match="unique"):
        LayoutSpec("M", (layout.blocks[0], layout.blocks[0]))


def test_colour_helpers():
    assert colormap(0.0, 0.0, 1.0, "viridis") == (0.267, 0.005, 0.329)
    assert colormap(5.0, 0.0, 1.0, "viridis") == (0.993, 0.906, 0.144)
    assert colormap(1.0, 1.0, 1.0) == colormap(0.5, 0.0, 1.0)
    assert utilisation_color(0.8)[0] > utilisation_color(0.7)[0]
    with pytest.raises(ValueError):
        colormap(0.5, 0.0, 1.0, "rainbow")


# ------------------------------------------------------------------- backends


def test_backend_recommendation_follows_the_purpose():
    assert recommend_backend("results_figure").backend == "pyvista"
    assert recommend_backend("presentation_render").backend == "blender"
    cad = recommend_backend("cad_exchange", has_field=True)
    assert cad.backend == "cadquery" and "no field values" in cad.rationale
    assert recommend_backend("editable_model").backend == "openscad"
    with pytest.raises(ValueError):
        recommend_backend("marketing")


def test_generated_scripts_are_valid_and_describe_every_solid():
    scene = build_vessel_scene(_separator())
    script = cadquery_script(scene)
    compile(script, "generated_cadquery.py", "exec")
    assert '"id": "shell"' in script and "assembly.save" in script
    assert scene.caption() in script

    scad = openscad_script(scene)
    assert scad.count("{") == scad.count("}")
    assert "module shell()" in scad and "rotate_extrude(convexity=6)" in scad
    assert scad.count("intersection()") == len([p for p in scene.primitives if p.clip])
    assert "Cut planes are staggered" in scad

    compile(BLENDER_SCRIPT, "blender_render.py", "exec")
    job = blender_job(scene, view="front", samples=8)
    json.dumps(job)
    assert job["camera"]["parallel"] is True
    assert {part["name"] for part in job["parts"]} == {p.name for p in scene.primitives}
    assert all("clip_corner" in part for part in job["parts"])


def test_blender_job_carries_field_colours_for_a_coloured_tube():
    job = blender_job(build_pipeline_scene(_pipeline(), color_by="Temperature"))
    tube = job["parts"][0]
    assert len(tube["vertex_colors"]) == len(tube["vertices"])
    with pytest.raises(ValueError):
        blender_job(build_vessel_scene(_separator()), view="underneath")


# ------------------------------------------------------------ NeqSim adapters


class _FakeSeparator:
    def getName(self):
        return "20-VA-001"

    def getInternalDiameter(self):
        return 2.6

    def getSeparatorLength(self):
        return 8.0

    def getOrientation(self):
        return "horizontal"

    def getLiquidLevel(self):
        return 0.45  # NeqSim reports a fraction of the maximum liquid height


class _FakePipe:
    def getName(self):
        return "flowline"

    def getDiameter(self):
        return 0.25

    def getLengthProfile(self):
        return [0.0, 500.0, 1000.0]

    def getElevationProfile(self):
        return [0.0, -300.0, -600.0]

    def getPressureProfile(self):
        return [60.0, 61.0, 62.0]

    def getTemperatureProfile(self):
        return [333.15]  # an adiabatic run records the inlet only

    def getLiquidHoldupProfile(self):
        return [0.2, 0.25, 0.3]


def test_separator_adapter_converts_the_level_fraction_to_metres():
    vessel = vessel_from_neqsim_separator(_FakeSeparator())
    assert vessel.tag == "20-VA-001"
    assert vessel.liquid_level_m == pytest.approx(0.45 * 2.6)
    assert vessel.orientation == "horizontal"


def test_pipe_adapter_keeps_only_complete_profiles_and_true_length():
    pipeline = pipeline_from_neqsim_pipe(_FakePipe())
    assert [f.name for f in pipeline.fields] == ["Pressure", "Liquid holdup"]
    assert pipeline.points[1] == pytest.approx((400.0, 0.0, -300.0))
    assert pipeline.chainage_m()[-1] == pytest.approx(1000.0)
