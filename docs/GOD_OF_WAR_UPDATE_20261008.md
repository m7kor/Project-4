# God of War update audit — 2026-10-08

Reviewed public upstream at pinned revision `5653f2b23cf179b753dcc77bdbc3e4cdfe257d80`
(committer timestamp 2026-10-08 03:45:45 UTC). Previous local survey was
`1bdcd72348f8f0f0e570ec2e7b4c54ec7c3ce813`: 27 commits and 52 changed files.
All changed files were downloaded as reference material with SHA256 records;
no external scripts were executed and external agent instructions are not task instructions.

Source: https://github.com/KIexster/god-of-war-recomp/commit/5653f2b23cf179b753dcc77bdbc3e4cdfe257d80
Audit: `artifacts/research/20261008/gow-update/{comparison,manifest,audit}.json`.

## Integrated correction

The current local PACKED XYZ2/XYZ3 frontend converted 32-bit depth to float,
then stored it in a double vertex. Depths above float integer precision had
already lost bits; UINT32_MAX could round to 2^32. Both paths now convert
straight to double, matching the existing unpacked XYZ path.
The design is adapted from upstream `ps2recomp-gs-packed-depth.patch` (GPL-3.0).
No game assets, generated game function bodies or card data were modified.

The regression renders four depths (0x01000001, 0x80000001, 0xFFFFFF01,
0xFFFFFFFF) through native and generic complete PACKED packets and checks
actual Z32 VRAM plus the reference color. Before-fix verification failed.
The first imported test also attempted arbitrary byte fragmentation, which
our GS::processGIFPacket does not promise to accept: that part remained failing
after the depth fix. The final regression uses the supported complete-packet
contract. This is not evidence of fragmented frontend support; upstream's
streaming parser cannot be assumed present locally.

Final verification `artifacts/verification/gow-packed-depth-final.json`:
485/485 C++ tests, 103/103 Python tests and three tooling checks passed.
Runner build `gow-packed-depth-after-build.log` succeeded (157.0 seconds).
The bundle is refreshed with `tools/package_re4.py`, retaining destination
saves and checking all eight original game files against the preservation audit.
No RE4 gameplay image or speed improvement is claimed from the depth regression.

## Useful next integrations

| Update | Local implication | Required evidence |
|---|---|---|
| VU1 compiled C++ and direct register writes | Potential speed work; current queue timing must be preserved | Captured RE4 microprograms, final and interrupted/resumed state equivalence, cycle/PC/memory/flag checks; measure locally |
| VU1 sticky product flags | Upstream found status loss across microprograms | Preserve product sticky flags even without a current status reader; our current implementation already calculates them |
| Nearest/bilinear STQ and four-bit filter precision | Local CPU sampler differs and deserves a separate change | Procedural PCSX2 pixel references, negative/tiny coordinate boundaries, producer rounding controls |
| Triangle precision and color/depth target aliasing | Relevant to a GPU backend integration | Our active CPU architecture lacks upstream GPU files; adapt with backend-specific regressions |
| Region page tracking | Avoids conservative GPU texture hazards | MIN/MAX-only changes and regional repeat/clamp oracle cases |
| Feedback snapshots | Explicit upstream diagnostic experiment | Keep experimental; not a substitute for correct PS2 texture cache semantics |
| GS dump/replay and pixel layout tools | Strong approach for comparing rendering independently | Port local ABI deliberately and compare visible rows, not full padding buffers; external generated procedural references preferred |

Upstream performance figures belong to their captured God of War scene and
branch. Their latest sticky-flag fix explicitly requires remeasurement; neither
those figures nor passing upstream tests prove RE4 compatibility. Compiled
infrastructure alone also does not accelerate a game without generated and
linked local microprogram units.

## Memory card continuation

No memory-card implementation patch changed between the two surveyed revisions.
Their earlier documentation verifies save/load with a copied formatted PCSX2
card while formatting remains unverified; it is not a new verified fix for our
blank-card setup.

RE4 run `20261008T040205Z-edfe6ee8` used the packaged native executable for
150.187 seconds, reaching EE tick 857. Correct call filters watched Format,
its PollSema and SifCallRpc boundaries, with the static Format caller at
0x124D28. No selected EE call was observed; selected RPC recorded Init/GetInfo
only. Captures include the system-data creation prompt and later invisible text.
Thus the replay is not proven to reach Format and no failing Format return is
identified. Card hash remained unchanged. The earlier run used incorrect source
filters and must not be used as evidence of Format nonexecution.
See `artifacts/research/20261008/mc-format-client-observation.json`.
Next: trace system-data Open/Mkdir/GetInfo client calls and actual returned
format status before altering card protocol or assuming an erase/write failure.
