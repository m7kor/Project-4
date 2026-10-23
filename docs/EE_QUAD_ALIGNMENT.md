# R5900 LQ/SQ address alignment

The recompiler previously used the effective address verbatim for LQ and
SQ. These instructions silently clear its low four bits. Both dynamic
effective-address expressions and resolved constant memory hints now align
after 32-bit address addition. Scalar LD/SD semantics are unchanged.

Primary reference: pinned PCSX2 `646df006a4688063e56c0826e7ea4b8bb0c112c4`,
`pcsx2/R5900OpcodeImpl.cpp`, LQ/SQ implementations. The locally verified
archive supplied the reference; the web fetch was unavailable. The copy
under `artifacts/research/20261007/pcsx2-R5900OpcodeImpl.cpp` has SHA256
`6ae749a7e3a297a291f1844d2f96a17bf7c53a9c6f6f4ab4ddab27781a78c2b4`.

`python -m ps2l canary --quad-align --out artifacts/canary-quad-align-after`
generates a redistributable EE ELF, recompiles it, compiles actual generated
C++, and executes sixteen load/store alignment combinations. It verifies
every byte of source, destination, and surrounding RAM, plus return PC.
The previous recompiler failed with 320 differing bytes; the corrected one
passes with zero. Reports and executable hashes are in
`artifacts/canary-quad-align-before/report.json` and
`artifacts/canary-quad-align-after/report.json`. This executable probe covers
constant addresses. The extended executable probe at
`artifacts/canary-quad-align-dynamic/report.json` also executes sixteen
dynamic address pairs with negative displacement and checks surrounding
memory after each invocation. Its unused MMIO link guards abort if called;
the probe covers ordinary RAM only. C++ regression checks additionally cover dynamic
expressions, negative displacement, all constant low-nibble values, and
the absence of the quadword mask on scalar LD.

Verification: `artifacts/verification/quad-align-final.json`, 470/470 C++
tests, 99/99 Python tests, and three tool self-checks. This is not a game
compatibility certificate. RE4 sources were regenerated with the corrected
recompiler, retaining original game files and existing configuration.
The runner rebuild is recorded in
`artifacts/verification/build-re4-quad-align.log`; its effect on actual
game rendering requires a completed build and a new runtime capture.

The runner rebuild completed successfully in 341.9 seconds. Actual run
`20261007T171932Z-9c54dd46` ended at the 181.579-second observation limit,
with 81 decoded frames, 34 nonblack, and no faults matched by the detector.
The captured font indices, loaded CLUT, and decoded RGBA bytes are identical
to the earlier capture: the alignment fix did not resolve this observed
palette defect. Evidence: `artifacts/research/20261007/quad-align-game-comparison.json`.
All eight extracted game files still match their prior local audit hashes:
`artifacts/research/20261007/game-file-preservation-quad-align.json`.

Regeneration still reports the two already documented unhandled words at
0x80075300 and 0x80076720. See RE4_GAME_FILE_AUDIT.md; no exception or content
was removed to conceal them. A generated-file hash inventory was collected
concurrently with regeneration and explicitly labeled as such. It must not
be used as an authoritative before/after snapshot.
