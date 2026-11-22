# Pipeline Profile Plot

Along-route pipeline figures from NeqSim results: stacked seabed/pressure/temperature/hydrate-margin panels, a P-T path over the hydrate curve, a margin-coloured planform, and a one-page combined dashboard with the field map from `neqsim-offshore-field-map`. `PipelineProfile.evaluate()` reports the minimum hydrate margin, the first KP in the watch and hydrate regions, and the KP sections involved.

The optional NeqSim bridge runs `PipeBeggsAndBrills` leg by leg along a KP/water-depth route and adds `hydrateFormationTemperature` at each station.

## Install

```bash
python -m pip install -e "skills/flow-assurance/pipeline-profile-plot[plot,neqsim]"
```

## Run Examples

```bash
python skills/flow-assurance/pipeline-profile-plot/examples/basic_pipeline_profile_plot.py out/
# with the offshore-field-map skill installed too:
python skills/flow-assurance/pipeline-profile-plot/examples/combined_map_and_profile.py out/
```

Without `neqsim` the examples fall back to a small synthetic profile.

## Run Tests

```bash
python -m pytest skills/flow-assurance/pipeline-profile-plot/tests
```

The NeqSim bridge test runs only when `neqsim` is installed; plotting tests need `matplotlib`.

## Public Scope

Examples use synthetic fluids and routes. The screening rule is a configurable public guideline (margin <= 0 C high, < 3 C watch). The figures are screening illustrations; design work needs validated NeqSim models, transient and cooldown analysis, and qualified flow assurance review.
