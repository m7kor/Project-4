# EE set-less-than comparison width

## Observed game failure

The RE4 capture `artifacts/runs/20261006T134542Z-273a47e0/report.json` remained at PC `0x177C40` after the missing indirect entry `0x2A9448` had been added. The run timed out after 121.609 seconds, with GS writes still zero. No matched fault does not establish successful execution.

`FUN_00177BC0` builds the unsigned threshold `0x0FFFFFFFFFFFFFFF` using a sign-extended `addiu -1` followed by `dsrl 4`. The loop doubles a 64-bit value and uses `sltu` to decide whether it exceeds that threshold. The previous emitter compared only the low 32 bits. Truncating the threshold produces `0xFFFFFFFF`, which cannot be less than any unsigned 32-bit operand; the loop therefore cannot take its exit on that comparison.

## Corrected contract

SLT and SLTI compare signed low 64-bit operands; SLTU and SLTIU compare unsigned low 64-bit operands. The immediate is sign-extended before either immediate comparison. Signed formatting matters: `inst.simmediate` is stored unsigned, so emitting it directly would turn immediate -1 into positive 4294967295 even with a subsequent cast to int64_t.

Independent reference: [PCSX2 R5900 opcode implementation](https://github.com/PCSX2/pcsx2/blob/master/pcsx2/R5900OpcodeImpl.cpp), functions SLT, SLTU, SLTI and SLTIU. This project uses its own generated expressions; the reference is used to verify the operand contract.

## Executable evidence

`python -m ps2l canary --compare64` generates a redistributable EE ELF, recompiles it to C++, builds and runs the actual generated functions. It covers 15 comparison cases, including contradictory upper/lower words and negative immediate values. A finite unrolled probe exercises the game's threshold pattern: an initial `2^32` exceeds `2^60-1` after 28 doubling steps.

Before the comparison correction, the earlier probe returned `v0=2117 slots=32` rather than `v0=17 slots=28`. The first correction exposed a second problem: immediate -1 formatting still caused failures (`v0=217 slots=28`). With signed immediate formatting corrected, the current 15-case probe returns `v0=17 slots=28 pc=1193046`. Its report is `artifacts/canary-compare64/report.json`; the combined verification report is `artifacts/tool-audit/20261006/verify-compare64.json`.

The regenerated game function now emits `GPR_U64` comparisons at `0x177C28` and `0x177C4C`. The rebuilt native capture `artifacts/runs/20261006T140632Z-80828e11/report.json` verifies return from the formerly stuck call: source `0x2B9A34`, target `0x177BC0`, leave PC `0x2B9A3C`. Execution then reaches a later missing indirect target `0x1B36F0`. The run still times out after 120.203 seconds, with zero GS writes and 56 black frames. These results establish removal of the comparison-loop obstacle, not graphics, audio, saving, or gameplay compatibility. Original game assets were not modified.
