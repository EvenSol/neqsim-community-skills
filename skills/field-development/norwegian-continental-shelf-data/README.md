# Norwegian Continental Shelf Reference Data

Educational, dependency-free, offline database of public Norwegian Continental
Shelf (NCS) facts — headline national KPIs, a resource-accounting split, sea
areas, and a qualitative inventory of major fields — plus screening-analysis
helpers for production and resource studies. It also has an opt-in live
client for the Sodir DataService REST API with tie-in host screening (GOR and
water-cut trends, an ullage proxy, nearby undeveloped discoveries), and an
offline Gassco UMM export-availability parser.

Data is sourced from [norskpetroleum.no](https://www.norskpetroleum.no/en/)
(Norwegian Petroleum, run by the Norwegian Ministry of Energy and the Norwegian
Offshore Directorate) and the Sodir FactPages, which publish open,
reusable-with-attribution data. The bundled data is a public *seed*; the full
production time series and per-field figures are refreshed by ingesting the
official Sodir/norskpetroleum.no CSV exports. See `SKILL.md` for the method,
the ingestion path, and the validated NeqSim workflows this data feeds.

## Quick Start

```bash
cd skills/field-development/norwegian-continental-shelf-data
python -m pytest          # run tests from inside the skill folder
python examples/basic_ncs_data.py
python examples/gassco_umm_screening.py            # offline, synthetic events
python examples/live_host_context.py GRANE 40      # needs factmaps.sodir.no
```

## Layout

- `src/norwegian_continental_shelf_data/dataset.py` — loader, queries, ingestion.
- `src/norwegian_continental_shelf_data/analysis.py` — screening analysis helpers.
- `src/norwegian_continental_shelf_data/sodir_api.py` — live Sodir DataService client (only module that uses the network).
- `src/norwegian_continental_shelf_data/host_analysis.py` — host rates, GOR/water-cut trend, ullage proxy, nearby discoveries, `host_context`.
- `src/norwegian_continental_shelf_data/gassco_umm.py` — Gassco UMM event parsing (CSV/rows/Atom) and capacity-impact screening.
- `src/norwegian_continental_shelf_data/data/ncs_reference.json` — public seed.
- `examples/basic_ncs_data.py` — minimal usage example.
- `tests/` — unit tests (run from inside this folder).

## Attribution

Source: Norwegian Petroleum (www.norskpetroleum.no), Norwegian Ministry of
Energy and Norwegian Offshore Directorate. Reused figures must keep this
attribution and a link to www.norskpetroleum.no.

Live Sodir data: Norwegian Offshore Directorate, open data under the Norwegian
Licence for Open Government Data (NLOD). Gassco UMM: Gassco AS (umm.gassco.no).
Gassco states the information is not exhaustive. Events are parsed from files
the user saves, and the skill never fetches the site.

## License

Apache-2.0 (skill code). NCS facts are open data reusable with attribution.
