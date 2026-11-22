"""Cutaway of a three-phase separator with its levels, weir and nozzles.

Synthetic public data. Run with ``--blender`` to add a Cycles render.
"""

from _common import draw_everywhere

from engineering_3d_illustration import Internal, Nozzle, VesselSpec, build_vessel_scene


def main() -> None:
    spec = VesselSpec(
        tag="20-VA-001",
        inside_diameter_m=3.0,
        tan_tan_length_m=10.0,
        wall_thickness_m=0.045,
        liquid_level_m=1.5,
        interface_level_m=0.6,
        nozzles=(
            Nozzle("Inlet", "top", 0.08, 0.5),
            Nozzle("Gas out", "top", 0.92, 0.4),
            Nozzle("Water out", "bottom", 0.60, 0.25),
            Nozzle("Oil out", "bottom", 0.90, 0.3),
        ),
        internals=(Internal("Weir", "weir", 0.78, 0.03, 0.0, 1.3),),
    )
    print(f"total volume  {spec.total_volume_m3:8.2f} m3")
    print(f"liquid volume {spec.liquid_volume_m3():8.2f} m3 at {spec.liquid_level_m} m")
    print(f"water volume  {spec.liquid_volume_m3(spec.interface_level_m):8.2f} m3")
    draw_everywhere(build_vessel_scene(spec), views=("iso", "front"))


if __name__ == "__main__":
    main()
