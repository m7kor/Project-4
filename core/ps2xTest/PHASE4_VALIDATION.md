# Phase 4 integration validation — 2026-10-26

This change fixes signed-overflow UB in emitted ADDI/SUB/DADD/DADDI/DSUB/DADDIU,
including ADDI's exception when its destination is zero. ADD already used a
safe widened intermediate. The corrected emitter produces unsigned intermediates
and sign-bit overflow tests; legacy runtime macros are unchanged. Previously
generated output must be regenerated; updating a runtime alone is insufficient.

The ELF parser now rejects unreadable symbol/relocation table data before ELFIO
accessors. Valid symbols remain available when a different relocation section
is malformed. The DMAC change bounds logical GIF/VIF gathered payloads at 256 MiB
before appending. Equality is allowed, oversize fails explicitly without a partial
packet or successful completion. This is a host resource policy, not a PS2 limit.
The existing exact cycle detector is retained, not introduced by this patch.

## Tests and provenance

Locally built Windows clang-cl/clang++ integration, with the existing private
development runtime dependencies:

- C++: 635/635. Two added cases cover ADDI-to-zero emission and an ELF32 file
  retaining valid symbols with unreadable relocation data.
- Actual emitter output: 952 value/exception-suppression checks under UBSan.
  Six old emitted operation implementations triggered signed-overflow diagnostics.
  The procedural shim does not prove the complete EE exception state or EPC/BD.
- Eight malformed/valid ELF fixtures: no candidate crash; two old-parser crashes.
- Four procedural DMA regressions: repeated CALL/REF/RET, cyclic NEXT, exact-cap
  success, oversize failure without packet/completion.
- Existing offline VU command, snapshot-budget, VIF, DMA and IOP replays passed.
  The VU implementation itself is unchanged by this change.
- Upstream integer bit-vector model: 29 checks including negative controls;
  model agreement is separate from executing emitted C++.

These local integration results do not assert that a fresh public checkout or
every platform has passed CI. New standalone CTest targets are included for that
validation. The integer CTest is enabled for non-MSVC Clang/GCC with Python;
Windows can run its script manually with clang++ in the developer environment.

Zmbor main audited: ec4a32de4d77b41990591d87a36f475e7725099b. Its engine/build
sources match Phase 7 c7e59604a0d13e51e61e99318196380e2e88ae2d.
A fresh execution of hash-checked previously built clean Phase 7 binaries gave
551/551 C++ and 53/55 hardware exact matches; sqrt/EFU mismatches remain.
Those are reference-engine results, not hardware validation of this candidate.
Hardware expected outputs were not changed.

## Release limits

Private regenerated EE and default native modules were used only locally.
No game data, extracted/generated game source, captures, save files or binaries
are included here. Optional legacy partial-native diagnostic modes remain outside
acceptance. No VU optimization or whole-game performance improvement is claimed.
Full campaign, post-transition combat and fresh campaign save/reload remain open
acceptance gates. The accepted runner is preserved; this is a draft integration.
