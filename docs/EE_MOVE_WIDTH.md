# EE conditional moves preserve the upper half

The scalar MOVZ and MOVN translators previously used SET_GPR_VEC and copied
all 128 bits from the source. The actual scalar operation changes only the
low 64 bits and leaves the destination's upper half intact. The condition
also reads the low 64 bits. This matches the primary
[PCSX2 R5900 MOVZ/MOVN implementation](https://github.com/PCSX2/pcsx2/blob/master/pcsx2/R5900OpcodeImpl.cpp).
The translator now uses SET_GPR_U64/GPR_U64 for these two instructions.

`python -m ps2l canary --move64` generates a redistributable synthetic EE
ELF, recompiles it with the actual recompiler, compiles the emitted C++, and
executes it against a real R5900Context. Ten instruction cases include taken
and untaken moves, a condition with low32 zero but low64 nonzero, a zero
source, self-aliasing and attempts to write register zero. Distinct upper
sentinels make full-vector copies observable.

The executable before the fix returns failure with `moves_ok=0` despite
correct v0 and return PC. After rebuilding the recompiler it passes with
`moves_ok=1`. Evidence is in `artifacts/canary-move64-before/report.json`
and `artifacts/canary-move64-after/report.json`, plus their execution logs.
The gate is included in `verify --canary`; all five native canaries and
the 80 Python tests passed in `artifacts/tool-audit/20261006/verify-move64.json`.

RE4 was regenerated: 1,150 conditional scalar moves in 630 function files,
with zero remaining conditional full-vector moves matching the old emitted
form (`generated-move64-summary.json`). Building and running that actual
game remains a separate requirement. The standalone regression does not
prove that this bug causes the black screen or that the game is playable.
No original game file was modified by the fix.

The corrected game and test executable built successfully in 203.0 seconds
with 633 build tasks. The rebuilt 458-test C++ suite passed, together with
the profile, function-map and observed-entry gates in `verify-move64-core.json`.
The actual game run `20261006T155739Z-beb8e2fc` finished after 180.203
seconds at the configured timeout, with no faults matching the detector.
All 84 captured images were black. The instruction correction is proven,
but it did not resolve the black screen in this run. Evidence:
`artifacts/tool-audit/20261006/run-move64-summary.json`. The runner hash is
`1672635ced680532b111bfc74342f6dfbd8989ce5db6fee80f900f727a1fcb6a`.
