# Original PS2 boot intro: local feasibility audit

The RE4 launcher currently loads SLUS_211.34 directly. It does not execute the
BIOS reset vector, OSDSYS or PS2LOGO. No original intro has been added yet.

The local BIOS inventory in
`artifacts/research/20261008/bios-intro-inventory.json` validates ROMDIR offsets
and records four 4 MiB BIOS images, their hashes and boot modules. Each contains
OSDSYS and PS2LOGO as ELF programs. The SCPH-39001 NTSC-U image has been used for
local analysis to match the region of this RE4 release. Its original BIOS and
the game files were not modified. Extracted local copies and their provenance
are kept under `artifacts/research/20261008/bios-intro/`.

These are distinct programs: OSDSYS presents the system startup/browser;
PS2LOGO is the disc launch program. Neither is a video file that can simply be
played before the game. The local reference `resources/09-ps2tek.md` describes
ROMDIR and the EELOAD/OSDSYS boot sequence.

Initial static analysis found 596 function candidates in PS2LOGO, with 96.08%
of its executable body bytes assigned to candidates. OSDSYS exposes a small
3,324-byte executable wrapper with `Expand` routines and a much larger data
payload; analysis of that wrapper found 21 candidates and 37.91% coverage.
The expanded program still needs investigation. These percentages measure
static candidate coverage, not intro completion, instruction correctness or
the amount of runtime work implemented. Both ELF entry points are 0x00100008,
demonstrating why selecting a separate function set is necessary.

The runtime ROM device currently supplies a base ROMVER file and optional
registered profiles. It does not automatically mount these BIOS images. The
runner's generated function set belongs to RE4, so loading another ELF alone
does not supply native implementations for its instructions.

Implementation order:

1. Audit both boot ELFs for executable coverage, relocations, syscall/import
   dependencies and expected ROM files using separate analysis outputs.
2. Add validated, local BIOS mounting and a separate boot function set. Boot
   addresses must not silently dispatch to RE4 functions at matching addresses.
3. Implement the boot programs' measured missing hardware/services and their
   transition into the game, including kernel/IOP reset and lifecycle handling.
4. Offer an optional original-intro launch mode; retain direct launch for fast
   play. Verify the transition repeatedly with physical input and unchanged game
   files. Display and audio must come from the original programs.

No fabricated logo animation, downloaded BIOS or fixed startup delay is used.
This audit establishes that source programs exist locally, not that boot works.
