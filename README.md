# cross-sec-evals

Evaluation scripts for the **Cross-Sec** project. The repo evaluates solved
**PyPSA-AT** networks exploratory [marimo](https://marimo.io) notebooks.

## Contents

| File | Purpose |
|---|---|
| `network-investigation.py` | marimo notebook for exploring a solved network |
| `coupling-variables.py` | marimo notebook deriving the Cross-Sec coupling variables, one cell per variable |
| `coupling-variables-plan.md` | Scope, decisions and method per coupling variable |
| `resources/` | Local model runs and reference data (not tracked in git) |

## Setup

Requires [pixi](https://pixi.sh). Dependencies (`pypsa`, `pandas`, `marimo`) are defined in `pixi.toml`.

```bash
pixi install
pixi run marimo edit coupling-variables.py   # interactive
pixi run marimo run coupling-variables.py    # read-only app
```

## Conventions

- Network files (`*.nc`) and results are not committed.
- all pixi files are commited for consistent setups across machines.
