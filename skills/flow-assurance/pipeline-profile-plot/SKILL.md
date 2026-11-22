---
name: neqsim-pipeline-profile-plot
version: "0.1.0"
description: "Along-route pipeline profile plots and hydrate-margin screening from NeqSim results: runs PipeBeggsAndBrills leg by leg over a KP/water-depth route, adds hydrateFormationTemperature at each station, screens where the margin drops below a guideline, and draws stacked depth/pressure/temperature/hydrate-margin panels, a P-T path over the hydrate curve and phase envelope, a margin-coloured planform, and a one-page combined dashboard with the field map. USE WHEN: a task needs to show pressure, temperature and hydrate margin along a flowline or tie-in route, find the KP where a pipeline enters the hydrate region, produce report figures of a NeqSim pipeline run, or combine a pipeline profile with a field map."
last_verified: "2026-11-22"
requires:
  python_packages: [matplotlib, neqsim]
  java_packages: []
  env: []
  network: []
---

# Pipeline Profile Plot

Use this skill to turn a NeqSim pipeline calculation into the figures an
engineer expects in a tie-in or flow assurance note:

1. **Stacked profile** sharing the KP axis: seabed/pipe elevation, pressure,
   fluid temperature against the hydrate equilibrium temperature (with the
   margin band and subcooled area shaded), and hydrate margin coloured
   `ok` / `watch` / `high`.
2. **P-T path** of the pipeline over the NeqSim hydrate curve and (optionally)
   the phase envelope.
3. **Planform** of the route coloured by margin status, optionally on top of
   the field map from `neqsim-offshore-field-map`.
4. **Combined dashboard**: planform + P-T path + stacked profile on one page.

`PipelineProfile.evaluate()` screens the margin with the same rule as
`neqsim-hydrate-margin-check` and reports the minimum margin, its KP, the first
KP in the watch and hydrate regions, and the KP sections involved.

## When to Use

- Show where along a tie-in route the fluid cools into the hydrate region.
- Produce report figures (PNG/SVG) from a NeqSim `PipeBeggsAndBrills` run.
- Compare cases (insulation, flow rate, arrival pressure) by re-running and re-plotting.
- Combine pipeline results with a field map for a one-page illustration.

## Inputs

- Profile data, either from NeqSim or supplied:
  - `kp_km` (km, non-decreasing), `pressure_bara` (bara, absolute), `temperature_c` (C);
  - optional `depth_m` (water depth, m, positive down), `hydrate_temperature_c` (C; NaN allowed),
    `lon` / `lat` (degrees WGS84).
- For the NeqSim helper `run_route_pipeline(inlet_stream, route, ...)`:
  - `inlet_stream`: a run NeqSim `Stream` (fluid, rate, inlet P and T);
  - `route`: rows with `kp_km`, `depth_m` and optional `lon`, `lat`;
  - `diameter_m` (m), `ambient_temperature_c` (C), `heat_transfer_coefficient_w_m2k` (W/m2K),
    `roughness_m` (m), `increments_per_km`.
- For hydrate temperatures: the water-bearing NeqSim fluid (CPA, e.g. `SystemSrkCPAstatoil`),
  `resolution_bar` for caching.
- `min_margin`: hydrate margin guideline in C (default 3.0).

## Outputs

- `PipelineProfile` with derived `elevation_m`, `hydrate_margin_c` and `records()` rows for CSV/JSON.
- `ProfileScreeningResult`: length, inlet/arrival P and T, minimum temperature, minimum margin and KP,
  first watch KP, first hydrate KP, hydrate and watch `Section`s, `margin_warning`
  (`ok`/`watch`/`high`/`unknown`), `neqsim_available`, assumptions.
- `HydrateCurve` (pressure, temperature, errors) and phase envelope dict from the NeqSim bridge.
- Matplotlib figures from `plot_profile`, `plot_pt_trajectory`, `plot_planform`, `plot_combined`;
  `save_figure(fig, path)` writes PNG/SVG/PDF.

## Engineering Method

1. **Hydraulics and heat loss (NeqSim).** The route is split into legs between
   the supplied stations. Each leg is a `PipeBeggsAndBrills` with length
   `sqrt(horizontal^2 + rise^2)`, elevation `depth_in - depth_out` (positive =
   rising), constant surrounding temperature and an overall heat transfer
   coefficient. Legs run in series (outlet stream of one is inlet of the next),
   and the increment profiles (`getLengthProfile`, `getPressureProfile`,
   `getTemperatureProfile`) are stitched onto KP.
2. **Hydrate equilibrium (NeqSim).** At each station's pressure a clone of the
   inlet fluid with `setHydrateCheck(True)` is solved with
   `hydrateFormationTemperature()`. Values are cached on a pressure grid
   (`resolution_bar`). Total composition is assumed constant along the line.
3. **Screening.** `margin = T - T_hydrate`. `<= 0 C` is `high` (inside the
   hydrate region), `< min_margin` is `watch`, otherwise `ok`. Sections are
   contiguous runs of stations; resolution is the station spacing.
4. **Figures.** One y-axis per panel, shared KP axis, fixed status colours
   (ok `#0ca30c`, watch `#fab219`, high `#d03b3b`) always paired with text labels,
   and a footer stating that the figure is a screening illustration.

## Python Usage Pattern

```python
from neqsim import jneqsim
from pipeline_profile_plot import plot_combined, plot_profile, save_figure
from pipeline_profile_plot.neqsim_bridge import add_hydrate_temperatures, hydrate_curve, run_route_pipeline

fluid = jneqsim.thermo.system.SystemSrkCPAstatoil(273.15 + 55.0, 140.0)
for name, moles in [("methane", 80.0), ("ethane", 6.5), ("propane", 3.2), ("CO2", 2.0), ("nC10", 1.5), ("water", 3.5)]:
    fluid.addComponent(name, moles)
fluid.setMixingRule(10)
fluid.setMultiPhaseCheck(True)
stream = jneqsim.process.equipment.stream.Stream("well stream", fluid)
stream.setFlowRate(3.0, "MSm3/day")
stream.run()

route = [
    {"kp_km": 0.0, "depth_m": 345.0, "lon": 3.30, "lat": 60.78},
    {"kp_km": 9.0, "depth_m": 330.0, "lon": 3.42, "lat": 60.72},
    {"kp_km": 25.0, "depth_m": 303.0, "lon": 3.60, "lat": 60.60},
]
profile, pipes = run_route_pipeline(stream, route, diameter_m=0.254,
                                    ambient_temperature_c=4.0, heat_transfer_coefficient_w_m2k=6.0)
profile, _ = add_hydrate_temperatures(profile, fluid, resolution_bar=1.0)

result = profile.evaluate(min_margin=3.0)
print(result.first_hydrate_kp_km, result.min_hydrate_margin_c, result.margin_warning)

save_figure(plot_profile(profile, result=result), "pipeline_profile.png")
save_figure(plot_combined(profile, hydrate_curve=hydrate_curve(fluid, 20, 160, 12)), "pipeline_combined.png")
```

Combined with the field map (`neqsim-offshore-field-map`): build a
`FieldMapBuilder`, add the route with `values=profile.hydrate_margin_c`, and pass
it as `plot_combined(profile, map_builder=fm, ...)`; `fm.save_html()` gives the
interactive version. See `examples/combined_map_and_profile.py`.

Without NeqSim, build `PipelineProfile(...)` or `PipelineProfile.from_records(rows)`
from any validated source and use the same screening and plots.

## Validation Checklist

- [ ] Inlet stream (rate, P, T, composition incl. water and inhibitor) is documented.
- [ ] Route KP and depth come from a stated source (survey, EMODnet sample, or synthetic).
- [ ] Heat transfer coefficient and ambient temperature are stated and justified.
- [ ] Hydrate temperatures came from NeqSim with water present; `HydrateCurve.errors` is empty or explained.
- [ ] Arrival pressure is checked against the host's inlet pressure requirement.
- [ ] Station spacing is fine enough that the reported first hydrate KP is meaningful.
- [ ] Figures carry the screening footer and sources; results are reviewed by a qualified engineer.

## Common Mistakes

| Symptom | Cause | Fix |
| --- | --- | --- |
| `hydrateFormationTemperature` fails ("phase number 4") | Hydrate check not enabled | The bridge calls `setHydrateCheck(True)` on a clone; use a CPA fluid with water |
| Margin far too optimistic | Fluid without water or with inhibitor not modelled | Add water and MEG/methanol to the NeqSim fluid |
| Pressure rises along a descending line unexpectedly | Elevation sign confused | Depth is positive down; rising legs have `depth_in > depth_out` |
| Temperature hardly drops | Heat transfer coefficient too low or wrong unit | `heat_transfer_coefficient_w_m2k` is W/m2K |
| Hydrate section KPs jump in large steps | Too few increments | Raise `increments_per_km` |
| Phase envelope missing on P-T plot | Envelope of water-saturated CPA fluid did not converge | Pass a dry-gas copy to `phase_envelope`, or omit it |

## Limitations

- Steady state only; shut-in cooldown, restart, transients and slugging are not covered.
- Beggs and Brill correlation with a constant overall U and surrounding temperature per run.
- Constant total composition along the line; no water drop-out accumulation or inhibitor partitioning model.
- The hydrate margin rule is a configurable public guideline, not a company design margin.
- Figures are screening illustrations, not design deliverables.

## Related NeqSim Functionality

- `neqsim.process.equipment.pipeline.PipeBeggsAndBrills` - multiphase pressure drop and heat loss per leg.
- `neqsim.process.equipment.stream.Stream` - inlet conditions and leg-to-leg coupling via `getOutletStream()`.
- `neqsim.thermo.system.SystemSrkCPAstatoil` - CPA EoS for water-bearing gas.
- `neqsim.thermodynamicoperations.ThermodynamicOperations#hydrateFormationTemperature()` - hydrate equilibrium temperature.
- `neqsim.thermodynamicoperations.ThermodynamicOperations#calcPTphaseEnvelope()` - phase envelope for the P-T plot.
- NeqSim MCP `runPipeline` and `runFlowAssurance` tools for the same calculations from an agent.

All are reached in Python through `from neqsim import jneqsim`.

## References

- NeqSim: https://github.com/equinor/neqsim
- Beggs, H.D. and Brill, J.P. (1973), "A Study of Two-Phase Flow in Inclined Pipes", JPT 25(5).
- Sloan, E.D. and Koh, C.A., Clathrate Hydrates of Natural Gases, 3rd ed., CRC Press.
- Matplotlib: https://matplotlib.org/
- Related community skills: `neqsim-offshore-field-map`, `neqsim-hydrate-margin-check`,
  `neqsim-pipe-route-profile`, `neqsim-bathymetry-profile-screening`, `neqsim-surf-cooldown-screening`.
