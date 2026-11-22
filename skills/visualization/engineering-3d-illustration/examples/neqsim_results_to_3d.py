"""Run a separator and a flowline in NeqSim, then draw what was calculated.

Needs the optional ``neqsim`` package (``pip install neqsim``) and a Java
runtime. Without it the script says so and exits - the other examples show the
same drawings from plain numbers.
"""

from _common import draw_everywhere

from engineering_3d_illustration import (
    Nozzle,
    build_pipeline_scene,
    build_vessel_scene,
    pipeline_from_neqsim_pipe,
    vessel_from_neqsim_separator,
)


def main() -> None:
    try:
        from neqsim import jneqsim
    except ImportError:
        print("neqsim is not installed - run: pip install neqsim")
        return

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

    feed = jneqsim.process.equipment.stream.Stream("feed", fluid)
    feed.setFlowRate(50000.0, "kg/hr")
    feed.run()

    pipe = jneqsim.process.equipment.pipeline.PipeBeggsAndBrills("Infield flowline", feed)
    pipe.setLength(8000.0)
    pipe.setElevation(120.0)
    pipe.setDiameter(0.25)
    pipe.setPipeWallRoughness(5.0e-5)
    pipe.setNumberOfIncrements(40)
    pipe.setRunIsothermal(False)
    pipe.setConstantSurfaceTemperature(4.0, "C")
    pipe.setHeatTransferCoefficient(15.0)
    pipe.run()

    separator = jneqsim.process.equipment.separator.Separator("20-VA-001", pipe.getOutletStream())
    separator.setInternalDiameter(2.6)
    separator.setSeparatorLength(8.0)
    separator.setLiquidLevel(0.45)
    separator.run()

    pipeline = pipeline_from_neqsim_pipe(pipe)
    print("fields read from NeqSim:", [(f.name, f.unit) for f in pipeline.fields])
    color_by = (
        "Temperature" if any(f.name == "Temperature" for f in pipeline.fields) else "Pressure"
    )
    draw_everywhere(
        build_pipeline_scene(pipeline, color_by=color_by), colormap="inferno", cad=False
    )

    vessel = vessel_from_neqsim_separator(
        separator,
        nozzles=(
            Nozzle("Inlet", "top", 0.08, 0.4),
            Nozzle("Gas out", "top", 0.92, 0.3),
            Nozzle("Liquid out", "bottom", 0.90, 0.25),
        ),
    )
    print(
        f"level from NeqSim: {vessel.liquid_level_m:.2f} m, inventory {vessel.liquid_volume_m3():.1f} m3"
    )
    draw_everywhere(build_vessel_scene(vessel), views=("iso",))


if __name__ == "__main__":
    main()
