"""A process module with each item coloured by its calculated utilisation.

Synthetic public layout. Utilisation is whatever the study calculated -
separator gas-load utilisation, compressor power against the driver, pump
flow against the curve - with 1.0 meaning at the limit.
"""

from _common import draw_everywhere

from engineering_3d_illustration import Deck, EquipmentBlock, LayoutSpec, build_layout_scene


def main() -> None:
    layout = LayoutSpec(
        "Process module M10",
        blocks=(
            EquipmentBlock(
                "20-VA-001", "horizontal_vessel", (8.0, 6.0, 0.0), (3.0, 10.0), 0.0, 0.82
            ),
            EquipmentBlock(
                "20-VA-002", "horizontal_vessel", (8.0, 12.0, 0.0), (2.6, 8.0), 0.0, 0.55
            ),
            EquipmentBlock("23-VG-001", "vertical_vessel", (20.0, 6.0, 0.0), (1.8, 5.5), 0.0, 1.07),
            EquipmentBlock("23-KA-001", "box", (22.0, 13.0, 0.0), (6.0, 3.5, 3.0), 0.0, 0.93),
            EquipmentBlock("23-HA-001", "box", (15.0, 16.5, 0.0), (4.0, 1.5, 1.5), 0.0, 0.40),
            EquipmentBlock("Local equipment room", "box", (3.0, 17.0, 0.0), (4.0, 4.0, 3.5)),
        ),
        decks=(Deck("Deck", 0.0, 28.0, 0.0, 20.0),),
    )
    draw_everywhere(build_layout_scene(layout), views=("iso", "top"))


if __name__ == "__main__":
    main()
