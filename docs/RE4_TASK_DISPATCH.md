# RE4 task dispatch investigation

The black screen remains unresolved. This investigation follows guest task
state without modifying guest data or original game files.

Capture `20261007T053300Z-70994b86` ran for 180.109 seconds with runner SHA-256
`778e0c8df6762d8acada3b939270a2a855f360070dfb5c2d341bad9ce155699b`.
All 84 PNGs were black and the known-fault detector reported no matches.
Evidence: `artifacts/tool-audit/20261006/task-state-summary.json`.

## Observed state and code interpretation

The main loop calls 0x255D68, which visits six records starting at 0x451688
with stride 0x350, skipping index 6. Each visited record goes to 0x255DE0.
The bounded trace covers 32 main-loop iterations, alongside calls to
0x1B5F60 and 0x221750. The latter two each have 32 enters and 32 leaves;
the task dispatcher has 192 enters and 127 leaves. Missing leaves can
represent scheduler preemption, so they are not a deadlock diagnosis.

| Record index | Address | Observations at entry |
|---|---|---|
| 0 | 0x451688 | State 1 once, then state 2 with countdown 1 |
| 1 | 0x4519D8 | State 1 twice, then state 2 with countdown 1 |
| 2 | 0x451D28 | State 0 throughout sample |
| 3 | 0x452078 | State 0 throughout sample |
| 4 | 0x4523C8 | State 1 once, then state 2 with countdown 1 |
| 5 | 0x452718 | State 0 throughout sample |

Static inspection explains why equal countdowns need further tracing:

- 0x2562B8 returns the state byte of the indexed record.
- At 0x255DF0, the dispatcher queries record 4. When nonzero, the gates
  at 0x255E08 and 0x255E10 skip some records, including record 0.
- State 1 creates and starts an EE thread using the entry stored at
  record+0x340. State 2 decrements a halfword at record+0x14 and, when it
  reaches zero, changes state to 3 and calls 0x29CC40 with record+0x0C.
- 0x256010 sets state 2 and the countdown, then coordinates with semaphores.
  Consequently a countdown of 1 every sampled frame can mean a task resumes,
  does work, and waits again. It does not prove the countdown is stuck.
- Record 0 is initialized with guest function 0x278D08 from main-loop
  setup at 0x227CB4. That function uses a state-indexed call table at
  0x32AAA8. This is a follow-up location, not proof of where the bug lies.

The next capture targets thread creation at caller 0x255EE4 and semaphore
signals at caller 0x255F44. Memory windows at record+0x340 identify worker
entry points, enabling their actual wait condition to be traced.

## Worker identified and wake requests observed

Capture `20261007T053626Z-6779b285` finished after 180.125 seconds with
85 black images, the same runner, and no known-fault matches. Creation
calls at 0x255EE4 exposed entries 0x278D08, 0x10A610, 0x172AA8 and
0x10A318. Record 4's entry and callback fields at 0x452708 both contain
0x172AA8. The trace observed 126 calls signaling semaphore 0x9D and 125
signaling 0x9A at caller 0x255F44. There are no corresponding leave
records in this sample; this is evidence of requests, not completed workers.
Evidence: `artifacts/tool-audit/20261006/task-wakeup-summary.json`.

Inspection of 0x172AA8 narrows the next capture to its waits and to waits
inside 0x172708. It can wait on 0x2F33D0, process queued entries at
0x417500, and poll 0x298960 from 0x1728E0. Trace caller addresses rather
than globally sampling 0x256010, whose unrelated callers would consume
the diagnostic limit before this worker is observed.

Capture `20261007T053944Z-d811bbdd` completed after 180.094 seconds,
with 85 black images and no known-fault matches. It recorded one wait
from 0x1728AC, then 128 service polls from 0x1728E0 and 127 waits from
0x1728D8. There were no selected waits from the initial 0x172B10 loop.
The worker is therefore cycling through the status-poll loop inside
0x172708. The observed leaves stop at nested continuation PCs, so their
v0 values must not be interpreted as final service return values.
Evidence: `artifacts/tool-audit/20261006/worker-wait-summary.json`.

At this point, the next diagnostic must inspect the status response rather
than just count worker waits. Static inspection shows 0x298960 delegates
to 0x298BE0, which obtains a response through 0x29A2F8 and combines a
flag from 0x29AFC0 with response bytes at offsets 8, 9 and 10. The latter
leaf reads gp-0x7F20. The original ELF's MIPS reginfo supplies gp=0x3D1DF0,
so this flag is at 0x3C9ED0. This establishes concrete observation points;
it does not yet establish which nonzero flag or transport behavior is wrong.

## Completed status observations (2026-10-07)

Capture `20261007T054336Z-58f8d609` established 123 genuine returns from
leaf 0x29AFC0 to 0x298C14: one local flag=1, then 122 local flag=0;
reply bytes 8/9/10 were 00/00/00 once, then 01/01/00. The STAT RPC SID
is 0x53544154, client 0x4588E8, original IOP server 0x159A00. RPC function
2 sends command 0x20000000 and receives at 0x458980. Nonzero reply bytes,
not just the local flag, sustain the selected worker's busy loop.

After fixing SIFCMD ordinal 23, capture `20261007T104211Z-9cc59b10`
still showed the same pattern: 256 completed leaf returns, one flag=1
and 255 flag=0; reply bytes 01/01/00 on 255 returns. All 84 captured
frames were black. The repair did not establish that RE4 invokes this
import or that it causes STAT's busy state. Automated audit:
`artifacts/research/20261007/rpc-wait-after-sif.json`.

Final runner with SIF and CMSAR0 fixes, `20261007T105041Z-b3ff6e0a`,
reproduced the same 256-return pattern and 85 black frames over 180.219 s.
Audit: `artifacts/research/20261007/rpc-wait-final.json`.

## Separate GS interrupt lead (continuation)

Local GS SIGNAL/FINISH handling sets CSR bits. Whether all unmasked events
reach the EE interrupt path still needs a complete audit. PCSX2's
[GS.cpp](https://github.com/PCSX2/pcsx2/blob/master/pcsx2/GS.cpp) provides a
primary reference: IMR unmasking considers pending CSR events, and gsIrq
routes to INTC_GS. This comparison alone is not evidence that GS interrupts
cause RE4's current black screen. No interrupt behavior was changed here.
