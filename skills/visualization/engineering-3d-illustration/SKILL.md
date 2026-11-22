---
name: neqsim-engineering-3d-illustration
version: "0.1.0"
description: "Illustrate NeqSim designs and calculated results in three dimensions with open tools. One backend-neutral scene describes a vessel cutaway with liquid levels, internals and nozzles, a pipeline profile coloured by a calculated field, an equipment layout coloured by utilisation, or a process area with equipment, valves and routed piping carrying a stream value; the scene is then drawn off-screen with PyVista for report figures, exported as exact solids (STEP, STL, glTF) with a generated CadQuery script, written as an editable OpenSCAD file, or rendered with Blender Cycles for presentation. Reads geometry and results from a NeqSim Separator and PipeBeggsAndBrills, draws the fields of a solved OpenFOAM case (surface, cut plane, clipped view, streamlines) for the CFD coupling skill, and writes a vessel's wetted volume as STL for a mesher. Every out-of-scale choice - vertical exaggeration, enlarged pipe diameter, assumed wall thickness - is recorded in the scene and printed in the caption, and labelled quantities are computed from the geometry that is drawn. USE WHEN: a study, report or presentation needs a 3D figure of equipment, piping, a pipeline or a layout with its calculated results; a NeqSim separator, pipeline or process area should be shown rather than tabulated; a STEP, STL or OpenSCAD model of screening geometry is needed; an OpenFOAM result needs a figure; or a rendered image is wanted for a front page."
last_verified: "2026-11-22"
requires:
  python_packages: []
  java_packages: []
  env: []
  network: []
---

# Engineering 3D Illustration

A study ends in numbers: a liquid level, a temperature along a flowline, a
utilisation per item of equipment. A table carries them; a picture makes a reader
see which vessel is full, where the line gets cold and which item is the
bottleneck. This skill turns those numbers into 3D figures with open tools, and
keeps the picture tied to the calculation that produced it.

It works in two steps. A **scene** is built from engineering inputs by
dependency-free Python. A **backend** then draws it:

| Backend | What it gives | Use it for |
|---|---|---|
| PyVista | Off-screen PNG with labels, colour legend and caption; optional glTF | Report figures - the default |
| CadQuery | Exact solids as STEP, STL and glTF, from a generated script | Exchange with CAD and layout tools |
| OpenSCAD | A small readable `.scad` file, preview PNG, STL | A model anyone can open and edit |
| Blender | Cycles render with materials and shadows | A front page or a slide |

All four are optional. Without any of them the scene, its caption and the
CadQuery, OpenSCAD and Blender scripts are still produced, with the command to
run them elsewhere.

## When to Use

- A report or presentation needs a figure of a separator, scrubber or column with
  its levels, of a pipeline with its temperature or pressure, or of a process
  area with its equipment, valves and piping.
- A NeqSim `Separator` or `PipeBeggsAndBrills` has been run and the result should
  be shown on the geometry.
- A tie-in or debottlenecking study wants utilisation and stream conditions on
  one 3D picture.
- A STEP, STL or OpenSCAD model of screening-level geometry is needed downstream.
- A solved OpenFOAM case needs figures, or a vessel volume is needed as STL for a
  mesher.

## When *Not* to Use

- As a design, fabrication or layout drawing. Shapes are envelopes and positions
  are as supplied; nothing is checked for clash, access or code compliance.
- To make a result look more certain than it is. A figure is drawn after the
  calculation has been checked, never instead of checking it.
- For 2D process flow diagrams or plots - use a PFD or plotting tool.
- For AI-generated imagery. Everything here is computed from stated inputs and is
  reproducible.

## Inputs

| Builder | Input | Meaning |
|---|---|---|
| `VesselSpec` | `tag`, `inside_diameter_m`, `tan_tan_length_m` | Vessel identity and size in metres |
| | `orientation`, `head_type` | `horizontal` or `vertical`; `elliptical_2_1`, `hemispherical` or `flat` |
| | `wall_thickness_m` | Optional; when omitted a visible thickness is assumed and declared |
| | `liquid_level_m`, `interface_level_m` | Heights in metres above the lowest inside point; the interface is water below oil |
| | `level_marks_m` | Named levels to label, for example `{"HLL": 1.8, "LLL": 0.5}` |
| | `nozzles`, `internals` | `Nozzle(name, location, position_fraction, diameter_m)` and `Internal(name, kind, position_fraction, thickness_m, bottom_m, top_m)` with kinds `weir`, `baffle`, `demister`, `inlet_device` |
| `PipelineSpec` | `points` or `from_profile(distance_m, elevation_m)` | Centreline in metres |
| | `outside_diameter_m`, `fields` | True diameter; `FieldSeries(name, unit, values)` with one value per point |
| `build_pipeline_scene` | `color_by`, `vertical_exaggeration`, `display_diameter_m` | Field to colour by; exaggeration and display diameter default to automatic, declared values |
| `LayoutSpec` | `blocks`, `decks` | `EquipmentBlock(tag, kind, position, size_m, rotation_deg, utilisation)` |
| `PlantSpec` | `equipment`, `pipes`, `decks`, `value_name`, `value_unit` | `Equipment` of kind `horizontal_vessel`, `vertical_vessel`, `column`, `heat_exchanger`, `pump`, `compressor` or `box`; `PipeRun(name, points, outside_diameter_m, value, valves)`; `InlineValve(tag, fraction, kind)` with kinds `manual`, `control`, `check` |
| `render_openfoam_case` | `case_dir`, `field`, `views`, `time` | A solved case; a field such as `U`, `p`, `T`, `alpha.water`; views from `surface`, `slice`, `clip`, `streamlines` |

`utilisation` is whatever the study calculated, with 1.0 meaning at the limit.

## Outputs

| Output | Contents |
|---|---|
| `Scene` | Primitives, labels, `notes`, `true_scale`, `facts` and `caption()` |
| `VesselSpec.total_volume_m3`, `liquid_volume_m3(level)` | Closed-form volumes of the vessel and of the liquid below a level |
| `PipelineSpec.chainage_m()`, `low_points()`, `suggested_vertical_exaggeration()` | True length along the pipe, labelled low points, a round exaggeration factor |
| `render_scene` | One PNG per view (`iso`, `iso_back`, `front`, `side`, `top`), a caption text file, optional glTF |
| `cadquery_script` / `export_cadquery` | A self-contained script; STEP, STL and GLB when CadQuery is installed |
| `openscad_script` / `export_openscad` | A `.scad` file with one module per part; preview PNG and STL when OpenSCAD is installed |
| `blender_job` / `render_blender` | A render job and script; a Cycles PNG when Blender or the `bpy` wheel is installed |
| `render_openfoam_case` | One PNG per view of the chosen field, with range and units in the caption |
| `vessel_fluid_volume_stl`, `write_stl` | The wetted volume of a vessel as a watertight, named STL solid |
| `RenderOutcome` | `status` (`completed`, `not_executed`, `failed`), `files`, the `command` to run elsewhere, `message`, `caption` |
| `recommend_backend`, `detect_backends` | Which backend fits a purpose and which are installed |

## Engineering Method

**One scene, several backends.** A scene holds five primitive kinds: `revolved`
(an outline turned about an axis), `cylinder`, `box`, `tube` and `ribbon`. A
vessel shell, a liquid phase, a weir, a valve body and a pump casing are all
built from these, so each backend implements five shapes and no equipment logic.
The PyVista figure, the STEP file and the Blender render therefore show the same
geometry.

**Cut, do not redraw.** A liquid phase is the vessel's inside outline clipped
between two level planes; a weir is the same outline clipped to a thin slab; a
cutaway is everything clipped at the centre plane. Because the liquid is cut from
the vessel shape, its drawn volume is the real partial volume, heads included.

**Labels come from the drawn geometry.** The inventory in the caption uses the
closed-form partial volume at the level the fill is clipped to. For a horizontal
vessel of radius $R$, tan-tan length $L$ and head depth $c$, filled to height $h$:

$$V(h) = L\left[R^2\cos^{-1}\frac{R-h}{R} - (R-h)\sqrt{2Rh-h^2}\right]
+ \frac{c}{R}\,\frac{\pi h^2(3R-h)}{3}$$

The second term is both heads together - a sphere scaled by $c/R$ along the
axis. A vertical vessel is integrated head, shell, head. The tests check the
tessellated and clipped solids against these formulas, in PyVista and in the
exported STEP.

**Out-of-scale choices are declared.** A 30 km flowline with 300 m of relief and
a 0.3 m pipe cannot be drawn to scale. The scene picks a round vertical
exaggeration and a display diameter, records both in `Scene.notes`, sets
`true_scale` to false, and `caption()` prints them. An unspecified wall thickness
is handled the same way. Vessels, layouts and process areas are drawn to scale.

**One colour scale per quantity.** Pipe runs in a process area share one range,
so two runs are comparable by colour. Utilisation uses a fixed legend - green up
to 0.70, amber at 0.90, red from 1.00 - which is printed in the caption.

**Process areas.** Equipment is placed by its footprint centre and turned about
the vertical. `Equipment.port(side, along)` returns a connection point on its
envelope and `route(start, end, order)` an axis-parallel path between two points.
Pipes are drawn at their true diameter with rounded bends, and a valve sits at a
fraction of the routed length, with its operator upright.

**Backend choice.**

| Purpose | Backend | Reason |
|---|---|---|
| `results_figure` | PyVista | Fields, labels, legend, caption |
| `cad_exchange` | CadQuery | Exact solids, STEP |
| `editable_model` | OpenSCAD | Plain text, no Python needed to open it |
| `presentation_render` | Blender | Materials and shadows; no labels or legend |

CAD solids carry colour but no field values. A pipeline coloured by temperature is
drawn with PyVista; its CAD export is the plain geometry.

**OpenFOAM.** `render_openfoam_case` reads the `VTK/` folder that `foamToVTK`
writes - the last step of every case the `neqsim-cfd-coupling` skill generates -
and falls back to the native time folders. A vector field is coloured by its
magnitude, the default cut plane is normal to the shortest extent of the domain,
and streamlines are seeded on the `inlet` patch. The caption states the field,
its range, the time and the file it was read from. Units of `p` and
`wallShearStress` depend on the solver (kinematic for incompressible), and the
caption says so rather than guessing.

## Python Usage Pattern

### A separator cutaway

```python
from engineering_3d_illustration import (
    Internal,
    Nozzle,
    VesselSpec,
    build_vessel_scene,
    export_cadquery,
    render_scene,
)

spec = VesselSpec(
    tag="20-VA-001",
    inside_diameter_m=3.0,
    tan_tan_length_m=10.0,
    wall_thickness_m=0.045,
    liquid_level_m=1.5,
    interface_level_m=0.6,
    nozzles=(Nozzle("Inlet", "top", 0.08, 0.5), Nozzle("Gas out", "top", 0.92, 0.4)),
    internals=(Internal("Weir", "weir", 0.78, 0.03, 0.0, 1.3),),
)
scene = build_vessel_scene(spec)
print(scene.caption())

figure = render_scene(scene, "figures", views=("iso", "front"))
solids = export_cadquery(scene, "figures")
for outcome in (figure, solids):
    print(outcome.backend, outcome.status, outcome.message)
```

### NeqSim results on the geometry

```python
from engineering_3d_illustration import (
    build_pipeline_scene,
    build_vessel_scene,
    pipeline_from_neqsim_pipe,
    render_scene,
    vessel_from_neqsim_separator,
)

# `pipe` is a neqsim PipeBeggsAndBrills and `separator` a neqsim Separator, both run.
pipeline = pipeline_from_neqsim_pipe(pipe)
render_scene(build_pipeline_scene(pipeline, color_by="Pressure"), "figures")

vessel = vessel_from_neqsim_separator(separator)
render_scene(build_vessel_scene(vessel), "figures")
```

### A process area with valves and piping

```python
from engineering_3d_illustration import (
    Equipment,
    InlineValve,
    PipeRun,
    PlantSpec,
    build_plant_scene,
    render_scene,
    route,
)

separator = Equipment("20-VA-001", "horizontal_vessel", (6.0, 5.0, 0.0), (2.6, 8.0), 0.0, 0.82)
scrubber = Equipment("23-VG-001", "vertical_vessel", (15.0, 5.0, 0.0), (1.6, 5.0), 0.0, 0.64)
gas = PipeRun(
    "Gas to scrubber",
    route(separator.port("top", 0.9), scrubber.port("inlet", 0.55), "zxy"),
    outside_diameter_m=0.40,
    value=58.0,
    valves=(InlineValve("20-PV-001", 0.5, "control"),),
)
plant = PlantSpec(
    "Separation", (separator, scrubber), (gas,), value_name="Temperature", value_unit="C"
)
render_scene(build_plant_scene(plant, colormap_name="coolwarm"), "figures", colormap="coolwarm")
```

### OpenFOAM in both directions

```python
from engineering_3d_illustration import render_openfoam_case, vessel_fluid_volume_stl

outcome = render_openfoam_case(
    "cases/20-P-001", "figures", field="U", views=("slice", "streamlines")
)
print(outcome.caption)

vessel_fluid_volume_stl(spec, "cases/20-VA-001/constant/triSurface/vessel.stl")
```

### A presentation render

```python
from engineering_3d_illustration import recommend_backend, render_blender

print(recommend_backend("presentation_render").rationale)
image = render_blender(scene, "figures", samples=64, resolution=(1920, 1080))
print(image.status, image.command)
```

## Validation Checklist

- [ ] Every input value comes from the study - a NeqSim result, a datasheet, a stated assumption - and none is invented to make the picture look complete.
- [ ] Levels are heights above the lowest inside point, in metres, not fractions.
- [ ] `scene.caption()` is placed with the figure, including every "not to scale" note.
- [ ] `scene.facts` volumes agree with the study's inventory numbers.
- [ ] The field shown on a pipeline or pipe run has its unit and range in the caption.
- [ ] Utilisation values state what they are a utilisation of.
- [ ] A `RenderOutcome` that is not `completed` is reported with its `command`, not hidden.
- [ ] An OpenFOAM figure is drawn after the CFD quality gate has passed.
- [ ] Synthetic or public data only in anything shared outside the project.
- [ ] A qualified engineer reviews the figure against the calculation before it is issued.

## Common Mistakes

| Symptom | Cause | Fix |
| --- | --- | --- |
| Liquid level looks wrong | A level fraction was passed as metres | Multiply by the inside height, or use `vessel_from_neqsim_separator` |
| Pipeline is a flat line | True scale on a long, shallow profile | Leave `vertical_exaggeration=None` and keep the note in the caption |
| Caption says "Not to scale" for a vessel | `wall_thickness_m` was not given | Supply the thickness |
| Temperature missing from a NeqSim pipe | The pipe ran adiabatic and recorded the inlet only | Enable heat transfer in NeqSim, or colour by pressure |
| CAD export has no colours for a field | CAD solids carry no field values | Use the PyVista figure for the result |
| Blender image has no labels | Blender draws the solids only | Pair it with the PyVista figure and its caption |
| OpenFOAM render reports `not_executed` | No `VTK/` folder and no solved time folder | Run the case, then `foamToVTK -latestTime` |
| Pipes cut through equipment | Routes are drawn as supplied | Route through a rack elevation with `route` in two steps |

## Limitations

- Equipment, valves and supports are envelope shapes. Nozzles are stubs at
  schematic positions and are not cut into the shell.
- Liquid is drawn level and still. With a weir, only the inlet side is filled.
- A process area is drawn as supplied; there is no clash, access or stress check.
- A pipeline built from a NeqSim pipe lies on a straight heading - the process
  model has no plan route.
- The Blender image has no labels or legend, and a CPU Cycles render takes from
  tens of seconds to minutes.
- OpenSCAD cut planes are staggered by a fraction of a millimetre per part to
  keep its preview clean; the file says so.
- `vessel_fluid_volume_stl` writes a closed wall with no nozzle openings; inlet
  and outlet patches are defined in the mesher.
- The OpenFOAM reader was checked against a `foamToVTK` export and native time
  folders of one OpenFOAM release; other releases lay out `VTK/` differently and
  fall back to the native reader.
- A figure is not evidence. Human review by a qualified engineer is required
  before a figure is used to support a decision.

## Related NeqSim Functionality

This skill renders data; it runs no thermodynamic or process calculation. The
numbers it shows come from NeqSim:

- `neqsim.process.equipment.separator.Separator` - `getInternalDiameter()`,
  `getSeparatorLength()`, `getOrientation()` and `getLiquidLevel()` (a fraction
  of the maximum liquid height) are read by `vessel_from_neqsim_separator`.
- `neqsim.process.equipment.pipeline.PipeBeggsAndBrills` - `getLengthProfile()`,
  `getElevationProfile()`, `getPressureProfile()` (bara),
  `getTemperatureProfile()` (K) and `getLiquidHoldupProfile()` are read by
  `pipeline_from_neqsim_pipe`.
- `neqsim.process.equipment.pipeline.TwoFluidPipe` exposes the same kind of
  profiles (`getPressureProfile()`, `getTemperatureProfile()`,
  `getLiquidHoldupProfile()`, `getElevationProfile()`) and can be passed to
  `PipelineSpec` as `FieldSeries`.
- Stream temperatures and pressures for pipe runs, and equipment utilisation,
  are taken from the study's `neqsim.process.processmodel.ProcessSystem` results
  and supplied as plain numbers.
- NeqSim is reached from Python with `from neqsim import jneqsim`.
- CFD figures are drawn from cases written by `neqsim-cfd-coupling`; solid
  temperature fields are rendered by `neqsim-fem-coupling`.

Candidate NeqSim gap: the process model holds no nozzle positions, plot-plan
coordinates or pipe routes, so layouts and routes are supplied by the user.

## References

- NeqSim repository: https://github.com/equinor/neqsim
- NeqSim Skills Guide: https://github.com/equinor/neqsim/blob/master/docs/integration/skills_guide.md
- PyVista: https://docs.pyvista.org
- CadQuery: https://cadquery.readthedocs.io
- OpenSCAD: https://openscad.org/documentation.html
- Blender Python API: https://docs.blender.org/api/current/
- OpenFOAM: https://www.openfoam.com
