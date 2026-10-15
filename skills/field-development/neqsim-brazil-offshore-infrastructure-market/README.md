# Brazil Offshore Infrastructure and Market

Public data and screening helpers for Brazilian offshore (Santos and Campos pre-salt) gas export routes, processing plants, tariff status, third-party access, gas specification, oil marketing and host capacity. Unknown values stay explicit.

## Install

```bash
python -m pip install -e skills/field-development/neqsim-brazil-offshore-infrastructure-market
```

## Run Tests

```bash
python -m pytest skills/field-development/neqsim-brazil-offshore-infrastructure-market/tests
```

## Example

```bash
python skills/field-development/neqsim-brazil-offshore-infrastructure-market/examples/gas_export_screen.py
```

## Public Scope

The packaged JSON files are a trimmed snapshot of public sources read on 2026-10-14 (ANP, EPE, Petrobras, Equinor, MODEC, PPSA, trade press). Each entry has value, unit, source id, confidence and as_of. The data goes stale: re-check tariffs, capacities, start dates and regulation before use. No company data is included.
