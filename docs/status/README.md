# Gameplay and hardware status

As of **27 October 2026**. The [SVG map](progress.svg) and [machine-readable data](data.json) describe scoped evidence. They do not measure overall port completion.

| Component | Current state | Evidence | Remaining gap |
|---|---|---|---|
| EE / R5900 | Static recompilation | Integer semantics / malformed ELF tests | Broader campaign instruction coverage |
| MMI + FPU | Implemented, scoped tests | Translation and arithmetic regressions | Independent hardware edge-case evidence |
| VU0 | Runtime implementation | Shared helpers and unit-test coverage | More captured real-workload equivalence |
| VU1 | Primary performance bottleneck | 3,200 snapshots; 964 + 1,024 commands | Sustained real-time performance |
| VU pipeline | Reference semantics retained | Budgets, flags, queues and continuation | Low-overhead candidate attribution |
| VIF0 / VIF1 | Fast paths retained | VIF replay and payload-bound tests | Wider interleaved workload coverage |
| GIF + XGKICK | Packet paths exercised | Ordered GIF / full-state comparisons | Independent timing edge cases |
| GS / paraLLEl-GS | Existing renderer retained | 37 matched guest-tagged RGBA frames | Wider scenes and frame-pacing proof |
| DMAC + SPR | Narrow replay coverage | Chains, payload bounds and DMA tests | More channels / independent timing |
| IOP + SIF | Services and replay | Protocol / ordering regression gates | Broader RPC and scheduler workloads |
| IPU / movies | Intro path demonstrated | Historical real-game intro observations | Longer video and AV-sync validation |
| SPU2 / audio | PCM agrees; underruns remain | 5,570,686 common stereo frames equal | Speaker output and AV synchronization |
| Disc / streaming | Read-only original assets | Resource requests and room loading | More rooms and completion behavior |
| Controllers | Movement / aiming / shooting | Verified input and real observations | Lossless same-tick event replay |
| Memory cards | Earlier save / restart / reload | Isolated campaign card validation | New candidate progress-save acceptance |
| Timing / scheduler | Measured below real time | Seven alternating scene A/B pairs | CPU / GPU wait attribution and pacing |
| Dynamic modules | Existing loader reused | Gameplay and IOP diagnostics | More events and module lifecycles |
| External quicksave | Not implemented | Card backup is not a savestate | Restorable complete-state contract |

## Performance and validation contract

One fixed RE4 scene, seven alternating primary A/B pairs: median reference speed **0.205848x**, candidate **0.215486x**; median paired gain **4.9357%**. These are different statistics. Descriptive bootstrap interval for the paired median: 4.248Ã¢â‚¬â€œ5.868%; conservative endpoint-bracket median bounds: 0.173Ã¢â‚¬â€œ10.699%. Individual bounds for two pairs cross zero. The replaced fourth pair was preregistered after an observer failure, with the original retained. No whole-campaign or real-time performance claim.

Reference game SHA-256: `fa528081c83a6ef3c54d050c4a103d5527afb99e708987e2640d462a32e08f53`.
Candidate SHA-256: `55b31f4f2470c06ebcd3f39cf11f223bcefb644efa6a10707d2e1f7a1103f87e`.
Protected accepted runner: `e17998c7099f3bff2892529d7726836d9689b9af1d6cd091bfa5b29c9a88542a`.

The small prototype force-inlines five unchanged VU helper bodies. It does not change arithmetic, retirement scheduling, flags, generated block coverage, or renderer. The candidate remains a separate experimental build. The public interpreter fallback is not the game-derived optimized table used in the private measurements; a public clean native build and equal public-fallback performance are not claimed.

## Gameplay limits

- Fresh human room transition 0x100Ã¢â€ â€™0x101: 677 stable observations; movement continued. Later room transition and village combat are not independently accepted.
- Backing ammunition 5Ã¢â€ â€™4Ã¢â€ â€™3Ã¢â€ â€™3 agreed in both runners. Historical HUD anomaly remains open.
- Earlier isolated campaign save/restart/reload was verified. No new progress-save acceptance was performed for the latest candidate. Arbitrary-location external quicksave is not implemented.
- 37 guest-tagged frames matched; no matching capture keys in the aim/inventory windows. This is not full VRAM or whole-scene coverage.
- 5,570,686 common committed stereo PCM frames matched. Hard-stop WAV tails were excluded. Speaker playback, host timing and AV sync remain unverified; underruns remain.

See the [test ledger](../testing/RESULTS.md) and [detailed lab report](../compatibility/reports/RE4_HOST_BOUNDARY_ENGINEERING_AR.md). Older reports retain the evidence and limits of their own revision.

## Diagram style and regeneration

The GitHub-dark treemap uses green, hatched yellow and gray. Library cells are decorative service groups, not counted SDK functions. Component areas are layout choices, not completion weights. No SDK completion percentage has been established.

Regenerate from the repository root with `python compatibility/tools/generate_github_status_map.py .`.

### Editable SVG

The SVG contains native text, rectangles, paths, patterns and named component groups. It has no embedded raster art, scripts or external fonts. Edit it directly in Inkscape or a text editor. For repeatable changes edit `docs/status/map.json`: each tile lists x,y,width,height,label,status,evidence. Status is `ok`, `partial` or `pending`; palette colors are editable. Run the regeneration command above. `data.json` retains the detailed evidence ledger; update both when the evidence changes.
