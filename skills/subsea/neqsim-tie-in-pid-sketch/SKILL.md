---
name: neqsim-tie-in-pid-sketch
calculation_basis: "screening"
version: "0.1.0"
description: "Conceptual P&ID sketches (SVG) of both ends of a new tie-in line - source platform end with pump, metering, pig launcher, ESDV and riser; landing end with riser, ESDV, pig receiver, sampling, pressure control, spectacle blind and tie-in to an existing header - plus a completeness check. USE WHEN: a tie-in or export concept needs a drawing of possible connection points and the isolation, pigging and metering philosophy before a controlled P&ID is made."
last_verified: "2026-10-20"
requires:
  python_packages: []
  java_packages: []
  env: []
  network: []
---

# Tie-in P&ID sketch

Draws a one-line conceptual P&ID for each end of a line. Existing plant is thin and dark, new scope is bold
and green, invented tags carry `*`. Built for the Martin Linge A to Oseberg A oil export concept.

## When to Use

- After `neqsim-tie-in-pipeline-concept` has chosen candidate landing points and a line size.
- To show where the line ties in, which isolation, pigging, metering and sampling it needs, and which options
  remain open (existing pump or new pump, which header, which riser slot).

Not for controlled P&IDs, HAZOP, or anything that is built from.

## Workflow

1. Read the real P&ID (STID) for the existing equipment at each end: name the export header, pump and battery
   limit valve. Pass the STID tag to the template (`existing_tag`, `header_tag`) and the element becomes
   `proposed=False`; leave it blank if you did not read it.
2. `pair_sketch(source, landing)` or call `source_end_oil_export` / `landing_end_oil_header` with options
   (`new_export_pump`, `with_booster`, `keep_old_route`). Build a custom `TieInEndSketch` for other layouts.
3. `sketch.validate()` must return an empty list or each finding must be explained in the report.
4. `render_svg(sketch)`, save to `figures/`, and convert to PNG for Word (for example with Edge or Inkscape).
5. List the open choices (the `options` block) as questions to the facility owners.

## Always state

Tags are proposals; routes of the main line are conceptual; capacity of the existing header, riser slot and
quality acceptance are not verified; the sketch is not a controlled document.

## Common mistakes

- Inventing STID tags. Use `proposed=True` (default) and keep the asterisk.
- Showing the landing as a single point. Keep the ESDV, pig receiver and spectacle blind: they are what makes the
  tie-in operable and isolable.
- Forgetting the old route. A blind towards the old export (FSO or tanker) is needed to isolate it safely.

## Related

`neqsim-tie-in-pipeline-concept`, `neqsim-pid-process-operations`.

