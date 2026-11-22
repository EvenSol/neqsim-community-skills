"""Presentation render of a scene with Blender (Cycles), run headless.

The scene is written as a job file (meshes, colours, cut boxes, camera) next to
a fixed render script. The script needs nothing but Blender's own ``bpy``, so
it runs with a Blender install (``blender -b -P``) or with the ``bpy`` wheel,
on this machine or another one.

A Blender image has no labels and no colour legend. It is the picture for a
front page or a slide; the PyVista figure with its caption is the one that
carries the numbers. Both are drawn from the same scene.
"""

from __future__ import annotations

import json
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path
from shutil import which
from typing import Any

from .cad_backends import _clip_box
from .model import RenderOutcome, Scene, colormap, tessellate
from .pyvista_backend import VIEWS

# Surface finish per role: (metallic, roughness).
_FINISH: dict[str, tuple[float, float]] = {
    "shell": (0.45, 0.38),
    "nozzle": (0.45, 0.38),
    "support": (0.2, 0.6),
    "equipment": (0.3, 0.45),
    "pipeline": (0.3, 0.45),
    "internal": (0.3, 0.5),
    "oil": (0.0, 0.12),
    "water": (0.0, 0.08),
    "liquid": (0.0, 0.08),
    "deck": (0.0, 0.9),
    "seabed": (0.0, 0.95),
}
_SMOOTH_KINDS = ("revolved", "cylinder", "tube")


def _linear(channel: float) -> float:
    """sRGB to linear, which is what Blender materials and colour attributes expect."""
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def blender_job(
    scene: Scene,
    *,
    view: str = "iso",
    resolution: tuple[int, int] = (1920, 1080),
    samples: int = 64,
    colormap_name: str = "viridis",
    ground: bool = True,
    transparent: bool = False,
    margin: float = 1.1,
    output: str | None = None,
) -> dict[str, Any]:
    """The render job as plain data: triangles, materials, cut boxes and camera."""
    if view not in VIEWS:
        raise ValueError(f"view must be one of {', '.join(VIEWS)}")
    if samples < 1:
        raise ValueError("samples must be at least 1")
    direction, up, parallel = VIEWS[view]
    parts = []
    for primitive in scene.primitives:
        tri = tessellate(primitive)
        metallic, roughness = _FINISH.get(primitive.role, (0.2, 0.5))
        part: dict[str, Any] = {
            "name": primitive.name,
            "vertices": [list(v) for v in tri.vertices],
            "triangles": [list(t) for t in tri.triangles],
            "color": [_linear(c) for c in primitive.color],
            "opacity": primitive.opacity,
            "metallic": metallic,
            "roughness": roughness,
            "smooth": primitive.kind in _SMOOTH_KINDS,
        }
        if tri.scalars is not None:
            low, high = primitive.scalar_range or (min(tri.scalars), max(tri.scalars))
            part["vertex_colors"] = [
                [_linear(c) for c in colormap(value, low, high, colormap_name)]
                for value in tri.scalars
            ]
        if primitive.clip is not None and tri.is_closed():
            corner, size = _clip_box(scene, primitive.clip)
            part["clip_corner"], part["clip_size"] = corner, size
        parts.append(part)
    return {
        "name": scene.name,
        "caption": scene.caption(),
        "bounds": list(scene.bounds()),
        "camera": {
            "direction": list(direction),
            "up": list(up),
            "parallel": parallel,
            "margin": margin,
        },
        "resolution": list(resolution),
        "samples": int(samples),
        "ground": bool(ground),
        "transparent": bool(transparent),
        "output": output or f"{scene.name}_blender_{view}.png",
        "parts": parts,
    }


BLENDER_SCRIPT = r'''"""Render a neqsim-engineering-3d-illustration job with Blender Cycles.

Run:  blender -b -P blender_render.py -- job.json
 or:  python blender_render.py job.json        (with the bpy wheel installed)
"""

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
job_path = Path(arguments[0]).resolve()
job = json.loads(job_path.read_text(encoding="utf-8"))

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
collection = scene.collection


def new_object(name, vertices, faces):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


def material(name, color, opacity, metallic, roughness, vertex_colors=False):
    mat = bpy.data.materials.new(name)
    if mat.node_tree is None:
        mat.use_nodes = True
    tree = mat.node_tree
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
    tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    bsdf.inputs["Base Color"].default_value = (color[0], color[1], color[2], 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Alpha"].default_value = opacity
    if vertex_colors:
        attribute = tree.nodes.new("ShaderNodeVertexColor")
        attribute.layer_name = "field"
        tree.links.new(attribute.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def cut_to_box(obj, corner, size):
    x, y, z = corner
    dx, dy, dz = size
    vertices = [
        (x, y, z), (x + dx, y, z), (x + dx, y + dy, z), (x, y + dy, z),
        (x, y, z + dz), (x + dx, y, z + dz), (x + dx, y + dy, z + dz), (x, y + dy, z + dz),
    ]
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    cutter = new_object(obj.name + "_cut", vertices, faces)
    modifier = obj.modifiers.new("cut", "BOOLEAN")
    modifier.operation = "INTERSECT"
    modifier.object = cutter
    try:
        modifier.solver = "EXACT"
    except TypeError:
        pass
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    result = bpy.data.meshes.new_from_object(evaluated)
    obj.modifiers.clear()
    obj.data = result
    bpy.data.objects.remove(cutter, do_unlink=True)


for part in job["parts"]:
    obj = new_object(part["name"], part["vertices"], part["triangles"])
    colored = "vertex_colors" in part
    if colored:
        attribute = obj.data.color_attributes.new(name="field", type="FLOAT_COLOR", domain="POINT")
        flat = []
        for r, g, b in part["vertex_colors"]:
            flat.extend((r, g, b, 1.0))
        attribute.data.foreach_set("color", flat)
    if "clip_corner" in part:
        cut_to_box(obj, part["clip_corner"], part["clip_size"])
        if len(obj.data.polygons) == 0:
            bpy.data.objects.remove(obj, do_unlink=True)
            continue
    if part["smooth"]:
        for polygon in obj.data.polygons:
            polygon.use_smooth = True
        if hasattr(obj.data, "set_sharp_from_angle"):
            obj.data.set_sharp_from_angle(angle=math.radians(40.0))
        elif hasattr(obj.data, "use_auto_smooth"):
            obj.data.use_auto_smooth = True
            obj.data.auto_smooth_angle = math.radians(40.0)
    # A cut mesh can come back with empty material slots; start from a clean one.
    obj.data.materials.clear()
    obj.data.materials.append(
        material(part["name"], part["color"], part["opacity"], part["metallic"],
                 part["roughness"], colored)
    )
    for polygon in obj.data.polygons:
        polygon.material_index = 0

bounds = job["bounds"]
centre = Vector(((bounds[0] + bounds[1]) / 2, (bounds[2] + bounds[3]) / 2, (bounds[4] + bounds[5]) / 2))
extent = max(bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4])

if job["ground"]:
    half = 30.0 * extent
    z = bounds[4] - 0.002 * extent
    ground = new_object(
        "ground",
        [(centre.x - half, centre.y - half, z), (centre.x + half, centre.y - half, z),
         (centre.x + half, centre.y + half, z), (centre.x - half, centre.y + half, z)],
        [(0, 1, 2, 3)],
    )
    ground.data.materials.append(material("ground", (0.9, 0.9, 0.9), 1.0, 0.0, 0.9))
    if job["transparent"]:
        ground.is_shadow_catcher = True

world = bpy.data.worlds.new("world")
scene.world = world
if world.node_tree is None:
    world.use_nodes = True
background = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
background.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
background.inputs["Strength"].default_value = 0.55

camera_job = job["camera"]
toward = Vector(camera_job["direction"]).normalized()
sun_data = bpy.data.lights.new("sun", "SUN")
sun_data.energy = 2.2
sun_data.angle = math.radians(12.0)
sun = bpy.data.objects.new("sun", sun_data)
collection.objects.link(sun)
side = toward.cross(Vector((0.0, 0.0, 1.0)))
if side.length < 1e-6:
    side = Vector((1.0, 0.0, 0.0))
light_from = (toward * 0.6 + side.normalized() * 0.5 + Vector((0.0, 0.0, 1.0))).normalized()
sun.rotation_euler = (-light_from).to_track_quat("-Z", "Y").to_euler()

camera_data = bpy.data.cameras.new("camera")
camera = bpy.data.objects.new("camera", camera_data)
collection.objects.link(camera)
scene.camera = camera
width, height = job["resolution"]
aspect = width / height
up = Vector(camera_job["up"])
right = up.cross(toward).normalized()
true_up = toward.cross(right).normalized()
half_h = math.tan(camera_data.angle / 2.0)  # horizontal half-angle for a landscape frame
half_v = half_h / aspect
distance = half_width = half_height = depth_max = 0.0
for x in bounds[0:2]:
    for y in bounds[2:4]:
        for z in bounds[4:6]:
            offset = Vector((x, y, z)) - centre
            across, rise, depth = abs(offset.dot(right)), abs(offset.dot(true_up)), offset.dot(toward)
            half_width, half_height = max(half_width, across), max(half_height, rise)
            depth_max = max(depth_max, depth)
            distance = max(distance, depth + rise / half_v, depth + across / half_h)
if camera_job["parallel"]:
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = max(2 * half_width, 2 * half_height * aspect) * camera_job["margin"]
    distance = depth_max + 2.0 * extent
distance *= camera_job["margin"]
camera.location = centre + toward * distance
camera.rotation_euler = (-toward).to_track_quat("-Z", "Y").to_euler()
camera_data.clip_start = max(distance * 1e-3, 1e-3)
camera_data.clip_end = distance * 10.0 + 60.0 * extent

scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = job["samples"]
try:
    scene.cycles.use_denoising = True
except Exception:
    pass
scene.render.resolution_x = width
scene.render.resolution_y = height
scene.render.resolution_percentage = 100
scene.render.film_transparent = bool(job["transparent"])
scene.render.image_settings.file_format = "PNG"
try:
    scene.view_settings.view_transform = "Standard"
except TypeError:
    pass
scene.render.filepath = str(job_path.parent / job["output"])
bpy.ops.render.render(write_still=True)
print("rendered", scene.render.filepath)
'''


def write_blender_job(scene: Scene, output_dir: str | Path, **options: Any) -> tuple[Path, Path]:
    """Write ``blender_render.py`` and ``<scene>_blender_job.json``; return both paths."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "blender_render.py"
    script.write_text(BLENDER_SCRIPT, encoding="utf-8")
    job = directory / f"{scene.name}_blender_job.json"
    job.write_text(json.dumps(blender_job(scene, **options)), encoding="utf-8")
    return script, job


def render_blender(
    scene: Scene, output_dir: str | Path, *, timeout_s: float = 1800.0, **options: Any
) -> RenderOutcome:
    """Write the Blender job and render it if Blender or the ``bpy`` wheel is available.

    ``options`` are those of :func:`blender_job` (``view``, ``resolution``,
    ``samples``, ``colormap_name``, ``ground``, ``transparent``, ``margin``).
    """
    script, job = write_blender_job(scene, output_dir, **options)
    directory = script.parent
    image = directory / json.loads(job.read_text(encoding="utf-8"))["output"]
    command = f"blender -b -P {script.name} -- {job.name}"
    executable = which("blender")
    if executable is not None:
        arguments = [executable, "-b", "--python-exit-code", "1", "-P", script.name, "--", job.name]
    elif find_spec("bpy") is not None:
        arguments = [sys.executable, script.name, job.name]
        command = f"python {script.name} {job.name}"
    else:
        return RenderOutcome(
            backend="blender",
            status="not_executed",
            files=(script, job),
            command=command,
            message="Blender is not installed; the render job was written but not run",
            caption=scene.caption(),
        )
    try:
        result = subprocess.run(
            arguments, cwd=directory, capture_output=True, text=True, timeout=timeout_s
        )
    except subprocess.TimeoutExpired:
        return RenderOutcome(
            "blender",
            "failed",
            (script, job),
            command,
            f"timed out after {timeout_s:.0f} s",
            scene.caption(),
        )
    if result.returncode != 0 or not image.exists():
        return RenderOutcome(
            "blender",
            "failed",
            (script, job),
            command,
            (result.stderr or result.stdout).strip()[-600:],
            scene.caption(),
        )
    return RenderOutcome(
        backend="blender",
        status="completed",
        files=(image, script, job),
        command=command,
        message="rendered with Cycles; no labels or legend are drawn in this image",
        caption=scene.caption(),
    )
