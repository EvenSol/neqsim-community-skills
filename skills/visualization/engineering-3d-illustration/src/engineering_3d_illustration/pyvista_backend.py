"""Render a scene off-screen with PyVista: the default backend for report figures.

PyVista is optional. When it is missing the render is reported as not executed,
with the install command, and nothing else in the skill is affected.

The renderer shows what the scene holds and adds nothing of its own: colours
come from the scene palette or from the calculated field, labels are the scene
labels, and the caption written next to each image is ``Scene.caption()`` - so
every out-of-scale choice made when the scene was built is stated in the figure.
"""

from __future__ import annotations

import textwrap
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Sequence

from .model import Primitive, RenderOutcome, Scene, tessellate

VIEWS: dict[str, tuple[tuple[float, float, float], tuple[float, float, float], bool]] = {
    # name: (direction from the focal point to the camera, view-up, parallel projection)
    "iso": ((-0.55, -1.0, 0.55), (0.0, 0.0, 1.0), False),
    "iso_back": ((0.55, 1.0, 0.55), (0.0, 0.0, 1.0), False),
    "front": ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0), True),
    "side": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), True),
    "top": ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0), True),
}

_SMOOTH_KINDS = ("revolved", "cylinder", "tube")
_INSTALL = "pip install pyvista"


def detect_pyvista() -> bool:
    """Whether PyVista is importable in this environment."""
    return find_spec("pyvista") is not None


def primitive_polydata(primitive: Primitive) -> Any:
    """The clipped PyVista mesh of one primitive, or ``None`` if nothing is left.

    A closed solid is clipped with capping, so a cut face (a liquid surface, a
    sectioned wall) is a real surface and the clipped mesh still encloses the
    right volume.
    """
    import numpy as np
    import pyvista as pv

    tri = tessellate(primitive)
    faces = np.hstack([np.full((len(tri.triangles), 1), 3), np.asarray(tri.triangles)]).ravel()
    mesh = pv.PolyData(np.asarray(tri.vertices, dtype=float), faces)
    if tri.scalars is not None:
        mesh.point_data[_scalar_title(primitive)] = np.asarray(tri.scalars, dtype=float)
    if primitive.clip is None:
        return mesh
    closed = tri.is_closed()
    low, high = (0, 2, 4), (1, 3, 5)
    for axis in range(3):
        for index, sign in ((low[axis], 1.0), (high[axis], -1.0)):
            limit = primitive.clip[index]
            if limit is None:
                continue
            bounds = mesh.bounds
            if sign > 0 and bounds[2 * axis] >= limit:
                continue  # already entirely on the kept side
            if sign < 0 and bounds[2 * axis + 1] <= limit:
                continue
            normal = [0.0, 0.0, 0.0]
            origin = [0.0, 0.0, 0.0]
            origin[axis] = limit
            if closed:
                # clip_closed_surface keeps the side the normal points to.
                normal[axis] = sign
                mesh = mesh.clip_closed_surface(normal=normal, origin=origin)
            else:
                # clip removes the side the normal points to.
                normal[axis] = -sign
                mesh = mesh.clip(normal=normal, origin=origin)
            if mesh.n_points == 0 or mesh.n_cells == 0:
                return None
    return mesh


def _scalar_title(primitive: Primitive) -> str:
    name = primitive.scalar_name or "value"
    return f"{name} [{primitive.scalar_unit}]" if primitive.scalar_unit else name


def _fit_camera(
    plotter: Any,
    bounds: Sequence[float],
    view: str,
    window_size: tuple[int, int],
    margin: float,
) -> None:
    """Place the camera so the scene bounds fill the frame from the chosen direction."""
    from math import radians, sqrt, tan

    direction, up, parallel = VIEWS[view]
    length = sqrt(sum(d * d for d in direction))
    w = tuple(d / length for d in direction)  # from the focal point towards the camera
    right = (
        up[1] * w[2] - up[2] * w[1],
        up[2] * w[0] - up[0] * w[2],
        up[0] * w[1] - up[1] * w[0],
    )
    length = sqrt(sum(d * d for d in right))
    right = tuple(d / length for d in right)
    true_up = (
        w[1] * right[2] - w[2] * right[1],
        w[2] * right[0] - w[0] * right[2],
        w[0] * right[1] - w[1] * right[0],
    )
    focal = tuple((bounds[2 * i] + bounds[2 * i + 1]) / 2.0 for i in range(3))
    aspect = window_size[0] / window_size[1]
    half_angle = tan(radians(plotter.camera.view_angle) / 2.0)
    distance = half_height = half_width = depth_max = 0.0
    for ix in (0, 1):
        for iy in (2, 3):
            for iz in (4, 5):
                offset = (bounds[ix] - focal[0], bounds[iy] - focal[1], bounds[iz] - focal[2])
                across = abs(sum(o * r for o, r in zip(offset, right)))
                height = abs(sum(o * u for o, u in zip(offset, true_up)))
                depth = sum(o * d for o, d in zip(offset, w))
                half_width, half_height = max(half_width, across), max(half_height, height)
                depth_max = max(depth_max, depth)
                distance = max(
                    distance,
                    depth + height / half_angle,
                    depth + across / (half_angle * aspect),
                )
    if parallel:
        distance = depth_max + 2.0 * max(half_width, half_height, 1e-6)
    distance = max(distance * margin, 1e-6)
    position = tuple(focal[i] + w[i] * distance for i in range(3))
    plotter.camera_position = [position, focal, true_up]
    if parallel:
        plotter.enable_parallel_projection()
        plotter.camera.parallel_scale = max(half_height, half_width / aspect, 1e-6) * margin
    plotter.reset_camera_clipping_range()


def render_scene(
    scene: Scene,
    output_dir: str | Path,
    *,
    views: Sequence[str] = ("iso",),
    window_size: tuple[int, int] = (1600, 1000),
    colormap: str = "viridis",
    background: str = "white",
    show_labels: bool = True,
    show_caption: bool = True,
    margin: float = 1.18,
    export_gltf: bool = False,
) -> RenderOutcome:
    """Render ``scene`` to one PNG per view, plus a caption text file.

    ``views`` are chosen from ``iso``, ``iso_back``, ``front``, ``side`` and
    ``top``; the orthographic views use a parallel projection so lengths can be
    compared across the image. ``margin`` is the free space left around the
    scene for labels, title and caption (1.0 fills the frame). ``export_gltf`` also writes a ``.gltf`` of the
    scene for a web viewer or for Blender.
    """
    for view in views:
        if view not in VIEWS:
            raise ValueError(f"view must be one of {', '.join(VIEWS)}")
    if not views:
        raise ValueError("at least one view is required")
    directory = Path(output_dir)
    caption = scene.caption()
    command = f'{_INSTALL} && python -c "from engineering_3d_illustration import render_scene"'
    if not detect_pyvista():
        return RenderOutcome(
            backend="pyvista",
            status="not_executed",
            files=(),
            command=_INSTALL,
            message="PyVista is not installed; the scene was built but not drawn",
            caption=caption,
        )

    import pyvista as pv

    directory.mkdir(parents=True, exist_ok=True)
    meshes = [(p, primitive_polydata(p)) for p in scene.primitives]
    meshes = [(p, m) for p, m in meshes if m is not None]
    if not meshes:
        return RenderOutcome(
            backend="pyvista",
            status="failed",
            files=(),
            command=command,
            message="nothing left to draw after clipping",
            caption=caption,
        )

    files: list[Path] = []
    for view in views:
        plotter = pv.Plotter(off_screen=True, window_size=list(window_size))
        plotter.set_background(background)
        try:
            plotter.enable_anti_aliasing("ssaa")
        except Exception:  # noqa: BLE001 - anti-aliasing is cosmetic
            pass
        for primitive, mesh in meshes:
            smooth = primitive.kind in _SMOOTH_KINDS
            options: dict[str, Any] = {
                "opacity": primitive.opacity,
                "smooth_shading": smooth,
                "split_sharp_edges": smooth,
                "feature_angle": 40.0,
                "specular": 0.25 if primitive.role in ("shell", "nozzle", "equipment") else 0.05,
                "ambient": 0.25,
                "diffuse": 0.8,
            }
            if primitive.scalars is not None:
                plotter.add_mesh(
                    mesh,
                    scalars=_scalar_title(primitive),
                    cmap=colormap,
                    clim=primitive.scalar_range,
                    scalar_bar_args={
                        "title": _scalar_title(primitive),
                        "color": "black",
                        "vertical": False,
                        "position_x": 0.30,
                        "position_y": 0.87,
                        "width": 0.40,
                        "height": 0.09,
                        "title_font_size": 20,
                        "label_font_size": 16,
                        "fmt": "%.4g",
                    },
                    **options,
                )
            else:
                plotter.add_mesh(mesh, color=primitive.color, **options)
        if show_labels and scene.labels:
            plotter.add_point_labels(
                [list(label.position) for label in scene.labels],
                [label.text for label in scene.labels],
                font_size=max(12, window_size[1] // 60),
                text_color="black",
                shape_color="white",
                shape_opacity=0.75,
                show_points=False,
                always_visible=True,
                margin=4,
            )
        if show_caption:
            plotter.add_text(scene.title, position="upper_left", font_size=12, color="black")
            wrapped = textwrap.fill(caption, width=max(60, window_size[0] // 11))
            plotter.add_text(wrapped, position="lower_left", font_size=9, color="black")

        _fit_camera(plotter, scene.bounds(), view, window_size, margin)

        image = directory / f"{scene.name}_{view}.png"
        plotter.screenshot(str(image))
        files.append(image)
        if export_gltf and view == views[0]:
            gltf = directory / f"{scene.name}.gltf"
            try:
                plotter.export_gltf(str(gltf))
                files.append(gltf)
            except Exception:  # noqa: BLE001 - the PNG is the deliverable
                pass
        plotter.close()

    caption_file = directory / f"{scene.name}_caption.txt"
    caption_file.write_text(caption + "\n", encoding="utf-8")
    files.append(caption_file)
    return RenderOutcome(
        backend="pyvista",
        status="completed",
        files=tuple(files),
        command=command,
        message=f"rendered {len(views)} view(s) of {len(meshes)} parts",
        caption=caption,
    )
