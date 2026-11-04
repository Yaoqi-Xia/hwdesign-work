# Float32 scale and offset

`prompt.md` is Part 1; `results.md` is Part 2. This folder stops at C
simulation as required. The common source files use `design.py` to select
the scale/offset implementation; the preprocessor removes FIR logic.

With Python 3.12, editable Waveflow and licensed Vitis on PATH:

```bash
python3.12 build.py --through csim
```

The build generates Waveflow stream support and message headers, checks
the hand examples, creates vectors, runs Vitis C simulation and compares
all actual beats/status with Python. Read the per-scenario evidence in
`evidence/csim_comparison.json`, `csim_status.csv` and `csim_beats.csv`.
No synthesis, RTL co-simulation or performance claims are made for this
folder. `build.py` rejects requests to run those stages here.
