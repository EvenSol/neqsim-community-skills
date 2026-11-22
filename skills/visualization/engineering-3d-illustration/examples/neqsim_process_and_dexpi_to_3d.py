"""Draw a NeqSim process model, and a DEXPI P&ID, in 3D - with the tie-in scope marked.

Part 1 builds and runs a small NeqSim ``ProcessSystem`` and draws it straight
from the model: equipment, lines, valves, stream temperatures and separator
sizes all come from NeqSim. A new booster compressor and cooler are marked as
the tie-in scope, and the same model is drawn twice - by results and by status.

Part 2 draws a DEXPI P&ID file through NeqSim's DEXPI reader:

    python neqsim_process_and_dexpi_to_3d.py [path/to/pid.xml]

Needs the optional ``neqsim`` package and a Java runtime.
"""

import sys

from _common import OUTPUT

from engineering_3d_illustration import (
    plant_from_dexpi,
    plant_from_neqsim_process,
    render_scene,
)


def build_process(jneqsim):
    fluid = jneqsim.thermo.system.SystemSrkEos(273.15 + 60.0, 60.0)
    for component, moles in (
        ("methane", 0.60),
        ("ethane", 0.05),
        ("propane", 0.04),
        ("n-heptane", 0.20),
        ("water", 0.11),
    ):
        fluid.addComponent(component, moles)
    fluid.setMixingRule("classic")
    fluid.setMultiPhaseCheck(True)

    equipment = jneqsim.process.equipment
    feed = equipment.stream.Stream("Well stream", fluid)
    feed.setFlowRate(50000.0, "kg/hr")
    choke = equipment.valve.ThrottlingValve("20-HV-001", feed)
    choke.setOutletPressure(40.0)
    separator = equipment.separator.Separator("20-VA-001", choke.getOutletStream())
    separator.setInternalDiameter(2.6)
    separator.setSeparatorLength(8.0)
    scrubber = equipment.separator.GasScrubber("23-VG-001", separator.getGasOutStream())
    compressor = equipment.compressor.Compressor("23-KA-001", scrubber.getGasOutStream())
    compressor.setOutletPressure(110.0)
    cooler = equipment.heatexchanger.Cooler("23-HA-001", compressor.getOutletStream())
    cooler.setOutTemperature(273.15 + 35.0)
    level_valve = equipment.valve.ThrottlingValve("20-LV-001", separator.getLiquidOutStream())
    level_valve.setOutletPressure(10.0)
    second_stage = equipment.separator.Separator("20-VA-002", level_valve.getOutletStream())
    second_stage.setInternalDiameter(2.2)
    second_stage.setSeparatorLength(6.0)
    pump = equipment.pump.Pump("21-PA-001", second_stage.getLiquidOutStream())
    pump.setOutletPressure(30.0)

    process = jneqsim.process.processmodel.ProcessSystem()
    for unit in (
        feed,
        choke,
        separator,
        scrubber,
        compressor,
        cooler,
        level_valve,
        second_stage,
        pump,
    ):
        process.add(unit)
    process.setName("Separation and recompression")
    process.run()
    return process


def report(outcome) -> None:
    print(f"[{outcome.backend}] {outcome.status}: {outcome.message}")
    print(outcome.caption)


def main() -> None:
    try:
        from neqsim import jneqsim
    except ImportError:
        print("neqsim is not installed - run: pip install neqsim")
        return

    process = build_process(jneqsim)
    arranged = plant_from_neqsim_process(
        process, value="temperature", new_tags=("23-KA-001", "23-HA-001")
    )
    for item in arranged.plant.equipment:
        print(f"  {item.tag:10s} {item.kind:18s} size {item.size_m} status {item.status}")
    for pipe in arranged.plant.pipes:
        print(f"  {pipe.name:28s} {pipe.value} C  valves {[v.tag for v in pipe.valves]}")

    results = arranged.scene(
        color_by="results", colormap_name="coolwarm", title="Process model - stream temperature"
    )
    report(render_scene(results, OUTPUT / "results", views=("iso",), colormap="coolwarm"))
    scope = arranged.scene(color_by="status", title="Process model - tie-in scope")
    report(render_scene(scope, OUTPUT / "scope", views=("iso",)))

    arguments = [a for a in sys.argv[1:] if not a.startswith("--")]
    if arguments:
        pid = plant_from_dexpi(arguments[0])
        report(render_scene(pid.scene(), OUTPUT, views=("iso", "top")))
    else:
        print("no DEXPI file given - pass a P&ID XML file to draw it")


if __name__ == "__main__":
    main()
