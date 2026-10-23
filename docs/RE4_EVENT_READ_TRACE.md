# RE4 event read and execution investigation — 2026-10-10

## Work gate continuity: closed 20261010T044310Z-90e4971c

Timeout124 after360.125s, last EE3144, no fault markers. The finalized trace has223 selected entries and15 RAM-change dispatcher rows; neither cap was reached. The final frame-16000.png was visually inspected and is grey.

Direct-tail wrappers2C3770 and2C3788 expose96 and113 input-feeding entries respectively. The last entries complete with v0=0; arguments include packet lengths such as0x7E2 and0x800. This proves calls and sampled arguments, not complete decoding. Work gateDE2144 reactivates after being cleared; the final recorded gate is1. StatusDE2148 changes0 ->1 ->2 in dispatcher samples, and requested stateDE214C is3 in later rows. Channel6/7 first two fields remain zero in the later recorded windows. Boundary sampling does not establish a unique writer or all intermediate states.

The earlier14-entry run20261010T043643Z-7960880c ended at360.141s/EE3190 without faults. Its inner-target probes missed direct-tail calls; it cannot establish a permanently inactive worker. Parser2C5450 yielded to2B27A0, and later feeding in the continuity run rules out treating that yield alone as a parser failure.

Evidence: movie-decoder-work-continuity-trace.json, movie-decoder-work-continuity-observation.json, movie-decoder-work-gate-observation.json and movie-work-gate-probe-coverage.json in artifacts/research/20261010.

Parser-completion run20261010T135207Z-90d65261 closed at360.172s/EE2535, timeout124, no faults. It recorded2 entries without reaching the cap:2C79D0 completed from2C6208 with a1=0x32000,a2=0,v0=0xF3800;2CDC90 completed from2CE8A8 with a0=DE55B8,v0=1. Both sampled status2/requested3/gate1. This proves entry in the DMA-control routine, not execution of every MMIO branch. FinalEE2535 is below replay events2700/3300, so complete fixture execution is not established. Evidence: movie-parser-completion-trace.json and movie-parser-completion-observation.json.

The sandboxed predecessor20261010T135004Z-f23aef94 exited0xC0000008 during window initialization, with zero guest state samples or frames; exclude it from decoder evidence. The successful retry entered guest execution outside isolation. Its watch wordsDE3448/DE344C andDE34BC/DE34C0 are not the intended input queue counters: correct counters areDE3438/DE343C andDE34AC/DE34B0, still covered by its64-byte memory windows. Do not mislabel them. Probe2D3BC8 may be hidden by the direct J from2CF148.

Corrected v2 run20261010T135953Z-9e458848/session16385 is closed: timeout124 after540.14s, EE3442, no faults. It again recorded only2 entries:2C79D0 and2CDC90; cap not reached. All four replay interval ends were reached according to replay_progress.py; logged matching button transitions were[True, True, True, True]. This does not prove action acceptance. Final frame-21000.png was visually inspected and is grey. Evidence: movie-parser-completion-v2-trace.json, movie-parser-completion-v2-observation.json and movie-parser-completion-v2-replay-audit.json. No game or build is live. The next investigation needs actual IPU MMIO/DMA command observations and service continuity; no causal runtime fix is claimed. User requested a comprehensive project inventory, now in progress.

Launcher configuration validation now rejects oversized/invalid selector lists before launch and records the used plan. Ten focused tests and the full177-test Python suite pass; see [TRACE_CONFIGURATION.md](TRACE_CONFIGURATION.md). The static parser/service audit matched411 unique instruction comment words in10 functions; the channel6/7 service slot2 maps to2D4C18/2C2B10. This establishes original word identity and static targets, not execution correctness. Evidence: movie-parser-service-original-word-audit.json. No new runtime patch or user-package replacement in this step. The sections below are historical.

## Corrected status probe, closed 20261010T042831Z-8a20a936

This run ended with timeout124 after360.094s, last EE3124, no fault markers.
There were only2 selected entries; the256-entry cap was not reached.
The final image `diagnostics/frame-16000.png` is grey, visually inspected.
No game or build remains live.

The explicitly sampled DE2140 window includes raw decoder status at+0x48.
At2CF160, actual a0 wasDE2100, status1, requested state+0x4C=3;
that function returned2. At2CF250, status was2, requested state3,
and the delivered buffer started with the original movie pack header.
2CF250 completed normally with v0=0. Both boundaries sampled work gate
raw+0x44=0. These are two boundaries, not continuous or final status observations.

Original2CF008 skips processing when work gate+0x44 is zero and clears it
before a processing pass. Original2CF250 tests flags at raw+A04+5*4 and
raw+A04+6*4, then combines callback progress values from indices6 and7
via2D3CC8/2D3CF8. Both sampled flags were1, but the combined progress
test returned0. The next probe isolates input delivery, work-gate
reactivation and these callback values. It must not force a ready state.

Evidence: `movie-decoder-status-trace.json`, `movie-decoder-status-observation.json`
and `movie-decoder-status-original-word-audit.json` in `artifacts/research/20261010`.
The audit matched594 unique instruction comment words in16 functions toELF;
it does not verify generated semantics. The next plan
`movie-decoder-work-gate-trace-plan.json` is prepared, not executed.

The earlier+0x48=2 claim was removed from the payload observation: its
64-byte DE2100 sample ended at+0x3F and the2 was actually at+0x38.

## Latest closed evidence: payload identity, not decoder completion

The current diagnostic runner is `36a30734427a624dd79876d0cb369645d582bd92a35c1abc1ca59a291007cd7c`.
The packaged executable and user card still match the previously recorded hashes.
No game or build remains live after these runs. Runner descriptions below are historical.

| Run | Result | Selected entries | Evidence |
| --- | --- | --- | --- |
| `20261010T040115Z-5201593f` | 124 /360.125s, EE3147, no fault markers |256, cap reached | File-pump guard changes0/1/2/3 and resets. File object words change; no byte identity established by this run. |
| `20261010T040852Z-e57ab0f0` |124 /360.14s, EE3105, no fault markers |6, cap not reached | Input parameter validation at2C3498 returns0. Samples of9A3E40 are zero at these early boundaries. Yielded2D0D38 calls are not failed returns. |
| `20261010T041537Z-1c4c561e` |124 /360.125s, EE3161, no fault markers |256, cap reached | Two2C3550 input-configuration entries and254 file-pump entries. Two distinct128-byte windows match the original SFD at relative0 and0xF3800. |

The source extent was independently verified against AFS entry192:
offset0x2A280800, length31791104. Both matching windows occur at the
same memory addresses9A3E40/9A3E80 at different trace boundaries. This
proves sampled byte delivery, not complete stream delivery or decoding.
Correction: the64-byte DE2100 snapshot does not include status at+0x48.
The observed2 is at+0x38 and cannot establish decoder status. The final
captured image is uniformly grey. The next trace explicitly samples
DE2140, including status+0x48, and decoder work boundaries.

Reports in `artifacts/research/20261010/`: `movie-file-pump-observation.json`,
`movie-decoder-input-observation.json`, `movie-payload-identity-observation.json`,
`movie-payload-identity-comparison.json`, and `movie-payload-source-entry.json`.
The new comparison tool passed7 tests and ran on actual traces;
see [TRACE_PAYLOAD_IDENTITY.md](TRACE_PAYLOAD_IDENTITY.md).
Earlier statements that payload delivery was unproved apply to their earlier runs.

The local user package retains the validated graphics runner
`cc1f10b3274f244bf5f3e2c6d62806386333ea3657ac758bf99a11d5b967d70e`.
The diagnostic runner has SHA
`f79216b8506564b93e9856765b22024a4c05756e9aa28b7c91f721452e073474`.
It adds only opt-in trace arming at a selected guest target; the build passed.
It has not replaced the packaged executable.

## Closed runs

`20261009T225204Z-23e7356c` timed out after 301.515 seconds, with no fault
markers and last EE field 4333. Its trace armed at target 0x206280 from
0x1189DA0 for `event/evd/r120s99.evd`. The 256-entry shared cap was reached:
only 29 entries were job notifications, while semaphore/scheduler calls
also consumed the budget. The corrected job-report tool now detects this.

`20261009T225803Z-33312c76` timed out after 300.109 seconds, with no fault
markers and last EE field 4379. Object 0x41C144 was polled through original
method table 0x31E6D8 (stride 8, signed adjustment at +0, target at +4):

| Type | Method | Observed transition |
| --- | --- | --- |
| 0 | 0x1B3770 | 0x40000001/type0/state0 → 0x40010001/type1/state0 |
| 1 | 0x1B3BE0 | states 0/1/2/3 → 0x44010001/type3/state0 |
| 3 | 0x1B4558 | yielded inside 0x16BEE0; this is not a failed return |

The wrapper at 0x1B1318 was later entered from 0x20619C and returned v0=1.
The trace then exhausted its cap mainly on 228 background entries at
0x1B6720 from 0x1B6018. This background path is in 0x1B5F60; it must not be
mistaken for a repeated invocation by the event reader at 0x1B5B00.
These observations show progress past the initial poll, but do not prove
payload correctness, completion of EvtReadExec or arrival at gameplay.

## Why file I/O and event execution must be separated

Original EvtReadExec at 0x206280 calls the read wrapper at 0x205F40 from
0x206374. A successful read then proceeds to event preparation including
0x2068D8 from 0x2064E0. Later it calls 0x205E38 from 0x206630 and, while
that check reports an active event, calls SceSleep at 0x274828 from 0x206640.
Therefore remaining inside EvtReadExec does not itself mean the file service
is stuck. WaitSema at 0x256074 also occurs during normal task yield/polling.
Do not force a semaphore, fabricate a read result or skip the original event.

## Current follow-up

The extended duplicate `20261009T230326Z-f6519fe8` was interrupted after
the closed trace exposed background budget exhaustion; no terminal report
was produced and it is excluded from outcome comparisons.

The replacement `20261009T230439Z-c8e30fcb`, session 85745, selects the same
file methods but filters caller sources, excluding background 0x1B6018.
It ended with timeout after 360.14 seconds, no fault markers, last EE field
7639 and latest captured image frame-16000.png. Its 28 selected entries
did not exhaust the 256-entry budget. The initial file poll and wrapper
return match the closed run above; no later selected file operation was
recorded. Threads 23/31/32 still wait on semaphores 153/172/156 at
0x29CC68, RA 0x25607C. Gameplay and event completion remain unverified.
No game or build process from this investigation remains live.

`event-execution-trace-plan.json` prepares a separate, unexecuted experiment
for EvtReadExec's parse and event-active checks, with physical/indirect
manager windows. It uses nine targets and sixteen reviewed caller sources.
An interim state file can lag buffered output and is not a completion test.

Trace reports live in `artifacts/research/20261009/event-read-armed-trace.json`,
`event-read-armed-jobs.json`, `event-file-poll-trace.json` and
`event-file-poll-filtered-trace.json`. Original static
table bytes were read from the private ELF load segments, with targets
recorded in `event-file-poll-static-table.json`.

Python verification: 151 tests passed, including shared-budget exhaustion
by other targets, exclusion of leave lines from that count, preservation
of yielded poll state, and rejection/reporting of unusable byte snapshots.
The previous graphics suite passed 525 C++ tests; it was not rerun for this
Python report change. The user's memory-card hash still matches the saved
baseline `8207bfeaff91e21998e71df1d3d86375f458e3d04a4669612f2bf89ccaabc448`.

## Parse/execution trace result and the next boundary

`20261009T231155Z-205bb886` completed its diagnostic timeout after 360.156
seconds, no fault markers, last EE field 7489, latest frame-16000.png.
It recorded only the initial EvtReadExec entry and yielded leave; none of
the selected parse, event-active-check or sleep caller sites appeared.
The arm marker was present and the shared budget was not exhausted.
Thus the previous read-wrapper result must not be used to claim the event
parser has already been reached. Its place in the remaining parent call
chain still requires evidence.

The next bridge trace `20261009T231924Z-422683f6`, session 68170, is live.
It includes the read wrappers, chapter-resource preparation 0x12BFC8 /
0x12B9C8 /0x1B63F0, movie preparation 0x2571B0, and all SceSleep caller
sites after the same arm point. This broadens the observed boundaries
between the read-wrapper return and parser rather than guessing which
service is stuck. No guest behavior was changed.

The report parser now preserves all observed argument and selected memory
snapshots, including indirect-window addresses. Invalid odd-length hex
is reported and excluded instead of terminating analysis or inventing
bytes. 153 Python tests passed, including seven trace-report tests.

`event-assets-header-inventory.json` bounds-checks all 2,628 AFS entries in
the user's unchanged bio4dat.afs and samples the first 64 bytes of each
nonempty entry. None starts with the exact five-byte `event` prefix.
That limited scan does not establish missing assets, distinguish nested
containers from transformed data, or certify EVD contents in guest RAM.

## Bridge result: movie readiness blocks entry to the parser

The bridge run ended with diagnostic timeout after 360.125 seconds, no fault
markers, last EE field 7584 and latest frame-16000.png. It recorded the
read-wrapper check returning v0=1, chapter preparation 0x12BFC8 returning
v0=1, and movie preparation 0x2571B0 from 0x2064C4 for the observed string
`movie/r120s99.sfd`. The next call is 0x273348 from 0x2064CC.

There were then 247 selected SceSleep entries at 0x274828 from 0x273378,
exhausting the 256-entry trace budget. The original 0x273348 routine checks
`root = *(0x325308); *(root + 0x7F50) & 0x04000000` and yields while this
bit is zero. Thus the captured wait is **before** event parsing and is tied
to movie readiness, not a demonstrated blocked EVD file read. The cap limits
this direct observation to the recorded calls; timeout and final waiting
threads alone do not prove that no unrecorded state change occurred later.

The original writer at 0x256FB4 sets that readiness bit only on the branch
where the virtual decoder-status method called from 0x256F88 returns 2.
It is reached from the movie worker's polling path:
0x257390 → 0x2572F0 → 0x256EB8. Original words for the wait and polling/writer
functions were checked against the ELF in
`movie-readiness-original-word-audit.json`. No guest code or flag was patched.

The next plan `movie-readiness-trace-plan.json` arms at 0x257390 and observes
original initialization, polling and raw decoder-object windows, including
the actual root+0x7F50 word. It is prepared but not run. Check the decoder's
status and data supply before choosing a fix. FFmpeg is OFF in the current
build cache; that alone does not prove this original CRI path calls the
FFmpeg-backed Sony MPEG stubs or that enabling the option would fix it.
All investigation runs are now closed; the packaged graphics executable
and user card remain unchanged.

## Worker-entry arm limitation and decoder status audit

Run `20261009T232923Z-22bb0e5d` ended at 360.141 seconds with exit 124,
no fault markers, last EE field 7226, and frame-16000.png. Its input replay
was confirmed in stderr. The trace armed on 0x257390 recorded **zero**
entries and no arm marker. This is not evidence that decoding failed:
EeScheduler.cpp calls lookupFunction(context.pc) directly when starting or
resuming a thread, bypassing the dispatchGuestBranch probe at that entry.

Original ELF inspection establishes the decoder vtable at 0x331BF8 and
status slot +0x20 = 0x2BECE8. That method reads decoder+8. When this is 2,
it calls 0x2D1948 on decoder+0x40; this reads subdecoder+0x48. Values 4/6
map to ready=2; negative values map to error=4; other values to waiting=1.
The static audit checks 303 original instruction comments with zero word
differences in `movie-status-original-word-audit.json`. It does not prove
the live decoder has those values, or validate generated instruction semantics.

The replacement `movie-launch-trace-plan.json` arms on the observed movie
request 0x2571B0, monitors original task creation and initialization, and
separately selects worker entry/resume PCs in the EE scheduler trace. Task
kind 3 maps to 0x452078 using the original stride 0x350/base 0x451688.
Run `20261009T233612Z-4d8fbc9a`, session 59595, is live with the confirmed
PS2X_NATIVE_PAD_REPLAY option. No build is live. The preceding short run
`20261009T233542Z-a71b5321` was interrupted after a wrong replay option
was detected; exclude it from result comparisons. Package/card unchanged.

## Movie worker and waiting decoder observed

The replacement run `20261009T233612Z-4d8fbc9a` ended at 360.14 seconds,
exit 124, field 4563, no fault markers. The shared call trace reached its
256-entry cap. It proves task kind 3 requested 0x257390, CreateThread
returned id 32, and the worker called its original initialization and poll
functions. The live decoder is 0x331DDC, vtable 0x331BF8, validity word 1,
state word at +8 = 1. All 61 recorded 0x2BECE8 returns were 1 (waiting).
No 0x2D1948 status call occurred in those observations, consistent with
the original +8 != 2 branch. Do not infer the state of later unrecorded polls.

This narrows investigation to movie open/setup/data supply. The initializer
chooses the batch branch only when controller+0x2A4 equals 0xFFFE; flags
0x400 alone do not select it. The captured lookup result was 0x10C0, so
the next probe selects the original single-file open chain 0x2BE4F8,
0x2BE258, 0x2BE720 and 0x17BC20, plus raw decoder command/state windows.
`movie-open-trace-plan.json` is prepared, not executed.

An auxiliary diagnostic problem was also measured: PS2X_TRACE_EE enabled
298,105 ReferThreadStatus lines in this run. Thread.cpp now bounds these
lines at 512 and emits an explicit cap notice; status-service writes and
returns still execute after the log cap. Runner build session 24474 is
live; no game is live. Build/tests/runtime cap verification are pending.
See `movie-launch-trace.json` and `movie-launch-observation.json`.

The bounded-log runner build completed with exit 0 in 149.9 seconds,
87,152,640 bytes, SHA256
`52a28975360b05405b704c8b78038a895886f122ea8c383ef24f38e103726784`.
The 525 C++ tests passed with PS2X_TRACE_EE enabled. The repeated-query
test poisoned its output buffer before each of 600 requests and verified
the final complete status ABI and successful returns after the log cap;
the captured log contains 512 status records and one cap notice.

Movie-open diagnostic `20261009T234600Z-06c1d5d8`, session 61614, is live
with this runner and `movie-open-trace-plan.json`; no build is live.
The packaged executable/card hashes were rechecked and remain unchanged.
This is a diagnostic fix and an active investigation, not a movie repair.

## Archive metadata matches the actual video entry

Movie-open run `20261009T234600Z-06c1d5d8` ended with exit 124 after
361.562 seconds, last EE field 5961, no fault markers. The bounded auxiliary
log has 512 records plus its cap notice in the actual game run as well.

0x2BE4F8 received archive 1, index 0xC0 (192). 0x17BCA8/0x17BC20 returned
0 and wrote `\\BIO4MOV.AFS`, sector offset 0x54501, and sector count 0x3CA3.
Reading the unchanged archive's table independently gives entry 192 offset
0x2A280800 and size 31,791,104 bytes: the sector values match exactly.
The first 64 bytes start with 000001BA (pack header). This verifies metadata
selection and bytes existing on disk; it does not prove delivery to the
decoder or full video validity. Evidence: `20261010/movie-open-observation.json`.

The shared trace cap was consumed by 186 calls to the global-pointer getter
0x2BD868. The next probe excludes this getter and monitors the original
service functions (0x2C06D0/0x2C0928/0x2C09F0/0x2C0A90), their lock and
file readiness gates, decoder command windows, and subdecoder state.
Run `20261010T024742Z-b87ecdef`, session 10597, is live with
`20261010/movie-service-trace-plan.json`; no build is live.

## 2026-10-10: فرز خدمة الفيديو وتصحيح تعليق EE


انتهت تجربة `20261010T025459Z-5869ad6b` بمهلة 360.14 ثانية، حقل EE 7855، دون fault markers. الاستدعاء الكامل المسجل للخدمة حدث أثناء reset مع مانع global+0x24=1؛ زال المانع بعده، ثم ملأت الفحوص الخفيفة حد 256. لا يُستنتج غياب الخدمة لاحقًا من هذا التسجيل. المهمة 7 ظهرت WaitingSuspended عند `0x29CB48`، عودة `0x17C3B0`. الخدمة الكاملة `0x2C0750` مسجلة ضمن مجموعة 6؛ مهمتها الأصلية `0x17C318` تستدعي تلك المجموعة.

وُجد خطأ مستقل قابل للتحقق: SuspendThread يراكم عدادًا عند إعادة تعليق EE، بينما [ps2tek BIOS 37h/38h](https://psi-rockin.github.io/ps2tek/index.html) ينص أن SUSPEND وWAITSUSPEND لا تتغير بإعادة التعليق. صُحح ذلك، وأضيف تحقق لتكرار التعليق 100 مرة ثم استئناف واحد، وللمحافظة على SleepThread عند استئناف WAIT-SUSPEND. البناء والاختبارات وأثر اللعبة معلقون؛ لا ادعاء أن هذا وحده حل الفيديو.

التجربة قليلة الأهداف `20261010T030411Z-106cdb7f`، جلسة 53184، جارية بمهلة 360 ثانية على runner السابق؛ لا بناء حي. حزمة المستخدم وبطاقة الحفظ لم تُستبدلا. الدليل `artifacts/research/20261010/movie-delivery-observation.json`. الأقسام التالية تاريخية.


## 2026-10-10: closed worker-wait probe and reference tool

Both kernel contract fixes passed526 C++ tests. Run20261010T032611Z-dd23e771 closed124/361.562s/no faults, EE3221; the rare-service probe reached the file-open gate with16 entries, cap not reached. See RE4_EE_REPEAT_SUSPEND.md. All earlier live/pending references above are historical checkpoints.

Worker-wait run20261010T034603Z-88a47349 closed124/360.141s/no faults, EE3008. It captured256 selected entries (cap reached):102 helper17C458,50 service191C78,76 mode191DA8,26 group5 wrapper18BD30, one17D788 and one2BB018. All76 completed mode reads returned2, derived by the original17C838 from2F68B4. This is a dispatch mode, not a file completion result.17D788 returned1 after configuring the file object;2BB018 yielded. Data delivery and decoding remain unverified. Instruction comments for170 words in8 selected functions match the original ELF, with zero differences; execution equivalence is not established by that check.

A diagnostic window mistake was corrected in the next plan:2FE398:0x40 means an indirect pointer window, not file-object+0x40. The inline tail uses absolute2FE3D8. The next bounded probe selects service groups0–3 and their callback tables, excluding high-frequency worker status/mode polls. Auxiliary PS2X_TRACE_EE logging is disabled for this next probe; guest behavior is unchanged. Evidence is in artifacts/research/20261010/movie-worker-wait-observation.json and movie-worker-original-word-audit.json.

The local paused-PCSX2 reference reader now passes10 synthetic protocol/identity/stability/output-guard tests. No live PCSX2 process was found during the read-only process check, and no real reference capture has been claimed. See PCSX2_REFERENCE_TOOL.md.

The callback-table run20261010T035311Z-2a0a7433 closed124/360.125s/no faults, EE3177. It reached the shared256-entry cap:127 group0 wrapper18BCB8 and127 group2 wrapper18BCE8, plus17D788 and2BB018. First captured group0/1/3 callback tables were empty. Group2 contained193918,1918A8,2C0688,18E068.1918A8 calls17FD98 ->17FDC0; that pump checks guard2FF154 and walks request slots3115C0 with stride0xC4, calling181CD0 for active entries and191F40 later. These addresses derive from captured tables and original code; table membership does not prove completion of the callbacks. Data delivery and movie decoding remain unverified, and the inspected last frame17000 is gray. The next pump-only plan is prepared, not run. No live game/build remains. User executable and card hashes remain unchanged.
