"""Live client for the Norwegian Offshore Directorate (Sodir) DataService REST API.

Sodir publishes the FactPages tables as an ArcGIS FeatureServer
(``https://factmaps.sodir.no/api/rest/services/DataService/Data/FeatureServer``),
which Sodir intends to replace the FactPages CSV downloads. Data is open under
the Norwegian Licence for Open Government Data (NLOD) and must be reused with
attribution to the Norwegian Offshore Directorate.

This module is the only part of the skill that touches the network, and only
when a query method is called. All HTTP goes through an injectable ``fetcher``
(``url -> parsed JSON dict``) so tests and offline runs can supply canned
responses. Standard library only.

Table ids and column names were verified against the live service metadata
(``.../FeatureServer/<id>?f=pjson``) on 2026-11-22. Re-check them if Sodir
changes the service; see the FactPages Data Service overview PDF in References.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

SODIR_DATASERVICE_URL = (
    "https://factmaps.sodir.no/api/rest/services/DataService/Data/FeatureServer"
)
SODIR_OPEN_DATA_URL = "https://www.sodir.no/en/facts/data-and-analyses/open-data/"
SODIR_ATTRIBUTION = (
    "Source: Norwegian Offshore Directorate (Sodir) FactPages DataService, "
    "open data under the Norwegian Licence for Open Government Data (NLOD)."
)

#: DataService table ids (FeatureServer layer/table numbers).
TABLE_IDS: dict[str, int] = {
    "company": 1200,
    "licence": 3000,
    "wellbore": 5000,
    "facility": 6000,
    "pipeline": 6100,
    "tuf": 6200,
    "discovery": 7000,
    "discovery_reserves": 7008,
    "field": 7100,
    "field_description": 7102,
    "field_reserves": 7113,
    "profiles": 7300,  # monthly/yearly saleable production + investments
}

#: Server page size (``maxRecordCount``) of the DataService tables.
DEFAULT_PAGE_SIZE = 2000

Fetcher = Callable[[str], Mapping[str, Any]]


class SodirApiError(RuntimeError):
    """Raised when the DataService returns an error or an unexpected payload."""


def default_fetcher(url: str, *, timeout_s: float = 60.0) -> Mapping[str, Any]:
    """Fetch ``url`` with the standard library and parse the JSON body."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "neqsim-community-skills/norwegian-continental-shelf-data",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:  # includes HTTPError
        raise SodirApiError(f"Sodir DataService request failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SodirApiError("Sodir DataService returned non-JSON content") from exc
    return payload


def sql_quote(value: str) -> str:
    """Quote a string literal for an ArcGIS ``where`` clause."""
    return "'" + str(value).replace("'", "''") + "'"


# --------------------------------------------------------------------------- #
# Typed records
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ProductionRecord:
    """One saleable-production row from the ``profiles`` table (7300).

    Volumes are per period (a month, or a year when ``month == 0``): oil, NGL,
    condensate and water in million Sm3, gas in billion Sm3, o.e. in million
    Sm3 o.e. ``*_net`` is saleable (net) volume; ``*_gross`` is gross volume as
    published by Sodir. ``water_mill_sm3`` is produced water in field and is
    often not published (``None``).
    """

    carrier: str
    carrier_kind: str
    year: int
    month: int
    oil_net: float
    gas_net: float
    ngl_net: float
    condensate_net: float
    oe_net: float
    oil_gross: float | None = None
    gas_gross: float | None = None
    condensate_gross: float | None = None
    oe_gross: float | None = None
    water_mill_sm3: float | None = None

    @property
    def is_monthly(self) -> bool:
        return self.month > 0


@dataclass(frozen=True)
class Facility:
    """A Sodir facility (table 6000) with decimal-degree coordinates."""

    npdid: int | None
    name: str
    kind: str
    phase: str
    functions: str
    fixed_or_moveable: str
    belongs_to: str
    belongs_to_kind: str
    operator: str
    water_depth_m: float | None
    startup: str | None
    design_lifetime_years: int | None
    latitude: float | None
    longitude: float | None
    fact_page_url: str | None = None


@dataclass(frozen=True)
class DiscoveryResources:
    """Recoverable resources of a discovery (table 7008)."""

    oil_mill_sm3: float | None
    gas_bill_sm3: float | None
    ngl_mill_tonnes: float | None
    condensate_mill_sm3: float | None
    oe_mill_sm3: float | None
    resource_category: str | None


@dataclass(frozen=True)
class Discovery:
    """A Sodir discovery (table 7000) with an approximate centroid."""

    npdid: int | None
    name: str
    status: str
    hc_type: str
    operator: str
    main_area: str
    discovery_year: int | None
    field_name: str | None
    latitude: float | None
    longitude: float | None
    resources: DiscoveryResources | None = None
    fact_page_url: str | None = None


# --------------------------------------------------------------------------- #
# Geometry helpers (shared with host_analysis)
# --------------------------------------------------------------------------- #


def dms_to_decimal(
    degrees: float | None, minutes: float | None, seconds: float | None, code: str | None
) -> float | None:
    """Convert degrees/minutes/seconds plus N/S/E/W code to decimal degrees."""
    if degrees is None:
        return None
    value = float(degrees) + float(minutes or 0.0) / 60.0 + float(seconds or 0.0) / 3600.0
    if code and code.strip().upper() in {"S", "W"}:
        value = -value
    return value


def esri_centroid(geometry: Mapping[str, Any] | None) -> tuple[float, float] | None:
    """Return ``(lat, lon)`` from an ESRI JSON point/polygon geometry.

    Points use ``x``/``y``. Polygons use the vertex mean of the outer ring,
    which is adequate for screening distances (km scale), not for survey work.
    The geometry must be requested in WGS84 (``outSR=4326``).
    """
    if not geometry:
        return None
    if "x" in geometry and "y" in geometry:
        if geometry["x"] is None or geometry["y"] is None:
            return None
        return float(geometry["y"]), float(geometry["x"])
    rings = geometry.get("rings")
    if rings:
        ring = max(rings, key=len)
        if ring and ring[0] == ring[-1] and len(ring) > 1:
            ring = ring[:-1]
        if not ring:
            return None
        lon = sum(p[0] for p in ring) / len(ring)
        lat = sum(p[1] for p in ring) / len(ring)
        return lat, lon
    return None


def _epoch_ms_to_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc).date().isoformat()
    return str(value)


def _opt_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _float0(value: Any) -> float:
    return 0.0 if value in (None, "") else float(value)


def _opt_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #


@dataclass
class SodirDataService:
    """Thin, paginating client for the Sodir DataService FeatureServer.

    Parameters
    ----------
    fetcher:
        Callable ``url -> parsed JSON``. Defaults to :func:`default_fetcher`
        (live network). Inject a fake for tests or cached/offline runs.
    base_url:
        FeatureServer root. Override only if Sodir moves the service.
    page_size:
        Records requested per page (server maximum is 2000).
    max_records:
        Safety cap on records returned by a single :meth:`query`.
    """

    fetcher: Fetcher | None = None
    base_url: str = SODIR_DATASERVICE_URL
    page_size: int = DEFAULT_PAGE_SIZE
    max_records: int = 200_000
    requested_urls: list[str] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if self.page_size <= 0:
            raise ValueError("page_size must be positive")
        if self.max_records <= 0:
            raise ValueError("max_records must be positive")

    # -- low level ----------------------------------------------------------

    @staticmethod
    def table_id(table: str | int) -> int:
        if isinstance(table, int):
            return table
        try:
            return TABLE_IDS[table]
        except KeyError as exc:
            raise KeyError(
                f"Unknown DataService table {table!r}; known: {sorted(TABLE_IDS)}"
            ) from exc

    def query_url(
        self,
        table: str | int,
        *,
        where: str = "1=1",
        out_fields: str | Sequence[str] = "*",
        return_geometry: bool = False,
        out_sr: int | None = 4326,
        order_by: str | None = "OBJECTID",
        offset: int = 0,
        count: int | None = None,
        max_allowable_offset: float | None = None,
    ) -> str:
        """Build a FeatureServer ``query`` URL (no network access)."""
        fields_param = out_fields if isinstance(out_fields, str) else ",".join(out_fields)
        params: dict[str, Any] = {
            "where": where,
            "outFields": fields_param,
            "returnGeometry": "true" if return_geometry else "false",
            "resultOffset": offset,
            "resultRecordCount": count if count is not None else self.page_size,
            "f": "json",
        }
        if order_by:
            params["orderByFields"] = order_by
        if return_geometry and out_sr is not None:
            params["outSR"] = out_sr
        if return_geometry and max_allowable_offset is not None:
            params["maxAllowableOffset"] = max_allowable_offset
        query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        return f"{self.base_url.rstrip('/')}/{self.table_id(table)}/query?{query}"

    def _fetch(self, url: str) -> Mapping[str, Any]:
        self.requested_urls.append(url)
        fetch = self.fetcher or default_fetcher
        payload = fetch(url)
        if not isinstance(payload, Mapping):
            raise SodirApiError("DataService payload is not a JSON object")
        if "error" in payload:
            err = payload["error"]
            message = err.get("message") if isinstance(err, Mapping) else err
            raise SodirApiError(f"DataService error: {message}")
        return payload

    def query(
        self,
        table: str | int,
        *,
        where: str = "1=1",
        out_fields: str | Sequence[str] = "*",
        return_geometry: bool = False,
        out_sr: int | None = 4326,
        order_by: str | None = "OBJECTID",
        max_allowable_offset: float | None = None,
    ) -> list[dict[str, Any]]:
        """Run a query and follow pagination; return attribute dicts.

        When ``return_geometry`` is true each row carries the ESRI geometry
        under the ``"_geometry"`` key.
        """
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            url = self.query_url(
                table,
                where=where,
                out_fields=out_fields,
                return_geometry=return_geometry,
                out_sr=out_sr,
                order_by=order_by,
                offset=offset,
                max_allowable_offset=max_allowable_offset,
            )
            payload = self._fetch(url)
            features = payload.get("features")
            if features is None:
                raise SodirApiError("DataService payload has no 'features' array")
            for feature in features:
                row = dict(feature.get("attributes") or {})
                if return_geometry:
                    row["_geometry"] = feature.get("geometry")
                rows.append(row)
            if len(rows) >= self.max_records:
                return rows[: self.max_records]
            if not payload.get("exceededTransferLimit") or not features:
                return rows
            offset += len(features)

    # -- typed helpers -------------------------------------------------------

    def field_overview(self, field_name: str) -> dict[str, Any]:
        """Return the Field overview row (table 7100) for ``field_name``."""
        rows = self.query(
            "field", where=f"UPPER(fldName)={sql_quote(field_name.upper())}"
        )
        if not rows:
            raise KeyError(f"Field {field_name!r} not found in Sodir DataService")
        return rows[0]

    def field_production(
        self, field_name: str, *, period: str = "month"
    ) -> list[ProductionRecord]:
        """Saleable production for one field from the ``profiles`` table.

        ``period`` is ``"month"`` (monthly rows) or ``"year"`` (yearly rows).
        Rows are returned in chronological order.
        """
        if period not in {"month", "year"}:
            raise ValueError("period must be 'month' or 'year'")
        where = (
            f"UPPER(prfInformationCarrier)={sql_quote(field_name.upper())} "
            f"AND prfPeriod={sql_quote(period)}"
        )
        rows = self.query("profiles", where=where, order_by="prfYear,prfMonth")
        # Defensive client-side filter: yearly rows carry prfMonth == 0.
        records = [
            rec
            for rec in (production_record_from_attributes(r) for r in rows)
            if rec.is_monthly == (period == "month")
        ]
        records.sort(key=lambda r: (r.year, r.month))
        return records

    def facilities(
        self, *, belongs_to: str | None = None, name: str | None = None
    ) -> list[Facility]:
        """Facilities (table 6000), optionally filtered by field or name."""
        clauses = []
        if belongs_to:
            clauses.append(f"UPPER(fclBelongsToName)={sql_quote(belongs_to.upper())}")
        if name:
            clauses.append(f"UPPER(fclName)={sql_quote(name.upper())}")
        rows = self.query("facility", where=" AND ".join(clauses) or "1=1")
        return [facility_from_attributes(r) for r in rows]

    def discoveries(
        self, *, where: str = "1=1", with_resources: bool = True
    ) -> list[Discovery]:
        """Discoveries (table 7000) with centroids and optional resources (7008)."""
        rows = self.query(
            "discovery",
            where=where,
            return_geometry=True,
            max_allowable_offset=0.01,
        )
        resources: dict[int, DiscoveryResources] = {}
        if with_resources and rows:
            resources = self.discovery_resources()
        out = []
        for row in rows:
            npdid = _opt_int(row.get("dscNpdidDiscovery"))
            out.append(
                discovery_from_attributes(row, resources.get(npdid) if npdid else None)
            )
        return out

    def discovery_resources(self) -> dict[int, DiscoveryResources]:
        """Latest recoverable-resource estimate per discovery NPDID (table 7008)."""
        rows = self.query("discovery_reserves")
        latest: dict[int, tuple[Any, DiscoveryResources]] = {}
        for row in rows:
            npdid = _opt_int(row.get("dscNpdidDiscovery"))
            if npdid is None:
                continue
            stamp = row.get("dscReservesDateUpdated") or 0
            res = DiscoveryResources(
                oil_mill_sm3=_opt_float(row.get("dscRecoverableOil")),
                gas_bill_sm3=_opt_float(row.get("dscRecoverableGas")),
                ngl_mill_tonnes=_opt_float(row.get("dscRecoverableNGL")),
                condensate_mill_sm3=_opt_float(row.get("dscRecoverableCondensate")),
                oe_mill_sm3=_opt_float(row.get("dscRecoverableOe")),
                resource_category=_text(row.get("dscReservesRC")) or None,
            )
            if npdid not in latest or (stamp or 0) >= (latest[npdid][0] or 0):
                latest[npdid] = (stamp, res)
        return {k: v[1] for k, v in latest.items()}


# --------------------------------------------------------------------------- #
# Attribute -> record mappers (public so cached JSON can be reused offline)
# --------------------------------------------------------------------------- #


def production_record_from_attributes(row: Mapping[str, Any]) -> ProductionRecord:
    return ProductionRecord(
        carrier=_text(row.get("prfInformationCarrier")),
        carrier_kind=_text(row.get("prfInformationCarrierKind")),
        year=int(row["prfYear"]),
        month=int(row.get("prfMonth") or 0),
        oil_net=_float0(row.get("prfPrdOilNetMillSm3")),
        gas_net=_float0(row.get("prfPrdGasNetBillSm3")),
        ngl_net=_float0(row.get("prfPrdNGLNetMillSm3")),
        condensate_net=_float0(row.get("prfPrdCondensateNetMillSm3")),
        oe_net=_float0(row.get("prfPrdOeNetMillSm3")),
        oil_gross=_opt_float(row.get("prfPrdOilGrossMillSm3")),
        gas_gross=_opt_float(row.get("prfPrdGasGrossBillSm3")),
        condensate_gross=_opt_float(row.get("prfPrdCondensateGrossMillSm3")),
        oe_gross=_opt_float(row.get("prfPrdOeGrossMillSm3")),
        # Sodir truncates this column name to 31 characters.
        water_mill_sm3=_opt_float(
            row.get("prfPrdProducedWaterInFieldMillS")
            if "prfPrdProducedWaterInFieldMillS" in row
            else row.get("prfPrdProducedWaterInFieldMillSm3")
        ),
    )


def facility_from_attributes(row: Mapping[str, Any]) -> Facility:
    lat = dms_to_decimal(
        row.get("fclNsDeg"), row.get("fclNsMin"), row.get("fclNsSec"), row.get("fclNsCode")
    )
    lon = dms_to_decimal(
        row.get("fclEwDeg"), row.get("fclEwMin"), row.get("fclEwSec"), row.get("fclEwCode")
    )
    if (lat is None or lon is None) and row.get("_geometry"):
        centroid = esri_centroid(row.get("_geometry"))
        if centroid:
            lat, lon = centroid
    return Facility(
        npdid=_opt_int(row.get("fclNpdidFacility")),
        name=_text(row.get("fclName")),
        kind=_text(row.get("fclKind")),
        phase=_text(row.get("fclPhase")),
        functions=_text(row.get("fclFunctions")),
        fixed_or_moveable=_text(row.get("fclFixedOrMoveable")),
        belongs_to=_text(row.get("fclBelongsToName")),
        belongs_to_kind=_text(row.get("fclBelongsToKind")),
        operator=_text(row.get("fclCurrentOperatorName")),
        water_depth_m=_opt_float(row.get("fclWaterDepth")),
        startup=_epoch_ms_to_date(row.get("fclStartupDate")),
        design_lifetime_years=_opt_int(row.get("fclDesignLifetime")),
        latitude=lat,
        longitude=lon,
        fact_page_url=_text(row.get("fclFactPageUrl")) or None,
    )


def discovery_from_attributes(
    row: Mapping[str, Any], resources: DiscoveryResources | None = None
) -> Discovery:
    centroid = esri_centroid(row.get("_geometry"))
    return Discovery(
        npdid=_opt_int(row.get("dscNpdidDiscovery")),
        name=_text(row.get("dscName")),
        status=_text(row.get("dscCurrentActivityStatus")),
        hc_type=_text(row.get("dscHcType")),
        operator=_text(row.get("cmpLongName")),
        main_area=_text(row.get("nmaName")),
        discovery_year=_opt_int(row.get("dscDiscoveryYear")),
        field_name=_text(row.get("fldName")) or None,
        latitude=centroid[0] if centroid else None,
        longitude=centroid[1] if centroid else None,
        resources=resources,
        fact_page_url=_text(row.get("dscFactPageUrl")) or None,
    )
