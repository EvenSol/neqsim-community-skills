# neqsim-well-trajectory-anticollision

Educational, screening-level 3D well trajectory planning and anti-collision for NeqSim community examples.

The skill provides:

- minimum curvature;
- curve-hold from a kick-off or a sidetrack tie-in;
- a reduced systematic MWD uncertainty model;
- the ISCWSA separation-factor scan against offset wellbores;
- parent-bore exit tracking;
- a slot-occupancy check;
- a target pull-back search.

See [SKILL.md](SKILL.md) for method, inputs, validation and limitations.

```powershell
<python> -m pip install -e .[test]
<python> -m pytest
<python> examples/synthetic_template_example.py
```

All example data are synthetic. Results are screening values and are not an anti-collision approval:
the operator's SF rule and the official directional-planning system govern.
