"""Shared helper for the examples: draw one scene with every backend that is installed."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from engineering_3d_illustration import (  # noqa: E402
    detect_backends,
    export_cadquery,
    export_openscad,
    render_blender,
    render_scene,
)

OUTPUT = Path(__file__).resolve().parent / "output"


def draw_everywhere(scene, *, views=("iso",), colormap="viridis", cad=True, blender=False):
    """Draw ``scene`` with each available backend and report what happened.

    Blender is off by default because a Cycles render takes from tens of seconds
    to minutes on a CPU; pass ``--blender`` on the command line to include it.
    """
    print(scene.caption())
    print("backends available:", detect_backends())
    outcomes = [render_scene(scene, OUTPUT, views=views, colormap=colormap)]
    if cad:
        outcomes.append(export_cadquery(scene, OUTPUT))
        outcomes.append(export_openscad(scene, OUTPUT))
    if blender or "--blender" in sys.argv:
        outcomes.append(
            render_blender(
                scene, OUTPUT, samples=48, resolution=(1600, 900), colormap_name=colormap
            )
        )
    for outcome in outcomes:
        print(f"[{outcome.backend}] {outcome.status}: {outcome.message}")
        for path in outcome.files:
            print("   ", path)
        if not outcome.completed:
            print("    run:", outcome.command)
    return outcomes
