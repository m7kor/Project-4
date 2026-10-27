# VU1 safe-normal classification experiment

This opt-in experiment batches the existing FMAC exponent-2-through-253
normal-result shortcut using integer SIMD classification. It does not change
floating-point arithmetic, rounding, flag retirement, pipeline scheduling,
Q/P, or XGKICK. Any selected exceptional/boundary lane falls back to the
original implementation. `PS2X_VU1_FMAC_CLASSIFY=1` enables it; default is off.

Local Windows compatibility-lab validation (2026-10-26):

- 635 C++ tests passed against the private Phase4-correctness runtime plus this
  narrow change; the public source clone is not claimed to have a clean CI build.
- 1,048,576 independent helper checks each in SSE2 and forced scalar modes;
  all-bit predicate proof, 4096 mask/table combinations, sign-pack mutation
  detection, and focused ASan/UBSan helper checks passed.
- Full register, memory, pipeline, flags, cycle and GIF comparisons passed:
  964 recorded VU commands, 800 captured states with several execution budgets,
  all 3200 captured snapshots, and 512 deterministic synthetic queue sets.
  These establish runtime equivalence, not independent PS2 hardware accuracy.
- Seven alternating isolated VU pairs: median cost reduction 0.7869%.
- Seven alternating real-game pairs: median speeds 0.203193x versus 0.203090x;
  paired gains ranged -1.6315% to +1.2354%. Whole-game improvement is inconclusive.

The experiment remains disabled and is not approved for a user package.
Against the current Phase4 reference, 35 counter-matched frames were identical.
Against the historical approved executable, 58 of 59 counter-matched frames
were identical; one movement-animation frame differed. Equal EE/presentation
counters alone do not prove equal complete guest state. The cause is unresolved
and this comparison does not pass a strict graphics release gate.
Two earlier retirement-scheduler prototypes were slower and are excluded.
The procedural `ps2x_fmac_classify_witness` target contains no game fixtures.
Private game captures, generated game source, binaries and saves are excluded.
