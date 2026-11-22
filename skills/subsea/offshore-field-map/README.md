# Offshore Field Map

Offshore field maps for NeqSim studies from open data: Norwegian Offshore Directorate (Sodir) FactMaps facilities, main pipelines and field outlines, plus EMODnet Bathymetry as a map overlay and for depth sampling along a route. Maps render as interactive folium HTML, static matplotlib planforms, or GeoJSON. Candidate tie-in routes can be coloured by a NeqSim result such as hydrate margin from the `neqsim-pipeline-profile-plot` skill.

## Install

```bash
python -m pip install -e "skills/subsea/offshore-field-map[map,plot]"
```

The core package has no dependencies; `folium` (`map`) and `matplotlib` (`plot`) are optional extras.

## Run Example

```bash
# offline, synthetic layers
python skills/subsea/offshore-field-map/examples/basic_offshore_field_map.py out/
# live open data around a named facility (needs internet)
python skills/subsea/offshore-field-map/examples/basic_offshore_field_map.py out/ --live "TROLL A"
```

## Run Tests

```bash
python -m pytest skills/subsea/offshore-field-map/tests
```

Tests run offline with synthetic Sodir-shaped GeoJSON and injected fetchers.

## Public Scope and Attribution

The skill uses public open data only: Sodir FactMaps (NLOD 2.0), EMODnet Bathymetry (CC BY 4.0) and OpenStreetMap basemap tiles (ODbL), and keeps those attributions on every map it renders. Examples use synthetic names and positions. Maps are screening illustrations, not for navigation, survey or design. Network access happens only when `fetch_layer` or the EMODnet sampling functions are called.
