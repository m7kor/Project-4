# Observed dispatch entry audit

`mapcheck` establishes static branch coverage within mapped code. A PC inside a mapped function can still be absent from the generated dispatch table. RE4 demonstrated this at `0x299178`, inside the owner starting at `0x299168`: the guest calls the interior prologue, and executing the earlier stack adjustments would be wrong.

`entrycheck` reads missing-target evidence from a native capture or a text trace, the ELF, CSV map, and current generated registration source. It derives dense addresses from the base and slot index and rejects disagreement with their address annotations. It also reads sparse entries, checks the selected body extent, and requires both a resume case and its label when the dispatch address is inside a body. Missing trace evidence does not pass. For a capture directory, the captured ELF hash must match the ELF being audited.

Example:

```powershell
python -m ps2l entrycheck 'game/Resident Evil 4 (USA)/SLUS_211.34' analysis/functions.csv artifacts/runs/20261006T142429Z-461d58c6 recomp/generated/SLUS_211.34 --out artifacts/entrycheck/latest.json
```

Add `--entry-trace <capture>` to `verify` with `--elf` and `--function-map` to run the same gate. `--generated` selects a different generated source directory.

The current source audit confirms dispatch entries for `0x299178` and `0x2C0028` in `artifacts/tool-audit/20261006/entrycheck-current-targets.json`. Six regression tests cover interior targets, absent labels, wrong owners, missing or invalid evidence, table/address inconsistency, sparse-count mismatch and a stale capture ELF identity. Combined pipeline verification passes in `verify-observed-entries.json`.

This checks the current generated sources, not the executable that produced the historical fault. Registration does not establish correct boundaries or successful gameplay. Copied runtime code outside the ELF requires separate source evidence; this tool reports it as outside its ELF-code scope. A freshly built native run remains the decisive next check.
