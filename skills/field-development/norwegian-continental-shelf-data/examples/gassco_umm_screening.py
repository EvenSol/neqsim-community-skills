"""Gas-export availability screening from Gassco UMM events (offline).

Gassco has no documented public API for umm.gassco.no, so save or copy the
event table (or the Atom feed) yourself and pass the file path:

    python examples/gassco_umm_screening.py my_umm_export.csv "Kollsnes"

Without arguments a small synthetic event set is used.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from norwegian_continental_shelf_data import (
    GASSCO_ATTRIBUTION,
    capacity_impact,
    parse_umm_atom,
    parse_umm_csv,
)

SYNTHETIC = """Event ID,Asset affected,Type of Unavailability,Revision,Time of Publication,Event Start,Event stop,Technical capacity,Available capacity,Unavailable capacity,Type of event,Reason for the unavailability,Remarks
DEMO-1,Example processing plant,Production unavailability,1,2026-05-01T08:00:00Z,2026-06-10T04:00:00Z,2026-06-14T04:00:00Z,100,70,30,Planned,Maintenance,synthetic
DEMO-2,Example processing plant,Production unavailability,1,2026-06-11T01:00:00Z,2026-06-11T00:00:00Z,2026-06-11T18:00:00Z,100,88,12,Unplanned,Compressor trip,synthetic
"""


def main(path: str | None = None, asset: str = "Example processing plant") -> None:
    if path is None:
        events = parse_umm_csv(SYNTHETIC)
    elif path.lower().endswith((".xml", ".atom")):
        events = parse_umm_atom(Path(path).read_text(encoding="utf-8"))
    else:
        events = parse_umm_csv(Path(path))

    impact = capacity_impact(
        events,
        asset=asset,
        start=datetime(2026, 6, 1, tzinfo=timezone.utc),
        stop=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    print(GASSCO_ATTRIBUTION)
    print(f"Asset filter: {impact.asset}  window {impact.window_start:%Y-%m-%d}"
          f" to {impact.window_stop:%Y-%m-%d}")
    print(f"Events: {len(impact.events)} "
          f"({impact.planned_count} planned, {impact.unplanned_count} unplanned)")
    print(f"Peak concurrent unavailable: {impact.peak_unavailable_msm3_d} MSm3/d "
          f"+/- {impact.uncertainty_msm3_d} at {impact.peak_time}")
    print(f"Technical capacity: {impact.technical_capacity_msm3_d} MSm3/d; "
          f"available at peak: {impact.available_at_peak_msm3_d} MSm3/d")
    for c in impact.caveats:
        print("NOTE:", c)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0] if a else None, a[1] if len(a) > 1 else "Example processing plant")
