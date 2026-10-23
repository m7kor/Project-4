# Local paraLLEl-GS correction

Dependency: https://github.com/Arntzen-Software/parallel-gs
Pinned revision: `cc6184af7e0c03da603045ca371ffa5dae9b0655`.
Original source retains its LGPL-3.0+ notices and contributor credits.

`gif-fragment-bounds.patch` preserves our correction to the optimized GIF
reader. It counts only remaining payload qwords after the current tag, and
uses the general reader until a complete optimized loop is available.

`texture-page-span.patch` prevents unsigned underflow when a texture block
span crosses the previous modulo-32 boundary. It bounds mask iteration by
the exact swizzle period on each axis while preserving the union of touched
blocks and existing page/straddle dimensions. An optional bounded trace
records the first eight spans affected by the previous calculation.
Keep this patch when refreshing the dependency; review whether upstream
already includes an equivalent correction before applying it again.

Regression: set both `PS2X_TEST_GPU_CONTINUATIONS=1` and`PS2X_GS_PRESERVE_CONTINUATIONS=1`. `ps2x_tests` uses the actual
Vulkan bridge and PACKED A+D packets fragmented across transfers on each of
PATH1/2/3, including independent interleaved FINISH and NREG=1 boundary cases.
This requires a supported Vulkan device. It is explicitly enabled so the
normal CPU test suite remains available on machines without that device.

The diagnostic strict mode preserves PACKED/REGLIST continuation instead of
resetting loop/reg at each transfer. Both corrections are documented in
`docs/FIVE_PATH_BATCH_20261014.md`; the test and game results distinguish
transport correctness from complete model and texture correctness.

Strict preservation is not the runtime default: v21/v22 exposed corrupt RE4
rendering and Vulkan device loss. The established runtime packet compatibility
was restored pending producer/ordering investigation. Keep the reader and
page-span corrections; do not treat the diagnostic mode as a game fix.
