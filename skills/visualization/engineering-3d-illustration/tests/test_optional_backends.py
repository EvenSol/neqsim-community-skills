"""Tests that draw for real. Each is skipped when its tool is not installed."""

from importlib.util import find_spec
from pathlib import Path
from shutil import which

import pytest

from engineering_3d_illustration import (
    FieldSeries,
    Nozzle,
    PipelineSpec,
    VesselSpec,
    build_pipeline_scene,
    build_vessel_scene,
    export_cadquery,
    export_openscad,
    primitive_polydata,
    render_blender,
    render_scene,
)


def _vessel():
    return VesselSpec(
        "20-VA-001",
        3.0,
        10.0,
        wall_thickness_m=0.045,
        liquid_level_m=1.1,
        interface_level_m=0.6,
        nozzles=(Nozzle("Inlet", "top", 0.1, 0.5),),
    )


def test_missing_tools_are_reported_with_the_script_still_written(tmp_path: Path, monkeypatch):
    import engineering_3d_illustration.blender_backend as blender
    import engineering_3d_illustration.cad_backends as cad
    import engineering_3d_illustration.pyvista_backend as viewer

    monkeypatch.setattr(cad, "find_spec", lambda name: None)
    monkeypatch.setattr(cad, "which", lambda name: None)
    monkeypatch.setattr(blender, "find_spec", lambda name: None)
    monkeypatch.setattr(blender, "which", lambda name: None)
    monkeypatch.setattr(viewer, "find_spec", lambda name: None)
    scene = build_vessel_scene(_vessel())

    drawn = render_scene(scene, tmp_path)
    assert drawn.status == "not_executed" and "pip install pyvista" in drawn.command
    for outcome, suffix in (
        (export_cadquery(scene, tmp_path), "_cadquery.py"),
        (export_openscad(scene, tmp_path), ".scad"),
        (render_blender(scene, tmp_path), "blender_render.py"),
    ):
        assert outcome.status == "not_executed" and not outcome.completed
        assert outcome.files[0].name.endswith(suffix) and outcome.files[0].exists()
        assert outcome.command and outcome.caption == scene.caption()


@pytest.mark.skipif(find_spec("pyvista") is None, reason="PyVista not installed")
def test_pyvista_clips_liquid_to_the_closed_form_volume_and_writes_images(tmp_path: Path):
    spec = _vessel()
    scene = build_vessel_scene(spec, cutaway=False)
    water = primitive_polydata(next(p for p in scene.primitives if p.role == "water"))
    oil = primitive_polydata(next(p for p in scene.primitives if p.role == "oil"))
    assert water.volume == pytest.approx(spec.liquid_volume_m3(0.6), rel=0.015)
    assert oil.volume == pytest.approx(
        spec.liquid_volume_m3(1.1) - spec.liquid_volume_m3(0.6), rel=0.015
    )

    outcome = render_scene(
        build_vessel_scene(spec), tmp_path, views=("iso", "front"), window_size=(480, 320)
    )
    assert outcome.completed
    images = [f for f in outcome.files if f.suffix == ".png"]
    assert len(images) == 2 and all(f.stat().st_size > 2000 for f in images)
    assert (tmp_path / "20-va-001_caption.txt").read_text().strip() == scene_caption(spec)


def scene_caption(spec):
    return build_vessel_scene(spec).caption()


@pytest.mark.skipif(find_spec("pyvista") is None, reason="PyVista not installed")
def test_pyvista_draws_a_coloured_pipeline(tmp_path: Path):
    spec = PipelineSpec.from_profile(
        "Line",
        [0, 500, 1000, 1500],
        [-100, -120, -90, -10],
        0.3,
        [FieldSeries("Temperature", "C", (60.0, 40.0, 25.0, 15.0))],
    )
    outcome = render_scene(
        build_pipeline_scene(spec, color_by="Temperature"), tmp_path, window_size=(480, 320)
    )
    assert outcome.completed


@pytest.mark.skipif(find_spec("cadquery") is None, reason="CadQuery not installed")
def test_cadquery_exports_step_with_the_drawn_liquid_volume(tmp_path: Path):
    import cadquery as cq

    spec = _vessel()
    outcome = export_cadquery(build_vessel_scene(spec, cutaway=False, supports=False), tmp_path)
    assert outcome.completed, outcome.message
    step = tmp_path / "20-va-001.step"
    assert step.exists() and (tmp_path / "20-va-001.stl").exists()
    volumes = sorted(s.Volume() for s in cq.importers.importStep(str(step)).solids().vals())
    # Solids: nozzle, steel shell, water, oil - the two largest are the liquid phases.
    assert volumes[-2] == pytest.approx(spec.liquid_volume_m3(0.6), rel=0.02)
    assert volumes[-1] == pytest.approx(
        spec.liquid_volume_m3(1.1) - spec.liquid_volume_m3(0.6), rel=0.02
    )


@pytest.mark.skipif(which("openscad") is None, reason="OpenSCAD not installed")
def test_openscad_accepts_the_generated_file(tmp_path: Path):
    outcome = export_openscad(build_vessel_scene(_vessel()), tmp_path, png=False, stl=True)
    assert outcome.completed, outcome.message
    assert (tmp_path / "20-va-001_openscad.stl").stat().st_size > 10_000
