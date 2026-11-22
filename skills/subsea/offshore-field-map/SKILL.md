---
name: neqsim-offshore-field-map
version: "0.1.0"
description: "Offshore field maps for NeqSim tie-in and flow assurance studies from open data: Norwegian Offshore Directorate (Sodir) FactMaps facilities, pipelines and fields (NLOD 2.0) plus an EMODnet Bathymetry overlay and route depth sampling (CC BY 4.0), rendered as an interactive folium map, a static matplotlib planform, or GeoJSON, with candidate tie-in routes coloured by a NeqSim result such as hydrate margin. USE WHEN: a task needs a map or illustration of a field, host facility, existing pipelines, new wells and a candidate tie-in route on the Norwegian continental shelf, needs seabed depth along a route from EMODnet, or needs to show NeqSim pipeline results (hydrate margin, temperature, pressure) spatially along a route."
last_verified: "2026-11-22"
requires:
  python_packages: [folium, matplotlib]
  java_packages: []
  env: []
  network: [factmaps.sodir.no, ows.emodnet-bathymetry.eu, rest.emodnet-bathymetry.eu]
---

# Offshore Field Map

Use this skill to put a NeqSim study on a map. It pulls the public context from
open data (Sodir FactMaps facilities, main pipelines and field outlines; EMODnet
bathymetry), adds the study's own objects (new wells, templates, a tie-in point,
candidate routes), and renders them as:

- an interactive **folium** (Leaflet) HTML map with an EMODnet bathymetry WMS
  overlay, depth contours, layer control, tooltips and a legend with source
  attribution;
- a static **matplotlib** planform for reports and slides;
- one **GeoJSON** `FeatureCollection` for other tools.

Routes can carry one value per vertex - typically the hydrate margin from the
`neqsim-pipeline-profile-plot` skill - and are coloured `ok` / `watch` / `high`,
which is how the map and the pipeline profile are combined.

The skill renders and transports data. It performs no thermodynamic or
hydraulic calculation; those come from NeqSim.

## When to Use

- Illustrate a tie-in study: new well(s), candidate host, existing pipelines and fields.
- Look up a host facility's position and water depth, or pipelines near it, from Sodir.
- Get a first seabed depth profile along a candidate route from EMODnet before
  running `PipeBeggsAndBrills` (feed it to `neqsim-pipe-route-profile` or the
  `run_route_pipeline` helper of `neqsim-pipeline-profile-plot`).
- Show NeqSim results spatially: colour a route by hydrate margin, arrival
  temperature or velocity and give each station a KP/P/T tooltip.

## Inputs

- Sodir layers as parsed GeoJSON (offline) or fetched with `fetch_layer(layer, where=..., bbox=...)`.
  Layer aliases (`LAYERS`): `facilities_in_place` (304), `facilities_all` (307),
  `pipelines` (311), `fields` (502), `discoveries_active` (503), `wellbores_all` (201).
- `bbox`: `(min_lon, min_lat, max_lon, max_lat)` in WGS84 degrees; `bbox_around(points, margin_km)` builds one.
- Nodes: dicts with `name`, `lon`, `lat` (degrees), optional `kind`
  (`well`, `template`, `manifold`, `tie_in`, `riser_base`, `host`) and `water_depth_m` (m, positive down).
- Routes: list of `(lon, lat)`; optional `values` (one per vertex, e.g. hydrate margin in C),
  `thresholds=(limit, watch)` (default `(0, 3)` C), `higher_is_better`, `vertex_info` (tooltip dicts).
- EMODnet: `wms_overlay(style)` with style `multicolour`, `rainbow`, `atlas_land` or `contours`;
  `sample_route_depths(coords)` / `sample_point_depth(lon, lat)` for depths.
- `fetcher`: optional callable `url -> parsed JSON` for offline tests, caching or a proxy.

## Outputs

- `Facility`, `Pipeline`, `FieldArea` records with the key Sodir attributes
  (kind, phase, water depth, from/to facility, medium, diameter in inch, max water depth, status).
- `DepthSample(distance_m, lon, lat, depth_m)` list along a route (depth positive downwards).
- `FieldMapBuilder.summary()` -> `MapSummary`: layer counts, bounding box, route lengths (km,
  great-circle), worst status per route, attributions, warnings, `neqsim_available`, assumptions.
- `to_geojson()`, `to_folium()` / `save_html(path)`, `plot_static(ax)`.

## Engineering Method

1. **Context data.** FactMaps is an ArcGIS MapServer; queries use `f=geojson`,
   `outSR=4326` and an envelope filter, paged in blocks of up to 1000 records
   (the service `maxRecordCount`). Records that cannot be parsed are skipped and
   listed in a `NormalizeReport`, so a partial layer is still usable.
2. **Bathymetry.** The WMS overlay is drawn by the browser from EMODnet. Depth
   sampling uses the EMODnet REST service: `depth_sample` returns the cell mean
   elevation and `depth_profile` an equally spaced list along a line. Elevations
   (negative below sea level) are converted to water depth (positive down),
   matching the community subsea skills.
3. **Geometry.** Route lengths use the haversine great-circle distance on a
   6371 km sphere; positions along a route are interpolated linearly in lon/lat.
4. **Route colouring.** Each vertex value is classified with the
   `neqsim-hydrate-margin-check` rule (`<= limit` high, `< watch` watch, else ok;
   mirrored for lower-is-better quantities). A segment takes the worse status of
   its two ends - conservative. Pass densely sampled stations (for example every
   NeqSim pipe increment) so the colour change sits close to the real KP.
5. **Attribution.** Every rendering lists the open-data sources used
   (Sodir NLOD 2.0, EMODnet CC BY 4.0, OpenStreetMap ODbL basemap).

## Python Usage Pattern

```python
from offshore_field_map import (
    LAYERS, FieldMapBuilder, bbox_around, facilities_by_name, fetch_layer,
    normalize_facilities, normalize_fields, normalize_pipelines, sample_route_depths,
)

# 1. Context from Sodir FactMaps (network, NLOD 2.0)
host = facilities_by_name(normalize_facilities(
    fetch_layer(LAYERS["facilities_in_place"], where="fclName='TROLL A'")))["TROLL A"]
box = bbox_around([(host.lon, host.lat)], margin_km=40)

fm = FieldMapBuilder("New well tie-in to Troll A")
fm.add_fields(normalize_fields(fetch_layer(LAYERS["fields"], bbox=box)))
fm.add_pipelines(normalize_pipelines(fetch_layer(LAYERS["pipelines"], bbox=box)))
fm.add_facilities(normalize_facilities(fetch_layer(LAYERS["facilities_in_place"], bbox=box)),
                  highlight=["TROLL A"])

# 2. Study objects and a candidate route
route = [(3.45, 60.75), (3.60, 60.70), (host.lon, host.lat)]
fm.add_nodes([{"name": "NEW-1", "lon": 3.45, "lat": 60.75, "kind": "well"}])
depths = sample_route_depths(route)          # EMODnet, CC BY 4.0
fm.add_route("NEW-1 to TROLL A", route)       # or values=hydrate_margin_per_vertex

# 3. Render
fm.save_html("field_map.html", bathymetry="multicolour")
ax = fm.plot_static()
print(fm.summary().attributions)
```

Offline, pass parsed GeoJSON to the `normalize_*` functions or give
`fetch_layer(..., fetcher=my_cached_loader)`. `examples/basic_offshore_field_map.py`
runs offline with synthetic layers and has a `--live NAME` mode.

To combine with a NeqSim pipeline run, colour the route by the profile from
`neqsim-pipeline-profile-plot`:

```python
fm.add_route(profile.name, list(zip(profile.lon, profile.lat)),
             values=profile.hydrate_margin_c, thresholds=(0.0, 3.0),
             vertex_info=profile.records())
```

## Validation Checklist

- [ ] Coordinates are WGS84 lon/lat (EPSG:4326); FactMaps queries use the WGS84 service.
- [ ] The highlighted host facility was found (no "not found" warning in `summary().warnings`).
- [ ] The Sodir pipeline layer was understood to contain main pipelines only (no infield lines).
- [ ] EMODnet depths were converted to positive-down water depth and spot-checked against a known depth (e.g. the facility's `fclWaterDepth`).
- [ ] Route colouring values came from validated NeqSim calculations and the thresholds are stated.
- [ ] Attributions (NLOD 2.0, CC BY 4.0, ODbL) are visible on every shared figure or page.
- [ ] Maps are labelled as screening illustrations, not for navigation, survey or design.

## Common Mistakes

| Symptom | Cause | Fix |
| --- | --- | --- |
| Points plotted in the wrong place | Latitude/longitude swapped | GeoJSON and this skill use `(lon, lat)` order |
| Pipeline from a subsea template is missing | Infield lines are not in Sodir layer 311 | Draw the tie-in yourself with `add_route` |
| Only 1000 features returned | Paging stopped early | Use `fetch_layer` (pages automatically) or raise `max_pages` |
| Depths are negative | Raw EMODnet elevations used | Use `elevation_to_depth` / `sample_route_depths` |
| Whole segment red though only its end is in the hydrate region | Coarse vertices, worse-end rule | Pass every NeqSim station as a vertex |
| Blank bathymetry in the HTML | Viewer has no internet access to EMODnet WMS | Open the HTML online, or rely on `plot_static` |

## Limitations

- No route optimisation, obstacle avoidance or seabed engineering; routes are what you supply.
- EMODnet DTM resolution (about 115 m grid) does not resolve local seabed features; use survey data for design.
- Sodir data reflect the public register at fetch time; positions are reference points, not as-built.
- Static plots have no basemap tiles; folium maps need internet access in the viewer for tiles and WMS.
- Colouring is a classification of supplied values only and is not a flow assurance assessment.

## Related NeqSim Functionality

This skill only prepares and renders spatial context. The validated calculations whose results it displays live in NeqSim:

- `neqsim.process.equipment.pipeline.PipeBeggsAndBrills` - pressure and temperature along the route whose geometry and depth this skill provides.
- `neqsim.thermodynamicoperations.ThermodynamicOperations#hydrateFormationTemperature()` - hydrate equilibrium temperature behind the hydrate-margin colouring.
- The NeqSim MCP `runPipeline` and `runFlowAssurance` tools for the same calculations from an agent.

In Python these are reached through `from neqsim import jneqsim`. The companion
`neqsim-pipeline-profile-plot` skill runs them along a KP/depth route and returns the
per-station values this skill colours a route with.

## References

- Norwegian Offshore Directorate open data and FactMaps API: https://www.sodir.no/en/about-us/open-data/
- Norwegian Licence for Open Government Data (NLOD 2.0): https://data.norge.no/nlod/en/2.0
- EMODnet web services: https://emodnet.ec.europa.eu/en/emodnet-web-service-documentation
- EMODnet terms of use (CC BY 4.0): https://emodnet.ec.europa.eu/en/terms-use-emodnet-online-services-data-and-data-products
- folium: https://python-visualization.github.io/folium/ ; OpenStreetMap copyright: https://www.openstreetmap.org/copyright
- GeoJSON: RFC 7946.
- Related community skills: `neqsim-pipeline-profile-plot`, `neqsim-pipe-route-profile`,
  `neqsim-bathymetry-profile-screening`, `neqsim-field-layout-import`, `neqsim-norwegian-continental-shelf-data`.
