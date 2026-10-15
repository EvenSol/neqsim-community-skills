"""Brazil offshore gas infrastructure, tariff status, market and host-capacity screening.

Packaged public data is a snapshot of 2026-10-14; unknowns stay explicit.
"""

from .data import (
    dataset_age_days,
    find,
    is_unknown,
    iter_entries,
    load_infrastructure,
    load_market,
    source_url,
    sources,
    unknown_entries,
)
from .helpers import (
    co2_removal_fraction,
    gas_export_upside,
    host_capacity_check,
    wellhead_netback,
)

__version__ = "0.1.0"

__all__ = [
    "co2_removal_fraction",
    "dataset_age_days",
    "find",
    "gas_export_upside",
    "host_capacity_check",
    "is_unknown",
    "iter_entries",
    "load_infrastructure",
    "load_market",
    "source_url",
    "sources",
    "unknown_entries",
    "wellhead_netback",
]
