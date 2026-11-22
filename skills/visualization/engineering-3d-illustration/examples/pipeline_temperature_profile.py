"""A 30 km tie-back flowline coloured by a calculated temperature.

Synthetic public profile and temperatures. The figure states its vertical
exaggeration and the enlarged pipe diameter in the caption.
"""

from math import exp, sin

from _common import draw_everywhere

from engineering_3d_illustration import FieldSeries, PipelineSpec, build_pipeline_scene


def main() -> None:
    count = 121
    distance = [250.0 * i for i in range(count)]
    elevation = [
        -350.0
        + 40.0 * sin(i / 9.0)
        - 60.0 * exp(-(((i - 70) / 8.0) ** 2))
        + (12.5 * (i - 100) if i > 100 else 0.0)
        for i in range(count)
    ]
    temperature = tuple(4.0 + 61.0 * exp(-i / 25.0) for i in range(count))
    pressure = tuple(150.0 - 0.45 * i for i in range(count))
    spec = PipelineSpec.from_profile(
        "Tie-back flowline",
        distance,
        elevation,
        outside_diameter_m=0.3239,
        fields=[
            FieldSeries("Temperature", "C", temperature),
            FieldSeries("Pressure", "bara", pressure),
        ],
    )
    print("suggested vertical exaggeration:", spec.suggested_vertical_exaggeration())
    print("low points at KP:", [round(spec.chainage_m()[i] / 1000.0, 1) for i in spec.low_points()])
    scene = build_pipeline_scene(spec, color_by="Temperature")
    draw_everywhere(scene, views=("iso", "front"), colormap="inferno", cad=False)


if __name__ == "__main__":
    main()
