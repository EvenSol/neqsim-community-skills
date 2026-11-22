---
name: neqsim-engineering-3d-illustration
version: "0.1.0"
description: "Illustrate NeqSim designs and calculated results in three dimensions with open tools. One backend-neutral scene describes a vessel cutaway with liquid levels, internals and nozzles, a pipeline profile coloured by a calculated field, an equipment layout coloured by utilisation, or a process area with equipment, valves and routed piping carrying a stream value; the scene is then drawn off-screen with PyVista for report figures, exported as exact solids (STEP, STL, glTF) with a generated CadQuery script, written as an editable OpenSCAD file, or rendered with Blender Cycles for presentation. Draws a NeqSim ProcessSystem straight from its process graph and a DEXPI P&ID through NeqSim's DEXPI reader - placing equipment in flow order or at layout-study positions, routing the lines and marking new and modified items for a tie-in - reads geometry and results from a NeqSim Separator, PipeBeggsAndBrills and mechanical design data, draws the fields of a solved OpenFOAM case (surface, cut plane, clipped view, streamlines) for the CFD coupling skill, and writes a vessel's wetted volume as STL for a mesher. Every out-of-scale choice - vertical exaggeration, enlarged pipe diameter, assumed wall thickness - is recorded in the scene and printed in the caption, and labelled quantities are computed from the geometry that is drawn. USE WHEN: a study, report or presentation needs a 3D figure of equipment, piping, a pipeline or a layout with its calculated results; a NeqSim separator, pipeline or process model should be shown rather than tabulated; a DEXPI P&ID or a tie-in scope (existing, new, modified) should be shown in 3D; a STEP, STL or OpenSCAD model of screening geometry is needed; an OpenFOAM result needs a figure; or a rendered image is wanted for a front page."
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
  one 3D picture, or the tie-in scope shown as existing, new and modified items.
- A NeqSim `ProcessSystem` or a DEXPI P&ID should be drawn without typing the
  equipment and connections in again.
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
| `Equipment`, `PipeRun` | `status` | `existing`, `new` or `modified`, for a tie-in or modification figure |
| `plant_from_neqsim_process` | `process`, `value`, `positions`, `new_tags`, `modified_tags` | A NeqSim `ProcessSystem`; the stream value on the lines (`temperature`, `pressure`, `mass_flow`); optional positions; the tie-in scope by tag |
| `plant_from_dexpi` | `path`, `positions`, `sizes`, `new_tags`, `modified_tags` | A DEXPI P&ID XML file; positions and sizes by tag where known |
| `plant_from_topology` | `items`, `connections`, `positions` | `TopologyItem(tag, kind, size_m, utilisation, status)` and `TopologyConnection(name, source, target, diameter_m, value, valves, status)` from any other source |
| `vessel_from_design_data` | `document`, `head_type` | NeqSim design-data JSON (schema 1.0); the head shape is stated by the caller |
| `plant_from_layout_study` | `study`, `alternative`, `new_tags`, `utilisation` | A `neqsim layout-study` dataset and one of its alternatives, drawn where it was placed with its route estimates |
| `positions_from_layout_study` | `study`, `alternative` | The same dataset, as positions for the model and P&ID builders |
| `render_openfoam_case` | `case_dir`, `field`, `views`, `time` | A solved case; a field such as `U`, `p`, `T`, `alpha.water`; views from `surface`, `slice`, `clip`, `streamlines` |

`utilisation` is whatever the study calculated, with 1.0 meaning at the limit.

## Outputs

| Output | Contents |
|---|---|
| `Scene` | Primitives, labels, `notes`, `true_scale`, `facts` and `caption()` |
| `VesselSpec.total_volume_m3`, `liquid_volume_m3(level)` | Closed-form volumes of the vessel and of the liquid below a level |
| `PipelineSpec.chainage_m()`, `low_points()`, `suggested_vertical_exaggeration()` | True length along the pipe, labelled low points, a round exaggeration factor |
| `ArrangedPlant` | The drawable `plant`, the `notes` on what was assumed, the tags with assumed positions, sizes and diameters, and `scene()` |
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

**From a model to a picture.** A process model and a P&ID say what is connected
to what, not where it stands. `plant_from_neqsim_process` walks the graph from
`ProcessSystem.buildGraph()`: vessels, columns, exchangers, pumps and compressors
become equipment, a valve is put on the line it sits in, and streams, mixers,
splitters and recycles are passed through. `plant_from_dexpi` does the same for a
P&ID, using NeqSim's `DexpiXmlReader` for the tagged items and their DEXPI
classes and `DexpiTopologyResolver` for the equipment, then following the piping
through valves, reducers and tees from nozzle to nozzle. Nominal diameters such
as `DN 80` become line diameters.

**Placement is automatic only where nothing better exists.** Items are placed in
flow order - one column per step, recycles ignored - and each line rises to a
rack, crosses and drops to its target. Positions from a layout study replace
this whenever they are given. Every automatic position, default size and assumed
diameter is counted in the caption, and such a figure is marked not to scale: it
is a schematic arrangement, not a plot plan.

**A studied layout.** `plant_from_layout_study` draws one alternative of the main repository's `neqsim layout-study`
exactly where the study placed it, deck by deck, and - when the study ran `--route` - with its route estimates as lines.
This is the figure for a new design: `neqsim layout-study --optimize --route` chooses and checks the arrangement against
the project's rules, and this skill shows it with results and scope on it. The route lines stay what the study says they
are: software estimates, not physical routes.

**Tie-in scope.** Marking tags as new or modified switches the colouring from
results to status: new in blue, modified in orange, existing in grey, with
utilisation and stream values kept as labels. A line is new when it serves a new
item or carries a new valve; a line to equipment that is only modified stays
existing. The same plant can be drawn both ways, so one figure shows what the
solution adds and the other what it does to the process.

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

### A NeqSim model or a DEXPI P&ID, with the tie-in scope

```python
from engineering_3d_illustration import (
    plant_from_dexpi, plant_from_neqsim_process, positions_from_layout_study, render_scene,
)

# `process` is a neqsim ProcessSystem that has been run.
arranged = plant_from_neqsim_process(
    process, value="temperature", new_tags=("23-KA-001", "23-HA-001")
)
print(arranged.notes)  # what was placed, sized and routed by assumption
render_scene(arranged.scene(color_by="status"), "figures/scope")
render_scene(arranged.scene(color_by="results", colormap_name="coolwarm"),
             "figures/results", colormap="coolwarm")

# A layout-study alternative as placed, with its route estimates (dataset/plant_layout.json):
# arranged = plant_from_layout_study(dataset["study"], dataset["alternatives"][0])

# The same from a P&ID file, at the positions of a layout study when there is one:
# positions = positions_from_layout_study(study, alternative)
pid = plant_from_dexpi("pid.xml", new_tags=("23-KA-001",))
render_scene(pid.scene(), "figures/pid", views=("iso", "top"))
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
- [ ] For a drawn model or P&ID, `ArrangedPlant.notes` has been read: assumed positions, sizes and diameters are acceptable for this figure, or have been supplied.
- [ ] Tags marked new or modified match the study's scope list.
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
| A drawn P&ID shows fewer valves than the drawing | Valves on drains, vents and off-page branches are not on an equipment-to-equipment line | Read the count in the caption; draw those lines by hand with `PipeRun` if they matter |
| Everything from a P&ID is the same size | A P&ID holds no equipment sizes | Pass `sizes` by tag, or draw from the process model |
| A model figure looks like a row of equipment | No positions were given, so flow order was used | Pass `positions`, for example from `positions_from_layout_study` |
| Pipes cut through equipment | Routes are drawn as supplied | Route through a rack elevation with `route` in two steps |

## Limitations

- Equipment, valves and supports are envelope shapes. Nozzles are stubs at
  schematic positions and are not cut into the shell.
- Liquid is drawn level and still. With a weir, only the inlet side is filled.
- A process area is drawn as supplied; there is no clash, access or stress check.
- An automatic arrangement is a schematic in flow order with rack routing. It is
  not a plot plan, and no clearance, access or escape-route rule is applied -
  that is the job of the layout study in the NeqSim main repository.
- From a DEXPI file, only lines between two equipment items are drawn, with the
  valves on them. Instruments, drains, vents and off-page branches are counted
  but not drawn. Orientation of a vessel is not in a P&ID.
- There is no connection to an operator's plant viewer or digital twin. The STEP
  and glTF exports are the hand-over; a company-specific connector belongs in an
  enterprise repository.
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
- `neqsim.process.processmodel.ProcessSystem#buildGraph()` and the
  `neqsim.process.processmodel.graph` classes (`ProcessGraph`, `ProcessNode`,
  `ProcessEdge`) give `plant_from_neqsim_process` its equipment, connections and
  streams; `getTemperature("C")`, `getPressure("bara")` and
  `getFlowRate("kg/hr")` on the edge's stream give the line value.
- `neqsim.process.equipment.capacity.CapacityConstrainedEquipment#getMaxUtilization()`
  gives the utilisation shown on equipment.
- `neqsim.process.processmodel.dexpi.DexpiXmlReader#readWithDiagnostics(File)`
  and `DexpiTopologyResolver#resolve(Document)` are what `plant_from_dexpi` reads
  a P&ID with; `DexpiXmlWriter#write(ProcessSystem, File)` writes one from a model.
- `neqsim.process.mechanicaldesign.MechanicalDesign#toDesignDataJson()` produces
  the design-data JSON read by `vessel_from_design_data`.
- The `neqsim layout-study` dataset (`devtools/layout_study.py`,
  `devtools/layout_model.py`) supplies positions through
  `positions_from_layout_study`, and a whole placed alternative with the
  `route_estimates` of `devtools/layout_routing.py` through
  `plant_from_layout_study`.
- NeqSim is reached from Python with `from neqsim import jneqsim`.
- CFD figures are drawn from cases written by `neqsim-cfd-coupling`; solid
  temperature fields are rendered by `neqsim-fem-coupling`.

Skills in the NeqSim main repository that this one works beside, not instead of:

- `neqsim-pid-process-operations` and `neqsim-dexpi-conformance-validation` -
  produce and validate the DEXPI P&ID that is drawn here.
- `neqsim-plant-layout-geometry`, `neqsim-plant-layout-study` and
  `neqsim-plant-layout-delivery` - place equipment against clearance, access and
  mass constraints and deliver plot drawings and CAD of the physical envelopes.
  Use their positions here; do not use the automatic arrangement as a layout.
- `neqsim-capacity-and-utilization-analysis` - calculates the utilisation shown.
- `neqsim-engineering-design-package` - produces the design data and datasheets.
- `neqsim-pfd-layout-review` - governs 2D flow diagrams, which this skill does
  not draw.

Candidate NeqSim gap: the process model holds no nozzle positions or pipe
routes, so routes are schematic unless supplied.

## References

- NeqSim repository: https://github.com/equinor/neqsim
- NeqSim Skills Guide: https://github.com/equinor/neqsim/blob/master/docs/integration/skills_guide.md
- PyVista: https://docs.pyvista.org
- CadQuery: https://cadquery.readthedocs.io
- OpenSCAD: https://openscad.org/documentation.html
- Blender Python API: https://docs.blender.org/api/current/
- OpenFOAM: https://www.openfoam.com
