"""Tie-in host context from the live Sodir DataService (network required).

Pulls a host field's monthly saleable production, computes GOR / water-cut
trends and the historic-peak ullage proxy, and lists nearby undeveloped
discoveries as tie-in candidates. Run from inside the skill folder:

    python examples/live_host_context.py GRANE 40

Needs outbound HTTPS to factmaps.sodir.no. Without it the script prints the
query URLs it would call and exits cleanly.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from norwegian_continental_shelf_data import (
    SodirApiError,
    SodirDataService,
    host_context,
)


def main(field_name: str = "GRANE", radius_km: float = 40.0) -> None:
    svc = SodirDataService()
    try:
        ctx = host_context(field_name, service=svc, radius_km=radius_km)
    except SodirApiError as exc:
        print(f"Sodir DataService not reachable ({exc}).")
        print("Query that would be sent first:")
        print(" ", svc.query_url("field", where=f"UPPER(fldName)='{field_name.upper()}'"))
        return

    print(ctx.attribution)
    print(f"Host: {ctx.field_name}  ({ctx.overview.get('fldHcType')}, "
          f"operator {ctx.overview.get('cmpLongName')})")
    print(f"Location: {ctx.host_latitude:.4f} N, {ctx.host_longitude:.4f} E")

    if ctx.trend:
        t = ctx.trend
        print(f"\nLast {t.window_months} months to {t.latest_month}:")
        print(f"  mean oil {t.recent_mean_oil_sm3_d:,.0f} Sm3/d, "
              f"gas {t.recent_mean_gas_sm3_d:,.0f} Sm3/d")
        print(f"  sales GOR {t.recent_mean_gor} Sm3/Sm3 (change {t.gor_change_fraction})")
        print(f"  water cut {t.recent_mean_water_cut} (change {t.water_cut_change})")

    if ctx.ullage:
        print("\nIndicative ullage (historic peak minus recent mean):")
        for s in ctx.ullage.streams:
            print(f"  {s.stream:6s} peak {s.historic_peak:>14,.0f} {s.unit} ({s.peak_month}) "
                  f"recent {s.recent_mean:>14,.0f}  ullage {s.indicative_ullage:>14,.0f}")
        print("  " + ctx.ullage.caveat)

    print(f"\nUndeveloped discoveries within {radius_km:g} km:")
    for c in ctx.candidates[:10]:
        oe = c.recoverable_oe_mill_sm3
        print(f"  {c.name:20s} {c.distance_km:6.1f} km  {c.discovery.hc_type:10s} "
              f"{'' if oe is None else f'{oe:.1f} mill Sm3 o.e.'}  [{c.discovery.status}]")
    for w in ctx.warnings:
        print("WARNING:", w)


if __name__ == "__main__":
    args = sys.argv[1:]
    main(args[0] if args else "GRANE", float(args[1]) if len(args) > 1 else 40.0)
