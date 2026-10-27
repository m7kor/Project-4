# All tests: commands, inputs and evidence

The [complete source index](SOURCE_INDEX.md) lists Project-4, compatibility-lab and preserved engine test sources. [RESULTS.md](RESULTS.md) records executed results separately from available source. A public checkout does not include private workloads or accepted executables.

## Project-4 Python

From the repository root:

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests
```

Tests with missing optional dependencies or local inputs may skip or fail; read the actual output. No full public clean-checkout pass is asserted by historical local results.

## Native tests

`core/ps2xTest/` and `core/ps2xIOP/tests/` contain the native source suites. Use the x64 developer shell and the build instructions in [01-BUILD.md](../01-BUILD.md). Tests must be bound to the exact source revision and newly built executable identity. Duplicate engine/source archives are held out of this publication; historical local reports remain revision-specific.

## Laboratory command groups

Run from `compatibility/` so Python resolves the laboratory tools rather than the root Project-4 tools:

```powershell
cd compatibility
python tools/lab_regression.py fast --plan
python tools/lab_regression.py vu --plan
python tools/lab_regression.py ee --plan
python tools/lab_regression.py graphics --plan
python tools/lab_regression.py audio --plan
python tools/lab_regression.py hardware --plan
python tools/lab_regression.py dma --plan
python tools/lab_regression.py iop --plan
python tools/lab_regression.py integration --plan
python tools/lab_regression.py full --plan
python tools/lab_regression.py auto --changed engines/project4/ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp --plan
```

The duplicate engine tree is held out of this publication. These commands are preserved historical laboratory interfaces. Restore/configure the corresponding local source tree before actual execution. Remove `--plan` only after supplying the required private binaries, source manifests and fixtures. Use `--candidate-dir`, `--baseline-dir`, `--vu-source`, `--project4-recompiler` and `--integration-spec` as appropriate. `integration --allow-game` requires an explicit validated spec and isolated cards. An old executable is never evidence for newly edited source. Running `--help` or `--plan` validates command selection, not hardware correctness.

The existing commands do not automatically download or reconstruct private inputs. Paths to prior `lab/` and `artifacts/` experiments are retained for provenance and need the corresponding local evidence. Some legacy diagnostic scripts have machine-specific paths. These are source archives, not a turnkey recreation of every old private experiment.

## Replay and negative controls

Sources include VU full-state equivalence, VIF, narrow DMA and IOP/SIF replay, input quality checks, source/binary identity, malformed ELF and integer-semantics tests, synthetic mutation checks, graphics and PCM analysis. Distinguish runtime agreement, recorded RE4 agreement and independent PS2 hardware evidence.

Do not change `.expected` files to create passes. Do not treat incomplete captures, missing fixtures, process liveness, or a successful compile as gameplay acceptance. Preserve failures and skipped/unavailable results.
