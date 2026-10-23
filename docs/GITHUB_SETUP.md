# Project-4 source distribution

Prepared on 2026-10-23 from the Lodestone workspace. This repository contains
the modified PS2Recomp core as regular source files, the Python tools and tests,
profiles, project documentation, adapters, and selected dependency sources.
`SOURCE_SNAPSHOT.json` records source hashes and upstream revisions.

## What is local only

Game discs, extracted game files, BIOS, saves, executable packages, build output,
generated EE/native game code and captured VU1 microprogram tables are excluded.
Historical research checkouts, logs and diagnostic captures are also excluded.
Links in older reports may refer to those local files. This is a development
source repository; the game is still in development, not a finished release.

The VU1 generated include ships a small fallback which selects the existing
interpreter. It contains no captured game program. The optimized table used by
the original workspace is deliberately local; recreate it from your own
captures with `ps2x_vu1_codegen` and the documented block-generation tools.
The published fallback has not been validated in a fresh native build.

## Start here

On Windows, install Git, Python 3.10+, Visual Studio C++ build tools and Windows
SDK, LLVM/clang-cl, CMake and Ninja. Python 3.10 additionally needs `tomli`.

```powershell
git -c core.longpaths=true clone https://github.com/m7kor/Project-4.git
cd Project-4
python -m unittest discover -s tests
python -m ps2l status
```

Use an x64 Visual Studio developer shell for native builds. Read `01-BUILD.md`
and `INCREMENTAL_BUILD.md`. The `core/` directory here already includes the
project changes: do not replace it with a fresh upstream clone. Dependencies
under `core/deps/` are obtained by CMake; selected sources under `dependencies/`
are included directly, preserving their license notices.

Provide your own RE4 USA SLUS-211.34 disc extraction under
`game/Resident Evil 4 (USA)/`. Verify it with the supplied profile, then follow
the analysis/recompilation pipeline and native module generation instructions
in the existing documentation before building the game runner. The default
native-module path is `recomp/native/SLUS_211.34/`; it is intentionally absent
until generated locally. Historical absolute paths and prebuilt-library settings
must be adapted to the new machine. No clean native build is claimed here.

The launch scripts in the root expect the separately assembled local
`Resident Evil 4/` package. That executable package is not in this repository.

## Licenses

The PS2Recomp core retains `core/LICENSE` (GPL v3). Other components retain
their own licenses, including paraLLEl-GS, Tracy, PCSX2 and the runtime-library
sources. See those files and the provenance manifest before redistributing a
combined binary. No rights to the original game or BIOS are granted.
