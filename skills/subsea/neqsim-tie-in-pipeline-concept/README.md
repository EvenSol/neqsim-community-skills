# Tie-in pipeline concept

Screening of a new export line from a source facility to a landing point on an existing host: ranked candidate
landing points, a seabed profile from the open EMODnet DTM, pressure drop, thermal decay, DNV-ST-F101 wall
thickness and a recommended nominal size. Pure Python, no JVM needed.

## Install and test

```bash
python -m pip install -e skills/subsea/neqsim-tie-in-pipeline-concept
python -m pytest skills/subsea/neqsim-tie-in-pipeline-concept/tests
```

## Public scope

Uses open bathymetry and generic correlations only. Results are screening indicators. Re-run the chosen case in
NeqSim `PipeBeggsAndBrills` with the real fluid and a surveyed profile, and have the wall thickness reviewed by
qualified pipeline engineering.
