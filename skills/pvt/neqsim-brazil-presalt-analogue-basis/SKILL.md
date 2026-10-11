---
name: neqsim-brazil-presalt-analogue-basis
calculation_basis: "screening"
version: "0.1.0"
description: "Declared best-guess fluid and flow-assurance basis for Santos Basin pre-salt blocks when no PVT exists: analogue ranges, CO2-rich gas handling, material and EOS checks, and an assumption register. USE WHEN: a frontier block in Santos or Campos pre-salt must be evaluated, a CO2-rich associated gas or CO2 re-injection case is in play, or a near-field analogue fluid is needed."
last_verified: "2026-10-09"
requires:
  python_packages: []
  java_packages: []
  env: []
  network: []
---

# Brazil Pre-Salt Analogue Basis

Advisory skill. It tells an agent how to build a declared, low/base/high fluid and flow-assurance basis for a pre-salt block that has no PVT report, and what to check before trusting a NeqSim result on it.

## When to Use

- A frontier Santos or Campos pre-salt block has no PVT report and a fluid basis is needed to proceed.
- A CO2-rich associated gas or a CO2 re-injection case must be screened before measured data exist.
- A near-field analogue fluid is needed for a tie-back or concept study.

## Inputs

- Datum depth below sea level, water depth and any measured temperature, pressure, GOR or API.
- Two or more named public analogue fields with depth, API, GOR and a source note.
- The CO2 range you can cite, with the source.

## Engineering Method

1. Start from `neqsim-reference-fluid-synthetic-generation` (no-PVT route): reservoir temperature from the depth and a stated geothermal gradient, GOR and oil density bands from named analogue fields, and low/base/high cases.
2. Treat the analogue values as inputs to confirm, not facts. Pre-salt carbonate reservoirs are generally light to medium oil with high GOR and CO2 in the associated gas that varies strongly between fields and within a field. Set the CO2 range from the analogue data you can cite, and record the source in the assumption register.
3. Run the low and high CO2 cases through the whole chain, not only the base case. CO2 content drives phase envelope, hydrate and dense-phase behaviour, separation and compression duty, and the need for CO2 removal or re-injection.
4. Gate the numbers before use:
   - Check a CO2-rich phase envelope and a saturation pressure against any available analogue PVT; flag if the EOS is outside its validated range. The NeqSim test `Co2RichAssociatedGasConsistencyTest` is the pass/fail gate for physical consistency (pure-CO2 critical temperature, bubble pressure rising with CO2, one dense phase above the cricondenbar). It is not a validation against measured pre-salt PVT; add measured data per field and say so in `data_gaps`.
   - Check hydrate and freezing margins on the CO2-rich gas.
   - Screen materials for sour or CO2 service with `neqsim-flow-assurance` and the material-selection skills; high CO2 partial pressure at depth is a corrosion driver.
5. Show the effect of re-injecting CO2 or gas as a separate case with `neqsim-ccs-hydrogen`.

## Outputs

- Low/base/high fluid composition and properties.
- Phase-envelope and hydrate margin per case.
- CO2 removal and re-injection screening flag.
- `assumptions` and `data_gaps` entries naming every analogue used.

## Python Usage Pattern

```python
from reference_fluid import FluidAnalogue, build_analogue_fluid_basis

analogues = [
    FluidAnalogue(name="Analogue A", play="Santos pre-salt", depth_tvdss_m=5200.0,
                  api_degrees=29.0, gor_sm3_sm3=250.0, note="cite the public source here"),
    FluidAnalogue(name="Analogue B", play="Santos pre-salt", depth_tvdss_m=5400.0,
                  api_degrees=30.0, gor_sm3_sm3=300.0),
]
basis = build_analogue_fluid_basis(datum_tvdss_m=5300.0, water_depth_m=2000.0, analogues=analogues)
basis["cases"], basis["assumption_register"]   # low/base/high and the register
```

The analogue values above are placeholders to show the call shape, not pre-salt data.

## Validation Checklist

- [ ] Every analogue is named and its source is in the assumption register.
- [ ] Low and high CO2 cases were run through the whole chain, not only the base case.
- [ ] `Co2RichAssociatedGasConsistencyTest` passes and the result is not described as measured-PVT validation.
- [ ] Hydrate, freezing and corrosion screening used the CO2-rich composition.
- [ ] CO2 re-injection is a separate case.

## Common Mistakes

| Symptom | Cause | Fix |
| --- | --- | --- |
| Base-case result quoted alone | CO2 range not carried through | Run low and high CO2 cases |
| Analogue numbers treated as facts | No source or confidence recorded | Put each in the assumption register |
| Consistent test read as validation | Gate checks physics, not field PVT | Add measured data per field and list the gap in `data_gaps` |
| Dense-phase behaviour missed | Only a gas-oil flash checked | Check the CO2-rich phase envelope |

## Limitations

- No measured pre-salt PVT; the basis is a declared best guess.
- CO2 content varies strongly between and within fields; the range must be cited per study.
- Not suitable for design, reserves booking or a bid decision without measured data.

## Related

- `neqsim-reference-fluid-synthetic-generation`, `neqsim-reservoir-model-builder`, `neqsim-phase-envelope`, `neqsim-flow-assurance`, `neqsim-ccs-hydrogen`, `neqsim-psc-bid-economics-screening`.

## References

- Public field papers and ANP or operator disclosures for each named analogue; cite them in the assumption register.
- `Co2RichAssociatedGasConsistencyTest` in the NeqSim test suite for the physical-consistency gate.
