"""Gassco Urgent Market Messages (UMM) for NCS gas-export availability screening.

Gassco publishes planned and unplanned unavailability in the Norwegian upstream
gas transport system (fields, processing plants and exit terminals) on
https://umm.gassco.no, as event tables and as an Atom web feed of REMIT Urgent
Market Messages (ACER REMIT Manual of Procedures, Annex VII). Gassco documents
no public machine API and the site opens behind its terms of use, so this
module does **not** fetch anything. It parses events you have exported or
saved yourself:

* table rows (CSV or dicts) with the 13 columns Gassco publishes for entry,
  exit and other events, see :data:`UMM_TABLE_COLUMNS`;
* a saved Atom/XML UMM feed, parsed tolerantly by element local-name.

It then filters events by asset and time window and computes the worst
concurrent capacity reduction for an asset. Gassco states its information is
not exhaustive and must not be the sole basis for decisions; results here are
screening context for export availability, not a nomination or capacity
booking basis.
"""

from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GASSCO_UMM_URL = "https://umm.gassco.no/"
GASSCO_UMM_PRINCIPLES_URL = (
    "https://umm.gassco.no/resources/Principles%20for%20publication%20on%20umm.pdf"
)
GASSCO_ATTRIBUTION = (
    "Source: Gassco AS, Urgent Market Messages (umm.gassco.no). Gassco states the "
    "information is not exhaustive and should not be the sole basis for decisions."
)

#: Columns of Gassco's published entry/exit/other event tables, in order.
UMM_TABLE_COLUMNS: tuple[str, ...] = (
    "Event ID",
    "Asset affected",
    "Type of Unavailability",
    "Revision",
    "Time of Publication",
    "Event Start",
    "Event stop",
    "Technical capacity",
    "Available capacity",
    "Unavailable capacity",
    "Type of event",
    "Reason for the unavailability",
    "Remarks",
)

#: Gassco publishes entry/exit outages that may affect daily capacity above this.
PUBLICATION_THRESHOLD_MSM3_D = 5.0
#: Stated uncertainty on planned maintenance ("uncertain capacity").
PLANNED_UNCERTAINTY_MSM3_D = 5.0
#: Stated uncertainty on unplanned events lasting more than one day.
UNPLANNED_UNCERTAINTY_MSM3_D = 2.0

#: Points with real-time daily aggregated nominations (5-minute refresh).
REALTIME_FLOW_POINTS: tuple[str, ...] = (
    "Dornum",
    "Aggregated Europipe Metering Station",
    "Nybro",
    "Dunkerque",
    "Zeebrugge",
    "Easington",
    "St Fergus/Vesterled",
    "Aggregated entry SEGAL system (Gjøa Gas Pipe, Knarr Gas Pipeline, Tampen Link)",
    "Aggregated other exit points (field injection and Norwegian exit points)",
    "Sum exit nominations NCS",
)

# Header / element aliases -> canonical key. Matching ignores case and
# non-alphanumeric characters, so "Event Start", "eventStart" and
# "event_start" are the same key.
_ALIASES: dict[str, tuple[str, ...]] = {
    "event_id": ("eventid", "messageid", "ummid", "id"),
    "asset": (
        "assetaffected",
        "affectedasset",
        "affectedassetname",
        "assetname",
        "asset",
        "balancingzone",
    ),
    "unavailability_type": ("typeofunavailability", "unavailabilitytype"),
    "revision": ("revision", "version", "versionnumber"),
    "published": ("timeofpublication", "publicationdatetime", "published", "updated"),
    "start": ("eventstart", "start", "startdate"),
    "stop": ("eventstop", "eventend", "stop", "end", "enddate"),
    "technical_capacity": ("technicalcapacity",),
    "available_capacity": ("availablecapacity",),
    "unavailable_capacity": ("unavailablecapacity",),
    "event_type": ("typeofevent", "typeofeventplannedorunplanned", "eventtype"),
    "reason": ("reasonfortheunavailability", "unavailabilityreason", "reason"),
    "remarks": ("remarks", "remark", "comments"),
    "unit": ("unit", "unitmeasure", "capacityunit"),
    "event_status": ("eventstatus", "status"),
}

# Unit string (normalised) -> factor to MSm3/d. Energy units need a gross
# calorific value and are deliberately not converted.
_UNIT_TO_MSM3_D: dict[str, float] = {
    "msm3d": 1.0,
    "msm3": 1.0,
    "mscmd": 1.0,
    "mcmd": 1.0,
    "millsm3d": 1.0,
    "mmscmd": 1.0,
    "sm3d": 1.0e-6,
    "ksm3d": 1.0e-3,
}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


@dataclass(frozen=True)
class UmmEvent:
    """One Gassco UMM event (one revision).

    Capacities are as published, in ``unit``; ``*_msm3_d`` properties convert
    volumetric units to MSm3/d and return ``None`` for energy units. Datetimes
    are timezone-aware; naive inputs are interpreted in ``naive_tz`` at parse
    time (default UTC).
    """

    event_id: str
    asset: str
    unavailability_type: str
    revision: int | None
    published: datetime | None
    start: datetime | None
    stop: datetime | None
    technical_capacity: float | None
    available_capacity: float | None
    unavailable_capacity: float | None
    event_type: str
    reason: str
    remarks: str
    unit: str = "MSm3/d"
    event_status: str = ""
    source: str = "table"

    @property
    def is_planned(self) -> bool:
        text = f"{self.event_type} {self.unavailability_type}".lower()
        return "planned" in text and "unplanned" not in text

    @property
    def is_unplanned(self) -> bool:
        return "unplanned" in f"{self.event_type} {self.unavailability_type}".lower()

    @property
    def duration_hours(self) -> float | None:
        if self.start is None or self.stop is None:
            return None
        return (self.stop - self.start).total_seconds() / 3600.0

    @property
    def unit_factor(self) -> float | None:
        return _UNIT_TO_MSM3_D.get(_norm(self.unit)) if self.unit else 1.0

    def _conv(self, value: float | None) -> float | None:
        factor = self.unit_factor
        if value is None or factor is None:
            return None
        return value * factor

    @property
    def unavailable_msm3_d(self) -> float | None:
        return self._conv(self.unavailable_capacity)

    @property
    def available_msm3_d(self) -> float | None:
        return self._conv(self.available_capacity)

    @property
    def technical_msm3_d(self) -> float | None:
        return self._conv(self.technical_capacity)

    @property
    def uncertainty_msm3_d(self) -> float | None:
        """Gassco's stated uncertainty band for this kind of event, if any."""
        if self.is_planned:
            return PLANNED_UNCERTAINTY_MSM3_D
        hours = self.duration_hours
        if self.is_unplanned and hours is not None and hours > 24.0:
            return UNPLANNED_UNCERTAINTY_MSM3_D
        return None

    def overlaps(self, start: datetime, stop: datetime) -> bool:
        ev_start = self.start or datetime.min.replace(tzinfo=timezone.utc)
        ev_stop = self.stop or datetime.max.replace(tzinfo=timezone.utc)
        return ev_start < stop and ev_stop > start


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

_DATE_FORMATS = (
    "%d.%m.%Y %H:%M",
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y %H:%M",
)


def parse_datetime(value: Any, *, naive_tz: timezone = timezone.utc) -> datetime | None:
    """Parse ISO 8601 or common Gassco/European date strings to aware datetimes."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text or text.lower() in {"n/a", "na", "-", "unknown", "tbd"}:
            return None
        dt = None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            for fmt in _DATE_FORMATS:
                try:
                    dt = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
        if dt is None:
            raise ValueError(f"Unrecognised date/time: {value!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=naive_tz)
    return dt.astimezone(timezone.utc)


def parse_number(value: Any) -> float | None:
    """Parse a capacity number; tolerates units, spaces and decimal commas."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", " ")
    match = re.search(r"-?\d[\d ]*(?:[.,]\d+)?", text)
    if not match:
        return None
    number = match.group(0).replace(" ", "").replace(",", ".")
    return float(number)


def _unit_from_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        m = re.search(r"(m?sm3/d|mcm/d|mscm/d|kwh/d|gwh/d|mwh/d|sm3/d)", str(value), re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _canonical(record: Mapping[str, Any]) -> dict[str, Any]:
    """Map raw keys to canonical keys; aliases earlier in the list win."""
    normalised: dict[str, Any] = {}
    for raw_key, value in record.items():
        if raw_key is None:
            continue
        nk = _norm(str(raw_key))
        if nk not in normalised and value not in (None, ""):
            normalised[nk] = value
    out: dict[str, Any] = {}
    for key, aliases in _ALIASES.items():
        for alias in aliases:
            if alias in normalised:
                out[key] = normalised[alias]
                break
    return out


def _split_message_id(event_id: str, revision: int | None) -> tuple[str, int | None]:
    """REMIT Message ID is ``<thread id>_<version>``; split if revision missing."""
    if revision is None and "_" in event_id:
        thread, _, version = event_id.rpartition("_")
        if version.isdigit() and thread:
            return thread, int(version)
    return event_id, revision


def event_from_record(
    record: Mapping[str, Any],
    *,
    default_unit: str = "MSm3/d",
    naive_tz: timezone = timezone.utc,
    source: str = "table",
) -> UmmEvent:
    """Build a :class:`UmmEvent` from one row/dict using tolerant header matching."""
    rec = _canonical(record)
    if not rec.get("asset"):
        raise ValueError(f"UMM record has no affected asset: {dict(record)!r}")
    revision_raw = parse_number(rec.get("revision"))
    revision = None if revision_raw is None else int(revision_raw)
    event_id, revision = _split_message_id(str(rec.get("event_id") or "").strip(), revision)
    unit = (
        str(rec.get("unit")).strip()
        if rec.get("unit")
        else _unit_from_text(
            rec.get("technical_capacity"),
            rec.get("available_capacity"),
            rec.get("unavailable_capacity"),
        )
        or default_unit
    )
    return UmmEvent(
        event_id=event_id,
        asset=str(rec["asset"]).strip(),
        unavailability_type=str(rec.get("unavailability_type") or "").strip(),
        revision=revision,
        published=parse_datetime(rec.get("published"), naive_tz=naive_tz),
        start=parse_datetime(rec.get("start"), naive_tz=naive_tz),
        stop=parse_datetime(rec.get("stop"), naive_tz=naive_tz),
        technical_capacity=parse_number(rec.get("technical_capacity")),
        available_capacity=parse_number(rec.get("available_capacity")),
        unavailable_capacity=parse_number(rec.get("unavailable_capacity")),
        event_type=str(rec.get("event_type") or "").strip(),
        reason=str(rec.get("reason") or "").strip(),
        remarks=str(rec.get("remarks") or "").strip(),
        unit=unit,
        event_status=str(rec.get("event_status") or "").strip(),
        source=source,
    )


def parse_umm_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    default_unit: str = "MSm3/d",
    naive_tz: timezone = timezone.utc,
) -> list[UmmEvent]:
    """Parse table rows (dicts keyed by Gassco's column headers)."""
    events = []
    for row in rows:
        if not any(str(v).strip() for v in row.values() if v is not None):
            continue
        events.append(event_from_record(row, default_unit=default_unit, naive_tz=naive_tz))
    return events


def parse_umm_csv(
    source: str | Path,
    *,
    default_unit: str = "MSm3/d",
    naive_tz: timezone = timezone.utc,
) -> list[UmmEvent]:
    """Parse a CSV export/copy of a Gassco event table (path or CSV text).

    The delimiter (comma, semicolon or tab) is sniffed.
    """
    if isinstance(source, Path) or (
        isinstance(source, str) and "\n" not in source and Path(source).exists()
    ):
        text = Path(source).read_text(encoding="utf-8-sig")
    else:
        text = str(source)
    try:
        dialect = csv.Sniffer().sniff(text.splitlines()[0], delimiters=",;\t")
    except (csv.Error, IndexError):
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    return parse_umm_rows(reader, default_unit=default_unit, naive_tz=naive_tz)


def parse_umm_atom(
    xml_text: str,
    *,
    default_unit: str = "MSm3/d",
    naive_tz: timezone = timezone.utc,
) -> list[UmmEvent]:
    """Parse a saved Atom/XML UMM feed.

    Each Atom ``entry`` (or, without entries, each element that carries an
    ``unavailableCapacity``-like child) becomes one event. Fields are matched
    by element local-name anywhere inside the entry, so REMIT-style nested XML
    and flat Gassco XML both work. If an entry only has text content of the
    form ``Label: value`` per line, those lines are used.
    """
    root = ET.fromstring(xml_text)
    entries = [el for el in root.iter() if _local(el.tag) == "entry"]
    if not entries:
        entries = [
            el
            for el in root.iter()
            if any(_norm(_local(c.tag)) == "unavailablecapacity" for c in el)
        ]
    events: list[UmmEvent] = []
    for entry in entries:
        record: dict[str, Any] = {}
        for el in entry.iter():
            if el is entry:
                continue
            name = _local(el.tag)
            text = (el.text or "").strip()
            if name == "link" and "href" in el.attrib:
                continue
            if text and name not in record:
                record[name] = text
            for attr in ("unit", "unitMeasure"):
                if attr in el.attrib and "unit" not in record:
                    record["unit"] = el.attrib[attr]
        canonical = _canonical(record)
        if not canonical.get("asset") or "unavailable_capacity" not in canonical:
            body = record.get("content") or record.get("summary") or ""
            for line in str(body).splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    record.setdefault(k.strip(), v.strip())
        # Atom <title>/<id> are fallbacks only.
        if "asset" not in _canonical(record) and record.get("title"):
            record["assetAffected"] = record["title"]
        try:
            events.append(
                event_from_record(
                    record, default_unit=default_unit, naive_tz=naive_tz, source="atom"
                )
            )
        except ValueError:
            continue
    return events


# --------------------------------------------------------------------------- #
# Analysis
# --------------------------------------------------------------------------- #


def latest_revisions(events: Iterable[UmmEvent]) -> list[UmmEvent]:
    """Keep only the latest revision of each event id (by revision, then publication)."""
    best: dict[str, UmmEvent] = {}
    anonymous: list[UmmEvent] = []
    for ev in events:
        if not ev.event_id:
            anonymous.append(ev)
            continue
        cur = best.get(ev.event_id)
        if cur is None or _rev_key(ev) >= _rev_key(cur):
            best[ev.event_id] = ev
    return sorted(
        [*best.values(), *anonymous],
        key=lambda e: (e.start or datetime.min.replace(tzinfo=timezone.utc), e.asset),
    )


def _rev_key(ev: UmmEvent) -> tuple[int, datetime]:
    return (
        ev.revision if ev.revision is not None else -1,
        ev.published or datetime.min.replace(tzinfo=timezone.utc),
    )


def filter_events(
    events: Iterable[UmmEvent],
    *,
    asset: str | Sequence[str] | None = None,
    start: datetime | None = None,
    stop: datetime | None = None,
    include_dismissed: bool = False,
) -> list[UmmEvent]:
    """Filter by case-insensitive asset substring(s) and overlap with a window."""
    keys = [asset] if isinstance(asset, str) else list(asset or [])
    keys_l = [k.lower() for k in keys]
    lo = start or datetime.min.replace(tzinfo=timezone.utc)
    hi = stop or datetime.max.replace(tzinfo=timezone.utc)
    out = []
    for ev in events:
        if keys_l and not any(k in ev.asset.lower() for k in keys_l):
            continue
        if not include_dismissed and ev.event_status.lower() in {"dismissed", "cancelled"}:
            continue
        if ev.overlaps(lo, hi):
            out.append(ev)
    return out


@dataclass(frozen=True)
class CapacityImpact:
    """Worst concurrent capacity reduction for an asset within a window.

    ``min_published_available_msm3_d`` is the lowest "Available capacity" on any
    single event row; ``available_at_peak_msm3_d`` is technical capacity minus
    the peak concurrent unavailability (only when one asset matched).
    """

    asset: str
    window_start: datetime
    window_stop: datetime
    events: tuple[UmmEvent, ...]
    peak_unavailable_msm3_d: float
    peak_time: datetime | None
    technical_capacity_msm3_d: float | None
    min_published_available_msm3_d: float | None
    available_at_peak_msm3_d: float | None
    planned_count: int
    unplanned_count: int
    uncertainty_msm3_d: float
    unconverted_events: tuple[str, ...]
    caveats: tuple[str, ...]


def capacity_impact(
    events: Iterable[UmmEvent],
    *,
    asset: str,
    start: datetime,
    stop: datetime,
) -> CapacityImpact:
    """Sweep event boundaries to find the worst concurrent unavailability.

    Uses the latest revision of each event, sums unavailable capacity of events
    active at the same time for assets matching ``asset``, and reports the
    peak. The uncertainty is the largest band Gassco states for any
    contributing event. Events in energy units are listed in
    ``unconverted_events`` and left out of the sums.
    """
    if stop <= start:
        raise ValueError("stop must be after start")
    selected = filter_events(latest_revisions(events), asset=asset, start=start, stop=stop)
    convertible = [e for e in selected if e.unavailable_msm3_d is not None]
    unconverted = tuple(e.event_id or e.asset for e in selected if e.unavailable_msm3_d is None)

    times = {start}
    for ev in convertible:
        for t in (ev.start, ev.stop):
            if t is not None and start <= t < stop:
                times.add(t)
    peak, peak_time = 0.0, None
    for t in sorted(times):
        active = [
            e
            for e in convertible
            if (e.start is None or e.start <= t) and (e.stop is None or e.stop > t)
        ]
        total = sum(e.unavailable_msm3_d or 0.0 for e in active)
        if total > peak:
            peak, peak_time = total, t

    technical = [e.technical_msm3_d for e in selected if e.technical_msm3_d is not None]
    available = [e.available_msm3_d for e in selected if e.available_msm3_d is not None]
    bands = [e.uncertainty_msm3_d for e in convertible if e.uncertainty_msm3_d is not None]
    assets = {e.asset for e in selected}
    caveats = [
        (
            "Events below Gassco's publication threshold "
            f"({PUBLICATION_THRESHOLD_MSM3_D:g} MSm3/d) are not published."
        ),
        (
            "Summing concurrent events can overstate the impact: Gassco's aggregated "
            "entry figure nets out dependencies such as parallel field and plant maintenance."
        ),
    ]
    if len(assets) > 1:
        caveats.append(
            f"Asset filter {asset!r} matched several assets ({', '.join(sorted(assets))}); "
            "the peak sums across them."
        )
    if unconverted:
        caveats.append("Some events are in energy units and were not converted to MSm3/d.")
    tech = max(technical) if technical else None
    at_peak = None
    if tech is not None and len(assets) == 1:
        at_peak = round(max(tech - peak, 0.0), 3)
    return CapacityImpact(
        asset=asset,
        window_start=start,
        window_stop=stop,
        events=tuple(selected),
        peak_unavailable_msm3_d=round(peak, 3),
        peak_time=peak_time,
        technical_capacity_msm3_d=tech,
        min_published_available_msm3_d=min(available) if available else None,
        available_at_peak_msm3_d=at_peak,
        planned_count=sum(1 for e in selected if e.is_planned),
        unplanned_count=sum(1 for e in selected if e.is_unplanned),
        uncertainty_msm3_d=max(bands) if bands else 0.0,
        unconverted_events=unconverted,
        caveats=tuple(caveats),
    )


def events_to_rows(events: Iterable[UmmEvent]) -> list[dict[str, Any]]:
    """Render events back to Gassco's column layout (ISO datetimes)."""
    rows = []
    for e in events:
        rows.append(
            {
                "Event ID": e.event_id,
                "Asset affected": e.asset,
                "Type of Unavailability": e.unavailability_type,
                "Revision": e.revision,
                "Time of Publication": e.published.isoformat() if e.published else None,
                "Event Start": e.start.isoformat() if e.start else None,
                "Event stop": e.stop.isoformat() if e.stop else None,
                "Technical capacity": e.technical_capacity,
                "Available capacity": e.available_capacity,
                "Unavailable capacity": e.unavailable_capacity,
                "Type of event": e.event_type,
                "Reason for the unavailability": e.reason,
                "Remarks": e.remarks,
                "Unit": e.unit,
            }
        )
    return rows
