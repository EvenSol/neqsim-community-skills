---
name: neqsim-anp-open-data
calculation_basis: "screening"
version: "0.1.0"
description: "Guide to reading Brazilian ANP open data for evaluation work: bid-round blocks, field and well production, well and seismic data bank, with CRS, unit and date checks and offline anchor handling. USE WHEN: a task needs Brazilian block, field production or well facts for a Santos, Campos or other Brazilian block, a host field such as a pre-salt FPSO, or a Sodir-like open-data basis."
last_verified: "2026-10-09"
requires:
  python_packages: []
  java_packages: []
  env: []
  network: ["ANP open-data portal (optional)"]
---

# ANP Open Data

Advisory skill. It is the Brazilian counterpart of `neqsim-norwegian-continental-shelf-data` and says what to read, how to trust it and how to hand it on.

## When to Use

- A task needs Brazilian block, field production or well facts for a Santos, Campos or other Brazilian block.
- A host field such as a pre-salt FPSO must be characterised from public data.
- A Sodir-like open-data basis is needed for a Brazilian evaluation.

## Inputs

- The downloaded ANP file and its documentation (header names, separator, decimal mark, encoding, units).
- A header mapping from the names you need to the names in the file.
- The block or field name and the year range of interest.

## Outputs

- Typed rows with explicit unit conversions (oil and gas volumes, daily rates).
- A CRS check for block coordinates and a distance to the host.
- Source, dataset name and download date for `references/SOURCES.md`.

## What to look for

The ANP open-data page (checked 2026-10-09, `gov.br/anp`, "Dados abertos"; also mirrored on `dados.gov.br`) lists these datasets by name. Names are in Portuguese:

- Bid rounds and blocks: "Rodadas de Licitações de Petróleo e Gás Natural", "Fase de Exploração", "Fase de Desenvolvimento e Produção", "Blocos com Fase Exploratória Encerrada", "Dados Georreferenciados das Bacias Sedimentares Brasileiras".
- Production: "Produção de Petróleo e Gás Natural por Poço", "Produção de petróleo e gás natural por estado e localização".
- Wells and technical data: "Resultado de poço", "Dados de E&P", "Acervo de Dados Técnicos", "Amostras de Rochas e Fluidos".
- Planning and money: "Previsão de Atividades e Investimentos Exploratórios", "Participações Governamentais".

The page also links a data inventory spreadsheet and an annual open-data plan. Header names, separators and units are not listed there: read them from the file and its documentation, and do not rely on a remembered column name.

## Python Usage Pattern

The package `anp_open_data` has no data and no assumptions about headers:

```python
from anp_open_data import load_table, oil_volume, gas_volume, monthly_to_daily, check_crs, haversine_km

rows = load_table(path, {"field": "<header>", "month": "<header>", "oil": "<header>"},
                  sep=";", decimal=",", numeric=["month", "oil"])   # KeyError if a header is renamed
rate_bbl_d = oil_volume(monthly_to_daily(rows[0]["oil"], 2026, 3), "m3", "bbl")
```

Separator, decimal mark, encoding and source units are arguments because they differ between datasets; check them in the file before use.

## Engineering Method

- Record the source, dataset name and download date for every number in `references/SOURCES.md`.
- Units: read the unit of every volume column from the file documentation (oil is often in m3 and gas in a thousand-m3 or m3 basis, but confirm); convert explicitly with `oil_volume` and `gas_volume` and state the conversion. Check month versus calendar-year aggregation.
- Coordinates: confirm the CRS and datum of block polygons before computing distance to a host; reproject to a metric CRS first.
- Production history of a host field is public only at the level the portal exposes; ullage and plateau need operator data and belong in a governed layer, not here.
- Keep a small offline anchor table (field, block, year, rate) so a task still runs without network.

## Validation Checklist

- [ ] Header, separator, decimal mark and encoding were read from the file, not remembered.
- [ ] Every volume column has a stated source unit and an explicit conversion.
- [ ] Block polygons were reprojected to a metric CRS before any distance was computed.
- [ ] Each number has its source, dataset name and download date in `references/SOURCES.md`.
- [ ] An offline anchor table exists so the task runs without network.

## Common Mistakes

| Symptom | Cause | Fix |
| --- | --- | --- |
| Rates off by a factor of 1000 | Gas or oil unit assumed | Read the unit from the dataset documentation |
| Wrong decimals | Comma decimal parsed as a thousands separator | Pass `decimal=","` and check a known row |
| Distances look wrong | Geographic CRS used for distance | Reproject, or use `haversine_km` on lat/lon |
| Monthly total used as a rate | No days-in-month conversion | Use `monthly_to_daily` |

## Limitations

- Public production history only; ullage, plateau and operator data belong in a governed layer.
- Dataset names and headers change; the skill holds no column map.
- Screening basis, not a reserves or fiscal statement.

## Hand-offs

- Production series to `neqsim-reservoir-depletion-screening` and decline fitting.
- Block and host positions to `neqsim-pipe-route-profile` and `neqsim-subsea-layout-geometry` for tie-back distance.
- Block facts to `neqsim-psc-bid-economics-screening` and the `frontier-block-bid-agent`.

## References

- ANP open-data portal (`gov.br/anp`, "Dados abertos") and its mirror on `dados.gov.br`; cite dataset name and download date per number.
