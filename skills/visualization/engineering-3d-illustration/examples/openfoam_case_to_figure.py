"""Draw a solved OpenFOAM case, and write a vessel volume as STL for a mesher.

    python openfoam_case_to_figure.py <case_dir> [field]

The case is one that has been run - for example a case written and run by the
neqsim-cfd-coupling skill, whose last step is ``foamToVTK -latestTime``. With no
case given, only the geometry export is shown.
"""

from pathlib import Path
import sys

from _common import OUTPUT

from engineering_3d_illustration import (
    VesselSpec,
    find_openfoam_output,
    render_openfoam_case,
    vessel_fluid_volume_stl,
)


def main() -> None:
    vessel = VesselSpec("20-VA-001", inside_diameter_m=3.0, tan_tan_length_m=10.0)
    stl = vessel_fluid_volume_stl(vessel, OUTPUT / "20-va-001_fluid_volume.stl")
    print(f"wetted volume of {vessel.tag} ({vessel.total_volume_m3:.1f} m3) written to {stl}")

    arguments = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not arguments:
        print("no case directory given - pass a solved OpenFOAM case to draw its fields")
        return
    case = Path(arguments[0])
    field = arguments[1] if len(arguments) > 1 else "U"
    print(find_openfoam_output(case).message)
    outcome = render_openfoam_case(
        case, OUTPUT, field=field, views=("surface", "slice", "clip", "streamlines")
    )
    print(f"[{outcome.backend}] {outcome.status}: {outcome.message}")
    for path in outcome.files:
        print("   ", path)
    if outcome.caption:
        print(outcome.caption)


if __name__ == "__main__":
    main()
