# Reviewed public source publication

The user requested a public archive of all redistributable sources/tests/docs from Project-4 and the compatibility lab, excluding game-derived and private data. After automatic review held additional source categories, the user explicitly requested removing problematic files. This update publishes the remaining reviewed subset; the complete original local archive is preserved separately.

## Included

- Existing public repository history, dependencies, licenses, Project-4 Python tools and tests.
- Reviewed public `core/` safety fixes and disabled experimental FMAC code; no new executable promotion.
- Laboratory Python tools, synthetic test/harness sources, reference Python helpers and source build helpers.
- Engineering reports in `docs/compatibility/reports/`, indexed documentation and test results.
- English main README and a native editable GitHub-style SVG map, JSON layout/palette and SVG generator.
- Unchanged55 hardware-reference text outputs, with source revision clearly separated from candidate verification.

## Held out of this update

Duplicate engine trees and original/pinned source archives, duplicated BIOS-analysis helpers, and source patch bundles. These local files were not deleted. They are omitted from this publication index and inventory. The branch does not indirectly embed those held files as encoded attachments or patches. Source archives already present in the old public baseline are not purged or rewritten.

Game assets/discs, BIOS images, proprietary executables/modules, generated EE/native/VU game programs, RAM/VRAM captures, raw audio/screenshots, saves/cards, compiled binaries/build caches/logs and credentials remain excluded. Public interpreter fallback code already in the baseline is retained; no captured game microprogram table is added.

## Reproducibility limits

Some laboratory tools retain paths to prior private experiments, source snapshots or local fixtures. Missing inputs are unavailable checks, not passes. Historical local test results and game performance are scoped to the identities in the reports, not a claim that a public checkout reproduces every private experiment. No fresh public native game build is certified. The latest635/635 and VU equivalence results remain local-candidate evidence; the publication Python suite was actually run403 cases with7 skipped.

`SOURCE_INVENTORY.json` records only files included in the reviewed publication selection. The excluded local source copies remain recoverable from the preserved local commit/archive; they are not uploaded in this branch. No automatic merge, runner promotion, upstream push or original-save modification.
