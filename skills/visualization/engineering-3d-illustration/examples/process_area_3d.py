"""A separation and recompression area in 3D: equipment, valves and routed piping.

Synthetic public layout. Pipes are coloured by the stream temperature and
equipment by its utilisation - the two numbers a debottlenecking or tie-in
study usually wants on one picture. Run with ``--blender`` for a Cycles render.
"""

from _common import draw_everywhere

from engineering_3d_illustration import (
    Deck,
    Equipment,
    InlineValve,
    PipeRun,
    PlantSpec,
    build_plant_scene,
)


def main() -> None:
    separator = Equipment("20-VA-001", "horizontal_vessel", (6.0, 5.0, 0.0), (2.6, 8.0), 0.0, 0.82)
    scrubber = Equipment("23-VG-001", "vertical_vessel", (15.0, 5.0, 0.0), (1.6, 5.0), 0.0, 0.64)
    compressor = Equipment("23-KA-001", "compressor", (22.0, 5.0, 0.0), (5.0,), 0.0, 0.93)
    cooler = Equipment("23-HA-001", "heat_exchanger", (20.0, 13.0, 0.0), (1.0, 6.0), 180.0, 0.71)
    pump = Equipment("21-PA-001", "pump", (6.0, 13.0, 0.0), (2.4,), 0.0, 0.45)
    rack = 4.5  # pipe-rack elevation, m

    gas_out = separator.port("top", 0.9)
    scrubber_in = scrubber.port("inlet", 0.55)
    scrubber_top = scrubber.port("top")
    suction = compressor.port("inlet")
    discharge = compressor.port("top", 0.2)
    cooler_in, cooler_out = cooler.port("inlet"), cooler.port("outlet")
    oil_out = separator.port("bottom", 0.5)
    pump_in, pump_out = pump.port("inlet"), pump.port("top", 0.1)

    pipes = (
        PipeRun(
            "Gas to scrubber",
            (
                gas_out,
                (gas_out[0], 5.0, 5.4),
                (scrubber_in[0] - 0.8, 5.0, 5.4),
                (scrubber_in[0] - 0.8, 5.0, scrubber_in[2]),
                scrubber_in,
            ),
            0.40,
            value=58.0,
            valves=(InlineValve("20-PV-001", 0.45, "control"),),
        ),
        PipeRun(
            "Scrubber gas",
            (
                scrubber_top,
                (15.0, 5.0, 6.2),
                (suction[0] - 1.0, 5.0, 6.2),
                (suction[0] - 1.0, 5.0, suction[2]),
                suction,
            ),
            0.35,
            value=57.0,
        ),
        PipeRun(
            "Compressor discharge",
            (
                discharge,
                (discharge[0], 5.0, rack),
                (cooler_in[0] + 1.5, 5.0, rack),
                (cooler_in[0] + 1.5, 13.0, rack),
                (cooler_in[0] + 1.5, 13.0, cooler_in[2]),
                cooler_in,
            ),
            0.30,
            value=142.0,
        ),
        PipeRun(
            "Cooled gas export",
            (
                cooler_out,
                (cooler_out[0] - 1.5, 13.0, cooler_out[2]),
                (cooler_out[0] - 1.5, 13.0, rack),
                (cooler_out[0] - 1.5, 18.0, rack),
            ),
            0.30,
            value=35.0,
            valves=(InlineValve("23-HV-002", 0.75, "manual"),),
        ),
        PipeRun(
            "Oil to pump",
            (
                oil_out,
                (oil_out[0], 5.0, 0.35),
                (oil_out[0], 9.0, 0.35),
                (pump_in[0] - 1.2, 9.0, 0.35),
                (pump_in[0] - 1.2, 13.0, 0.35),
                (pump_in[0] - 1.2, 13.0, pump_in[2]),
                pump_in,
            ),
            0.25,
            value=58.0,
            valves=(InlineValve("20-LV-001", 0.27, "control"),),
        ),
        PipeRun(
            "Oil export",
            (pump_out, (pump_out[0], 13.0, rack), (pump_out[0], 18.0, rack)),
            0.20,
            value=59.0,
            valves=(InlineValve("21-NRV-001", 0.75, "check"),),
        ),
    )
    plant = PlantSpec(
        "Separation and recompression",
        equipment=(separator, scrubber, compressor, cooler, pump),
        pipes=pipes,
        decks=(Deck("Deck", 0.0, 28.0, 0.0, 19.0),),
        value_name="Temperature",
        value_unit="C",
    )
    scene = build_plant_scene(plant, colormap_name="coolwarm")
    draw_everywhere(scene, views=("iso", "top"), colormap="coolwarm")


if __name__ == "__main__":
    main()
