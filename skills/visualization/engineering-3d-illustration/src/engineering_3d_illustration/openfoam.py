"""OpenFOAM in both directions: draw a solved case, and hand geometry to a mesher.

**Results in.** ``render_openfoam_case`` reads what a solved OpenFOAM case
already holds - the ``VTK/`` folder written by ``foamToVTK`` (the last step of
every case the ``neqsim-cfd-coupling`` skill generates), or the native time
folders when no VTK export exists - and draws the field with PyVista: the outer
surface, a cut plane, a clipped view and, for a velocity, streamlines.

**Geometry out.** ``write_stl`` and ``vessel_fluid_volume_stl`` write the
wetted volume of a vessel as a watertight STL, the starting geometry for
``snappyHexMesh`` or ``cfMesh``.

A rendered field says nothing about whether the solution is converged or the
mesh adequate. The caption says so, and the CFD skill's quality gate
(``CfdCouplingModel.assess_quality``) comes before any number is quoted.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Sequence

from . import mesh as _mesh
from .mesh import TriMesh
from .model import RenderOutcome, VesselSpec, _slug, vessel_profile
from .pyvista_backend import VIEWS, _fit_camera

FOAM_VIEWS = ("surface", "slice", "clip", "streamlines")

# Units OpenFOAM uses for the common fields. Pressure and wall shear depend on
# the solver, so the caption says which reading applies instead of guessing.
_FIELD_UNITS = {
    "U": "m/s",
    "T": "K",
    "k": "m2/s2",
    "epsilon": "m2/s3",
    "omega": "1/s",
    "nut": "m2/s",
    "yPlus": "-",
    "p": "m2/s2 if incompressible (kinematic), Pa otherwise",
    "p_rgh": "Pa",
    "wallShearStress": "m2/s2 if incompressible (kinematic), Pa otherwise",
}


@dataclass(frozen=True)
class FoamOutput:
    """Where the drawable data of a case is, and for which time."""

    kind: str  # "vtk", "native" or "none"
    path: Path | None
    time: str | None
    message: str


def find_openfoam_output(case_dir: str | Path, time: str = "latest") -> FoamOutput:
    """Locate the data to draw: a ``foamToVTK`` export first, native time folders second."""
    case = Path(case_dir)
    if not case.is_dir():
        return FoamOutput("none", None, None, f"{case} is not a directory")
    vtk = case / "VTK"
    if vtk.is_dir():
        candidates: dict[str, Path] = {}
        for path in sorted(vtk.iterdir()):
            match = re.fullmatch(r".*_(\d+)\.(vtm|vtk|vtu)", path.name)
            if match and path.is_file():
                # Prefer the multiblock file when both exist for one index.
                if match.group(1) not in candidates or path.suffix == ".vtm":
                    candidates[match.group(1)] = path
        if candidates:
            if time == "latest":
                key = max(candidates, key=int)
            elif time in candidates:
                key = time
            else:
                return FoamOutput(
                    "none",
                    None,
                    None,
                    f"no VTK export for time index {time}; available: {sorted(candidates, key=int)}",
                )
            return FoamOutput(
                "vtk", candidates[key], key, f"foamToVTK export {candidates[key].name}"
            )
    times = []
    for path in case.iterdir():
        if path.is_dir():
            try:
                times.append((float(path.name), path.name))
            except ValueError:
                continue
    solved = [t for t in sorted(times) if t[0] > 0.0]
    if solved and (case / "constant" / "polyMesh").is_dir():
        if time == "latest":
            chosen = solved[-1][1]
        elif time in [t[1] for t in solved]:
            chosen = time
        else:
            return FoamOutput(
                "none", None, None, f"no time folder {time}; available: {[t[1] for t in solved]}"
            )
        return FoamOutput("native", case, chosen, f"native time folder {chosen}")
    return FoamOutput(
        "none",
        None,
        None,
        "no VTK export and no solved time folder - run the case, then foamToVTK -latestTime",
    )


def _collect(block: Any, name: str, internal: list[Any], patches: dict[str, Any]) -> None:
    """Walk a multiblock dataset into the volume mesh and the named boundary patches."""
    import pyvista as pv

    if block is None:
        return
    if isinstance(block, pv.MultiBlock):
        for index in range(block.n_blocks):
            child_name = block.get_block_name(index) or f"{name}_{index}"
            _collect(block[index], child_name, internal, patches)
    elif isinstance(block, pv.PolyData):
        patches[name] = block
    elif block.n_cells > 0:
        internal.append(block)


def read_openfoam_case(
    case_dir: str | Path, time: str = "latest"
) -> tuple[Any, dict[str, Any], FoamOutput]:
    """Read ``(volume mesh, {patch name: surface}, FoamOutput)``; needs PyVista.

    The volume mesh is ``None`` when nothing drawable was found - the reason is
    in ``FoamOutput.message``.
    """
    import pyvista as pv

    output = find_openfoam_output(case_dir, time)
    if output.kind == "none":
        return None, {}, output
    internal: list[Any] = []
    patches: dict[str, Any] = {}
    if output.kind == "vtk":
        _collect(pv.read(str(output.path)), "internal", internal, patches)
    else:
        case = Path(case_dir)
        marker = next(iter(case.glob("*.foam")), None)
        if marker is None:
            marker = case / f"{case.name}.foam"
            marker.touch()  # the empty marker file ParaView and VTK readers expect
        reader = pv.POpenFOAMReader(str(marker))
        reader.set_active_time_value(float(output.time))
        reader.enable_all_patch_arrays()
        _collect(reader.read(), "internal", internal, patches)
    if not internal:
        return None, patches, FoamOutput("none", None, None, "the export holds no volume mesh")
    return internal[0], patches, output


def _outer_surface(volume: Any) -> Any:
    try:
        return volume.extract_surface(algorithm="dataset_surface")
    except TypeError:  # PyVista releases without the algorithm keyword
        return volume.extract_surface()


def _field_array(dataset: Any, field: str) -> tuple[str, bool] | None:
    """``(association, is_vector)`` of a field on a dataset, preferring point data."""
    for association, data in (("point", dataset.point_data), ("cell", dataset.cell_data)):
        if field in data:
            array = data[field]
            return association, array.ndim == 2 and array.shape[1] == 3
    return None


def render_openfoam_case(
    case_dir: str | Path,
    output_dir: str | Path,
    *,
    field: str = "U",
    views: Sequence[str] = ("surface", "slice"),
    time: str = "latest",
    slice_normal: Sequence[float] | None = None,
    slice_origin: Sequence[float] | None = None,
    camera: str = "iso",
    colormap: str = "viridis",
    window_size: tuple[int, int] = (1600, 1000),
    show_edges: bool = False,
    title: str | None = None,
) -> RenderOutcome:
    """Draw a field of a solved OpenFOAM case to one PNG per view.

    ``views`` are chosen from ``surface`` (the outside of the volume), ``slice``
    (a cut plane - by default through the middle, normal to the shortest
    extent), ``clip`` (half removed along the same plane) and ``streamlines``
    (vector fields only, seeded on the ``inlet`` patch when there is one). A
    vector field is coloured by its magnitude. All views share one colour range.
    """
    for view in views:
        if view not in FOAM_VIEWS:
            raise ValueError(f"view must be one of {', '.join(FOAM_VIEWS)}")
    if not views:
        raise ValueError("at least one view is required")
    if camera not in VIEWS:
        raise ValueError(f"camera must be one of {', '.join(VIEWS)}")
    case = Path(case_dir)
    name = _slug(case.name)
    command = "foamToVTK -latestTime   # then call render_openfoam_case again"
    if find_spec("pyvista") is None:
        return RenderOutcome(
            "openfoam",
            "not_executed",
            (),
            "pip install pyvista",
            "PyVista is not installed; the case was not drawn",
        )

    import numpy as np
    import pyvista as pv

    volume, patches, output = read_openfoam_case(case, time)
    if volume is None:
        return RenderOutcome("openfoam", "not_executed", (), command, output.message)
    found = _field_array(volume, field)
    if found is None:
        available = sorted(set(volume.point_data.keys()) | set(volume.cell_data.keys()))
        return RenderOutcome(
            "openfoam",
            "failed",
            (),
            command,
            f"field {field!r} is not in the export; available fields: {available}",
        )
    _association, is_vector = found
    if _field_array(volume, field)[0] == "cell":
        volume = volume.cell_data_to_point_data()
    values = np.asarray(volume.point_data[field], dtype=float)
    # "|" is a column separator in VTK text, so the magnitude is spelled out.
    scalar_name = f"{field} magnitude" if is_vector else field
    volume.point_data[scalar_name] = np.linalg.norm(values, axis=1) if is_vector else values
    low = float(np.nanmin(volume.point_data[scalar_name]))
    high = float(np.nanmax(volume.point_data[scalar_name]))
    unit = _FIELD_UNITS.get(field, "-" if field.startswith("alpha") else "solver units")

    bounds = volume.bounds
    extents = [bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4]]
    if slice_normal is None:
        normal = [0.0, 0.0, 0.0]
        normal[extents.index(min(extents))] = 1.0
    else:
        normal = [float(v) for v in slice_normal]
    origin = list(slice_origin) if slice_origin is not None else list(volume.center)

    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    heading = title or f"{case.name} - {scalar_name} at time {output.time}"
    caption = (
        f"{heading}. OpenFOAM field {field}, {low:.4g} to {high:.4g} [{unit}]. "
        f"Read from {output.message}. Drawn to scale. "
        "A rendered field is not evidence of convergence or mesh adequacy - "
        "quote values only after the CFD quality gate."
    )
    bar = {
        "title": f"{scalar_name} [{unit.split(' ')[0]}]",
        "color": "black",
        "vertical": False,
        "position_x": 0.30,
        "position_y": 0.87,
        "width": 0.40,
        "height": 0.09,
        "title_font_size": 20,
        "label_font_size": 16,
        "fmt": "%.4g",
    }
    files: list[Path] = []
    skipped: list[str] = []
    for view in views:
        plotter = pv.Plotter(off_screen=True, window_size=list(window_size))
        plotter.set_background("white")
        try:
            plotter.enable_anti_aliasing("ssaa")
        except Exception:  # noqa: BLE001 - cosmetic
            pass
        common = {
            "scalars": scalar_name,
            "cmap": colormap,
            "clim": (low, high),
            "scalar_bar_args": bar,
        }
        outline = _outer_surface(volume)
        if view == "surface":
            plotter.add_mesh(outline, show_edges=show_edges, **common)
        elif view == "slice":
            plotter.add_mesh(volume.slice(normal=normal, origin=origin), **common)
            plotter.add_mesh(outline, color=(0.6, 0.63, 0.67), opacity=0.12)
        elif view == "clip":
            # Keep the half behind the plane as seen from the camera, so the cut face shows.
            facing = sum(n * d for n, d in zip(normal, VIEWS[camera][0])) > 0.0
            half = volume.clip(normal=normal, origin=origin, invert=not facing)
            plotter.add_mesh(half, show_edges=show_edges, **common)
        else:
            if not is_vector:
                skipped.append("streamlines need a vector field")
                plotter.close()
                continue
            seeds = patches.get("inlet")
            if seeds is None or seeds.n_points == 0:
                seeds = volume.slice(normal=normal, origin=origin)
            step = max(1, seeds.n_points // 120)
            source = pv.PolyData(np.asarray(seeds.points)[::step])
            lines = volume.streamlines_from_source(
                source, vectors=field, integration_direction="both", max_steps=4000
            )
            if lines.n_points == 0:
                skipped.append("no streamlines could be traced")
                plotter.close()
                continue
            radius = 0.004 * max(extents)
            plotter.add_mesh(lines.tube(radius=radius), **common)
            plotter.add_mesh(outline, color=(0.6, 0.63, 0.67), opacity=0.12)
        plotter.add_text(heading, position="upper_left", font_size=12, color="black")
        plotter.add_text(
            textwrap.fill(caption, width=max(60, window_size[0] // 11)),
            position="lower_left",
            font_size=9,
            color="black",
        )
        _fit_camera(plotter, bounds, camera, window_size, 1.3)
        image = directory / f"{name}_{field}_{view}.png"
        plotter.screenshot(str(image))
        plotter.close()
        files.append(image)
    if not files:
        return RenderOutcome("openfoam", "failed", (), command, "; ".join(skipped), caption)
    caption_file = directory / f"{name}_{field}_caption.txt"
    caption_file.write_text(caption + "\n", encoding="utf-8")
    files.append(caption_file)
    message = f"rendered {len(files) - 1} view(s) of {field} from {output.message}"
    if skipped:
        message += "; skipped: " + "; ".join(skipped)
    return RenderOutcome("openfoam", "completed", tuple(files), command, message, caption)


# ------------------------------------------------------------------ geometry out


def write_stl(mesh: TriMesh, path: str | Path, solid_name: str = "walls") -> Path:
    """Write a triangle mesh as an ASCII STL with a named solid (the OpenFOAM patch name)."""
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", solid_name):
        raise ValueError("solid_name must be a plain identifier - it becomes the patch name")
    lines = [f"solid {solid_name}"]
    for a, b, c in mesh.triangles:
        pa, pb, pc = mesh.vertices[a], mesh.vertices[b], mesh.vertices[c]
        ux, uy, uz = pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]
        vx, vy, vz = pc[0] - pa[0], pc[1] - pa[1], pc[2] - pa[2]
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        length = (nx * nx + ny * ny + nz * nz) ** 0.5
        if length <= 0.0:
            continue  # a degenerate triangle carries no surface
        lines.append(f" facet normal {nx / length:.6e} {ny / length:.6e} {nz / length:.6e}")
        lines.append("  outer loop")
        for point in (pa, pb, pc):
            lines.append(f"   vertex {point[0]:.6e} {point[1]:.6e} {point[2]:.6e}")
        lines.append("  endloop")
        lines.append(" endfacet")
    lines.append(f"endsolid {solid_name}")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def vessel_fluid_volume_stl(
    spec: VesselSpec, path: str | Path, *, solid_name: str = "walls", segments: int = 96
) -> Path:
    """Write the inside volume of a vessel as one closed STL surface.

    The surface is the wetted wall only: it has no nozzle openings, so inlet
    and outlet patches still have to be defined in the mesher. It is the right
    starting point for a closed-domain case (sloshing, settling, cooldown of a
    shut-in vessel) and for ``snappyHexMesh`` with separately defined inlets.
    The vessel sits as in the illustration: lowest inside point at ``z = 0``.
    """
    profile = vessel_profile(spec.radius_m, spec.tan_tan_length_m, spec.head_depth_m)
    if spec.orientation == "horizontal":
        origin, axis = (0.0, 0.0, spec.radius_m), (1.0, 0.0, 0.0)
    else:
        origin, axis = (0.0, 0.0, spec.head_depth_m), (0.0, 0.0, 1.0)
    return write_stl(_mesh.revolve(profile, origin, axis, segments), path, solid_name)
