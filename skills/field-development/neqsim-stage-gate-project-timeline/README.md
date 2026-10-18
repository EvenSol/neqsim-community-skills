# Stage-Gate Project Timeline

Educational, dependency-free timelines for field-development screening: a
prospect's stage gates (exploration, appraisal, DG1-DG3, execution, first oil at
a turnaround), a host modification's study/concept/execution with ASAP or
just-in-time scheduling and cost placed in the phases that incur it, and a
host life-extension decision deadline. `portfolio_plan` combines them into
Gantt rows, a capex calendar and milestones; `plot_gantt` draws it.

Use it so that an optimiser never starts production, counts new capacity or
runs a host past its programme before the project can exist. See `SKILL.md`
for the method and the Snorre A tie-in living-task pattern that uses it.

## Quick Start

```bash
pip install -e .
python examples/basic_timeline.py
pytest
```

```python
from stage_gate_project_timeline import prospect_timeline, project_timeline
prospect_timeline({"name": "P", "status": "undrilled"}, 2026)["first_production_year"]   # 2033
project_timeline({"id": "x", "capex_musd": 60}, 2026, needed_by=2036)["available_year"]  # 2035
```
