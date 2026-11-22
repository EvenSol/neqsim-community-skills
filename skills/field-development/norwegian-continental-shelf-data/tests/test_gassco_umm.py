"""Tests for Gassco UMM parsing and capacity-impact screening (synthetic events)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from norwegian_continental_shelf_data import (
    UMM_TABLE_COLUMNS,
    capacity_impact,
    events_to_rows,
    filter_events,
    latest_revisions,
    parse_umm_atom,
    parse_umm_csv,
    parse_umm_rows,
)
from norwegian_continental_shelf_data.gassco_umm import parse_datetime, parse_number

UTC = timezone.utc

CSV_TEXT = """Event ID;Asset affected;Type of Unavailability;Revision;Time of Publication;Event Start;Event stop;Technical capacity;Available capacity;Unavailable capacity;Type of event;Reason for the unavailability;Remarks
EV1;Plant A;Production unavailability;1;01.06.2026 08:00;10.06.2026 06:00;12.06.2026 06:00;80;60;20;Planned;Maintenance;
EV1;Plant A;Production unavailability;2;05.06.2026 08:00;10.06.2026 06:00;13.06.2026 06:00;80;55;25;Planned;Maintenance;extended
EV2;Plant A;Production unavailability;1;11.06.2026 02:00;11.06.2026 00:00;11.06.2026 12:00;80;70;10;Unplanned;Trip;
EV3;Terminal B;Transport unavailability;1;01.06.2026 08:00;20.06.2026 06:00;21.06.2026 06:00;40;30;10;Planned;Maintenance;
"""


def test_table_columns_match_gassco_publication() -> None:
    assert len(UMM_TABLE_COLUMNS) == 13
    assert UMM_TABLE_COLUMNS[0] == "Event ID"
    assert UMM_TABLE_COLUMNS[-1] == "Remarks"


def test_parse_csv_semicolon_and_european_dates() -> None:
    events = parse_umm_csv(CSV_TEXT)
    assert len(events) == 4
    ev = events[1]
    assert ev.event_id == "EV1" and ev.revision == 2
    assert ev.start == datetime(2026, 6, 10, 6, tzinfo=UTC)
    assert ev.unavailable_msm3_d == 25.0
    assert ev.is_planned and not ev.is_unplanned
    assert ev.duration_hours == pytest.approx(72.0)
    assert ev.uncertainty_msm3_d == 5.0


def test_latest_revisions_keeps_highest_revision() -> None:
    latest = latest_revisions(parse_umm_csv(CSV_TEXT))
    ev1 = [e for e in latest if e.event_id == "EV1"]
    assert len(ev1) == 1 and ev1[0].revision == 2
    assert len(latest) == 3


def test_filter_events_by_asset_and_window() -> None:
    events = latest_revisions(parse_umm_csv(CSV_TEXT))
    got = filter_events(events, asset="plant a",
                        start=datetime(2026, 6, 11, tzinfo=UTC),
                        stop=datetime(2026, 6, 12, tzinfo=UTC))
    assert {e.event_id for e in got} == {"EV1", "EV2"}
    assert filter_events(events, asset=["terminal"])[0].event_id == "EV3"


def test_capacity_impact_sums_concurrent_events() -> None:
    impact = capacity_impact(parse_umm_csv(CSV_TEXT), asset="Plant A",
                             start=datetime(2026, 6, 1, tzinfo=UTC),
                             stop=datetime(2026, 6, 30, tzinfo=UTC))
    # EV1 rev2 (25) overlaps EV2 (10) on 11 June 00:00-12:00
    assert impact.peak_unavailable_msm3_d == pytest.approx(35.0)
    assert impact.peak_time == datetime(2026, 6, 11, 0, tzinfo=UTC)
    assert impact.technical_capacity_msm3_d == 80.0
    assert impact.min_published_available_msm3_d == 55.0
    assert impact.available_at_peak_msm3_d == pytest.approx(45.0)
    assert impact.planned_count == 1 and impact.unplanned_count == 1
    assert impact.uncertainty_msm3_d == 5.0
    assert any("aggregated entry" in c for c in impact.caveats)
    with pytest.raises(ValueError):
        capacity_impact([], asset="x", start=datetime(2026, 1, 2, tzinfo=UTC),
                        stop=datetime(2026, 1, 1, tzinfo=UTC))


def test_capacity_impact_no_events_is_zero() -> None:
    impact = capacity_impact(parse_umm_csv(CSV_TEXT), asset="Nowhere",
                             start=datetime(2026, 6, 1, tzinfo=UTC),
                             stop=datetime(2026, 7, 1, tzinfo=UTC))
    assert impact.peak_unavailable_msm3_d == 0.0
    assert impact.events == ()


def test_energy_units_are_not_converted() -> None:
    (ev,) = parse_umm_rows([{"Event ID": "E", "Asset affected": "Exit X",
                             "Unavailable capacity": "120 GWh/d",
                             "Event Start": "2026-06-01T06:00:00Z",
                             "Event stop": "2026-06-02T06:00:00Z"}])
    assert ev.unit == "GWh/d"
    assert ev.unavailable_msm3_d is None
    impact = capacity_impact([ev], asset="Exit", start=datetime(2026, 6, 1, tzinfo=UTC),
                             stop=datetime(2026, 6, 3, tzinfo=UTC))
    assert impact.unconverted_events == ("E",)
    assert impact.peak_unavailable_msm3_d == 0.0


def test_mcm_and_sm3_unit_conversion() -> None:
    (a, b) = parse_umm_rows([
        {"Asset affected": "A", "Unavailable capacity": "12", "unit": "mcm/d"},
        {"Asset affected": "B", "Unavailable capacity": "3 000 000", "unit": "Sm3/d"},
    ])
    assert a.unavailable_msm3_d == 12.0
    assert b.unavailable_msm3_d == pytest.approx(3.0)


def test_record_without_asset_raises() -> None:
    with pytest.raises(ValueError):
        parse_umm_rows([{"Event ID": "X", "Unavailable capacity": "5"}])


ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:u="urn:example:umm">
  <title>UMM</title>
  <entry>
    <id>urn:uuid:aaaa</id>
    <title>Plant A maintenance</title>
    <updated>2026-06-05T08:00:00Z</updated>
    <content type="application/xml">
      <u:umm>
        <u:messageId>THREAD9_3</u:messageId>
        <u:unavailabilityType>Planned</u:unavailabilityType>
        <u:eventStatus>Active</u:eventStatus>
        <u:publicationDateTime>2026-06-05T08:00:00+02:00</u:publicationDateTime>
        <u:eventStart>2026-06-10T06:00:00+02:00</u:eventStart>
        <u:eventStop>2026-06-12T06:00:00+02:00</u:eventStop>
        <u:affectedAsset><u:assetName>Plant A</u:assetName></u:affectedAsset>
        <u:technicalCapacity unit="mcm/d">80</u:technicalCapacity>
        <u:availableCapacity>62.5</u:availableCapacity>
        <u:unavailableCapacity>17.5</u:unavailableCapacity>
        <u:unavailabilityReason>Maintenance</u:unavailabilityReason>
      </u:umm>
    </content>
  </entry>
  <entry>
    <id>urn:uuid:bbbb</id>
    <title>Terminal B</title>
    <summary>Asset affected: Terminal B
Unavailable capacity: 8
Event Start: 2026-06-20T06:00:00Z
Event stop: 2026-06-21T06:00:00Z
Type of event: Unplanned</summary>
  </entry>
  <entry><id>urn:uuid:cccc</id><title>Ticker only</title></entry>
</feed>"""


def test_parse_atom_remit_style_and_text_summary() -> None:
    events = parse_umm_atom(ATOM)
    assert len(events) == 3  # third entry falls back to title as asset
    a = events[0]
    assert a.event_id == "THREAD9" and a.revision == 3  # messageId beats <id>
    assert a.asset == "Plant A"
    assert a.unit == "mcm/d"
    assert a.unavailable_msm3_d == 17.5
    assert a.start == datetime(2026, 6, 10, 4, tzinfo=UTC)
    assert a.is_planned and a.event_status == "Active"
    b = events[1]
    assert b.asset == "Terminal B" and b.is_unplanned
    assert b.unavailable_capacity == 8.0
    assert events[2].unavailable_capacity is None


def test_dismissed_events_excluded_by_default() -> None:
    (ev,) = parse_umm_rows([{"Asset affected": "A", "eventStatus": "Dismissed",
                             "Event Start": "2026-01-01", "Event stop": "2026-01-02"}])
    assert filter_events([ev]) == []
    assert filter_events([ev], include_dismissed=True) == [ev]


def test_parse_helpers() -> None:
    assert parse_number("1 234,5 MSm3/d") == pytest.approx(1234.5)
    assert parse_number("n/a") is None
    assert parse_datetime("") is None
    assert parse_datetime("TBD") is None
    naive_oslo = parse_datetime("01.06.2026 12:00", naive_tz=timezone(timedelta(hours=2)))
    assert naive_oslo == datetime(2026, 6, 1, 10, tzinfo=UTC)
    with pytest.raises(ValueError):
        parse_datetime("next tuesday")


def test_events_round_trip_to_gassco_columns() -> None:
    rows = events_to_rows(parse_umm_csv(CSV_TEXT)[:1])
    assert set(UMM_TABLE_COLUMNS).issubset(rows[0])
    again = parse_umm_rows(rows)
    assert again[0].unavailable_capacity == 20.0
