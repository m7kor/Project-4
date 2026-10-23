# Process / Agent Guardrails

Distilled from `resources/08-infinite-knowledge-base.md`, `resources/10-agent-guardrails.md`,
`resources/11-operational-phases.md`, `resources/13-decisional-brain.md` and
`resources/padspecs.txt`.

**On `padspecs.txt`:** it contributes nothing to this cluster. It is a PAD (controller)
protocol reference — device mode IDs, command opcodes `0x40`–`0x4F`, wire formats — with no
process, agent or workflow content. It is the one file in this cluster that is pure hardware;
nothing in this document is derived from it.

**On the corpus as a whole:** it is written as a *prose skill document for a human-reading
LLM session*, not as a specification. It is rich on prohibitions and on evidence discipline,
and genuinely thin on two things this document must flag as gaps rather than fill:
**retirement/supersession of knowledge**, and **any machine-readable form of a decision**.
Both gaps are named explicitly in §3 and §5 below.

---

## Guardrails

### The layer prohibition (absolute)

The corpus's central structural rule is that there are exactly four places a fix may live.

> **10 §3.1:** "You have exactly **4 tools** to fix anything. There is no 5th option. If you
> can't map a problem to one of these, you don't understand the problem yet."

| # | Tool | What it does | Files touched |
|---|------|-------------|---------------|
| 1 | **TOML Config** | Declarative: stubs, skips, patches, nops | `game.toml` |
| 2 | **Runtime C++** | Implements PS2 hardware in native code | `ps2xRuntime/src/lib/*.cpp` |
| 3 | **Game Override** | Per-game C++ replacing recompiled code | `ps2xRuntime/src/lib/game_overrides.cpp` |
| 4 | **Re-run Recompiler** | Regenerate runner code from updated TOML | `output/*.cpp` |

> **10 §3.1:** "**NEVER**: edit `runner/*.cpp`, write inline assembly hacks, or bypass the
> architecture. If none of the 4 tools fit, STOP and ask the user."

> **10 §3.2:** "NEVER edit the runner file directly"

> **10 §3.3:** "If your answer to question 4 is 'edit the runner .cpp' → **your answer to
> question 2 is WRONG.** Go back."

> **11, Decision Tree:** "**NEVER patch `runner/*.cpp`. Always fix via runtime or override.**"

> **13 §4 (TOML anti-signal):** "If the function does GAMEPLAY LOGIC (not hardware), stubbing
> is hiding a bug."

> **13 §4 (Override anti-signal):** "If you're overriding more than ~5 functions for the same
> subsystem, you probably need a Runtime implementation instead."

> **13 §4 (Recompiler anti-signal):** "Never rerun the recompiler 'just to see if it helps.'
> It takes a full rebuild after."

### Red flags — the same rule as a self-interrupt list

> **10 §3.4:** "If you catch yourself doing any of these, STOP IMMEDIATELY:"
> — Opening `runner/out_*.cpp` to edit it. ("Your edit will be overwritten.")
> — Writing `#ifdef` in runner code. ("Write a Game Override that replaces the function entirely.")
> — Copy-pasting MIPS disassembly into C++. ("Understand WHY the recompiled version doesn't work, fix the ROOT cause.")
> — Adding `if (address == 0xXXXXXX) return;` in the runtime. ("You're patching a symptom, not the cause.")
> — Creating "adapter" functions between runner calls. ("The recompiler handles calling conventions.")
> — "Spending >10 minutes on a single crash without a diagnosis."

### Do not guess; consult the reference first

> **08 §Absolute Source of Truth:** "Do **NOT** guess. Do **NOT** hallucinate based on general
> MIPS knowledge."

> **08 §Golden Rule:** **"If it's hardware, it's mapped. If it's mapped, it's documented. If
> it's documented, it's in ps2tek."**

> **08 §Golden Rule:** "Never bypass an unknown hardware interaction by stubbing it with
> `ret0` without first checking the `ps2tek` to understand *why* the game is touching that
> memory. If you stub a DMAC completion flag with 0, you might cause an infinite spinlock.
> Read the docs!"

> **10 §6, the rule:** "If you're about to write code that touches PS2 hardware and you
> haven't loaded the relevant db file THIS SESSION → **STOP and load it first**. Never
> implement from memory. Always verify against the reference."

### Epistemic rules

> **10 §4, The 3 Rules of Epistemic Humility:**
> 1. "**Never claim without evidence.**" — ❌ "This function returns 0" → ✅ "Let me verify —
>    `view_file` on the function → yes, line 47 returns 0"
> 2. "**Never assume from pattern.**" — ❌ "The other syscalls use this pattern, so this one
>    must too" → ✅ "Let me check db-syscalls.md for this specific syscall number"
> 3. "**If you're >80% sure without recent verification, you're probably wrong.**" — "Re-read
>    the source. Re-read the reference. THEN be confident."

> **10 §4, the framing:** "You are an LLM. You WILL hallucinate. You WILL confuse similar
> patterns. You WILL forget things from 50 tool calls ago. Accept this and COMPENSATE with
> structure."

> **13 §5, the named worst trap:** "I'm confident I know the answer without checking" —
> "**THE MOST DANGEROUS TRAP.** Confidence without verification = hallucination risk."

### The adversarial three-step — mandatory for every code change

> **10 §4:** "Before writing ANY C++ fix, override, or stub, you MUST execute:
> 1. **PROPOSE:** Draft your solution — which address to hook, what C++ logic, which file.
>    State your hypothesis about *why* this fixes the crash.
> 2. **ATTACK:** Immediately switch stance. Try to destroy your own proposal:
>    - Does the address exceed PS2's 32MB RDRAM (0x01FFFFFF)?
>    - Are you suppressing a crash that will just cause silent corruption later?
>    - Are you modifying a `runner/*.cpp` file instead of the runtime layer?
>    - Does this break any previous milestone in the state file?
>    - **Did you actually READ the relevant code, or are you assuming from memory?**
>    - **Have you loaded the relevant db file for this subsystem?**
> 3. **EXECUTE:** Only after the attack finds no fatal flaws, output the final code and commands."

### The Verification Ladder — mandatory for every code modification

> **10 §4:** "1. ✍️ Write the fix → 2. 🔨 BUILD it (read full output, verify exit code 0) →
> 3. 🎮 RUN it (read stdout, verify behavior changed) → 4. ✅ COMPARE to expected behavior
> (what SHOULD happen? does it?) → 5. 📝 Only THEN update `PS2_PROJECT_STATE.md` with
> success/failure"
>
> "**If you skip any step, your claim of 'fixed' is a hallucination.** Build output or it
> didn't happen."
>
> "Skip this ONLY for trivial reads, greps, or state file updates. For **any code
> modification**, this structure is mandatory."

> **13 §5:** "'It compiles, so it works' — **WRONG.** Compiling proves syntax. Running proves
> behavior. COMPARING proves correctness."

### The Circuit Breaker (3-Strike Rule)

> **10 §5:** "If you attempt the same `compile → test → fail → guess → compile` loop **3
> times** for the same crash: 1. **STOP.** Do not guess again. 2. Re-read
> `PS2_PROJECT_STATE.md`. 3. **LOAD the relevant knowledge database** … You MUST do this
> before strike 3 — never attempt a third fix without loading the reference. …
> 7. If still stuck: format a specific technical question and **ask the user**."

> **10 §6, Circuit Breaker integration:** "On strike 2 of the 3-strike rule, you **MUST**
> load the relevant db file before your third attempt. This is not optional."

> **10 §1:** "Trying 3+ fixes for the same crash without diagnosis | Guessing instead of
> reasoning | 3 Strike Rule exists — USE it."

### Anti-patterns — named cognitive traps (13 §5)

Each is stated as WRONG + a mandated corrective:

| Anti-pattern | The corrective the corpus demands |
|---|---|
| "This looks like the same bug as before" | "Every crash is unique until you VERIFY it's the same root cause. Same crash address ≠ same bug." Read registers/stack. |
| "The fix worked for another function, so I'll apply it here too" | "Go through the reasoning loop for THIS function." |
| "I'll just stub this and move on" | "Before stubbing, verify with Ghidra what the function does." |
| "It compiles, so it works" | Build → Run → Read output → **Compare** with expected. |
| "I'll add more logging and try again" | "**WRONG (after the first round)** … Escalate to the next level in the Diagnosis Ladder." |
| "I'm confident without checking" | "Check. Always check." |

### Context and hygiene rules (10 §1, 11 Phase 4)

These are stated as *the agent's own recurring mistakes*, with prevention attached:

| Rule as stated |
|---|
| "Editing a `.h` file 'just to add one field'" → "If in doubt, it's a .h and you can't touch it." |
| "Creating temp scripts in project root" → "Put ALL temp files in `/tmp/`. Clean up before ending." |
| "Reading a huge log file in one shot" → "Max 200 lines per read. Use `OutputCharacterCount=5000`." |
| "Appending to the same log file across runs" → "**Overwrite every time.** Better: read from stdout directly." |
| "Not re-reading the state file" / "Writing a fix without reading the state file first" → "Context drift … Before writing ANY C++ code → re-read state file." |
| "Leaving game processes running" → "Always `Terminate` … after reading output." |
| "Confident without verification" → "Verify. Build. Run. Read output. THEN claim success." |

From **11, Phase 4** (build and test):

> "⛔ Execute BUILD GATE before building: INSPECT command: no `--clean-first`, no `--target
> clean`, no delete … RUN: `cmake --build <build_dir>` — **INCREMENTAL ONLY, no extra flags**"
>
> "**Step A — Read the command.** Get the exact run command from `PS2_PROJECT_STATE.md` §
> Active Runner Command. **NEVER reconstruct it from memory.** Memory lies."
>
> Boot tests: 10–15 s max. Menu tests: 30 s max. "The game will crash or hang — short
> timeouts prevent wasting time waiting."
>
> "**NEVER** read more than 10K chars total from a single test run"
>
> "**Step D — Kill the process.** … Don't leave game instances running"
>
> "**Step E — Diagnose from the output you just read.** Don't re-run hoping for different
> results — same code = same crash. Fix first, THEN test again"
>
> "**Step F — Record.** One line in `PS2_PROJECT_STATE.md`: date, what you tested, exact result."

From **11, Phase 0**:

> "**NEVER reconfigure or delete the build directory without explicit user approval.** Only
> suggest; let the user decide."
>
> "**Do NOT auto-rebuild.** Report the status and ask the user how to proceed."
>
> "**Check runner code exists (SAFELY).** Do NOT list the runner directory!" (it holds ~32,000 files)

### Upstream-tool protocol (10 §2)

> "PS2Recomp is under **active development**. It has open bugs. You WILL encounter situations
> where the tool itself produces incorrect output. This is normal — don't hack around it,
> handle it methodically."

Protocol when an upstream bug is suspected:

> "1. **CONFIRM:** … Compare the Ghidra disassembly of the original MIPS with the generated
> C++. If the C++ doesn't match the MIPS semantics, it's the tool.
> 2. **WORK AROUND CLEANLY:** Don't patch the generated file. Instead: TOML stub/skip; Game
>    Override; TOML patch NOP.
> 3. **DOCUMENT:** Add a note to `PS2_PROJECT_STATE.md` under a '## Known Upstream Issues'
>    header — which function/address; what the recompiler generates vs. what the MIPS does;
>    what workaround you applied; link to the GitHub issue if one exists (or suggest opening one)."

> "**Do NOT:** silently work around tool bugs without documenting them. The user may want to
> report them upstream, and future sessions need to know which workarounds are 'permanent' vs
> 'waiting for a tool fix.'"

---

## Knowledge base discipline

### Storage model

> **08 §How to extract:** "All PDF text content has been extracted into the `db-*.md`
> knowledge bases. PDFs are kept as backup and for visual diagrams."

So there are two tiers: `db-*.md` structured knowledge bases are authoritative; the raw PDFs
and images are a **backup and a diagram source**, not a lookup path.

> **10 §6:** "You have 230+ KB of PS2 hardware documentation at your disposal. The boot loads
> pipeline and runtime references (03, 04). **Everything else is on-demand**."

### Indexing

The index is a **router, not a document**. `db-ps2-index.md` is titled "Master Index" and its
stated job is routing:

> **db-ps2-index.md:** "**The LLM looks here FIRST.** Every PS2 topic maps to a file and section."
> "Numbered files (01–09) are narrative references; `db-*.md` are structured knowledge bases."

Its tables are uniformly of the form **topic → file → section** (e.g. "VU UNPACK formats →
`db-ps2-architecture.md` → §6"). Sections, not files, are the unit of citation.

Images get the same treatment:

> **08 §2:** "`resources/images/IMAGE_CATALOG.md` — it lists 80 extracted PNGs sorted by
> category … **Each entry has filename, source PDF, and description.**"

Provenance is a required field of the catalogue, not an optional nicety.

### The trigger table — mandatory, session-scoped loading

> **10 §6:** "Everything else is **on-demand** — but you MUST know WHEN to reach for it."

| Encounter | Load | Why |
|---|---|---|
| Unknown syscall number | `db-syscalls.md` | Full syscall table with params |
| Unknown SDK function (sif*, sce*) | `db-sdk-functions.md` | SDK stub signatures |
| Hardware register address (0x1000xxxx) | `db-registers.md` | Register map by subsystem |
| Memory address confusion | `db-memory-map.md` | EE address space layout |
| Unknown MIPS instruction | `db-isa.md` | R5900 encoding |
| VU0/VU1 instruction | `db-vu-instructions.md` | VU reference |
| GS/DMA/VIF/GIF behavior | `resources/09-ps2tek.md` | "Holy grail hardware doc" |
| Multi-binary / overlay issue | `db-overlay-patterns.md` | Overlay detection & multi-TOML |
| Runtime crash (need register state) | `12-pcsx2-mcp-playbook.md` | Breakpoints, A/B comparison |
| Stuck after 2 failed fixes | `13-decisional-brain.md` | "Reasoning loop, anti-patterns" |

The binding rule:

> "**The rule**: If you're about to write code that touches PS2 hardware and you haven't loaded
> the relevant db file **THIS SESSION** → **STOP and load it first**. Never implement from
> memory."

Loading is **session-scoped**: evidence read in a previous session does not count.

### Recording what was learned

The corpus specifies exactly **one** write-back target and **two** record shapes:

1. **Per-test line** — 11 Phase 4 Step F: "One line in `PS2_PROJECT_STATE.md`: date, what you
   tested, exact result."
2. **Learned Pattern** — 13 §1, on a verified fix: update `PS2_PROJECT_STATE.md` with Learned
   Pattern: **"X causes Y, fix with Z."**
3. **Known Upstream Issues** — 10 §2, with the four mandatory fields listed above.

And the failure case is explicitly in scope:

> **10 §4, ladder step 5:** "Only THEN update `PS2_PROJECT_STATE.md` with **success/failure**."

### Recording FAILED approaches — what the corpus actually requires

**This is where the corpus is thinner than one might assume, and the gap should be stated
rather than papered over.**

The corpus requires that failures be *recorded*. It requires it in three places, always as a
line or note in the state file, not as a separate store:

- 10 §4.5: "update `PS2_PROJECT_STATE.md` with **success/failure**" — a failure is an
  admissible record, with the same ceremony as a success.
- 11 Phase 4 Step F: "date, what you tested, **exact result**" — the word is *result*, not
  *outcome-of-success*.
- 10 §2: "**Do NOT:** silently work around tool bugs without documenting them." — a wrong path
  is itself the thing that must not be silent.

What the corpus **does not** say, anywhere, in any of these five files:

- There is **no rule requiring a dedicated dead-end / failed-approach store.** Nothing
  prescribes a separate file, a separate schema, or a category distinct from "what we tested".
- There is **no rule about never retrying a previously-recorded failure.** The nearest is
  behavioural, not archival: 10 §5's 3-Strike Rule ("**STOP.** Do not guess again") and 13 §3
  Level 5 ("**Do NOT keep looping without new information**"). Both bound the *current*
  session's looping; neither requires a durable record that forbids re-treading.
- There is **no machine-readable decision format.** `PS2_PROJECT_STATE.md` is prose markdown.
  No schema, no required fields beyond the four upstream-issue fields, no required linkage
  from a recorded failure back to the hypothesis or change that produced it.

**Conclusion:** a durable, queryable, cross-session failure memory is *consistent with* the
corpus and in the spirit of 10 §2 and 13 §3, but it is **not something the corpus asks for.**
Any implementation of it is an extension, and should be defended as one.

---

## Operational phases

The corpus **does** define named phases with explicit machine-matchable identifiers and
explicit exit criteria. **11's header:** "The phase names match the `## Current Phase` field in
`PS2_PROJECT_STATE.md`" — i.e. the state file carries the current phase as a field.

Entry criteria are, with one exception, **not defined**. Only Phase 0 states an entry
condition ("Load this at session start for fresh projects"). For Phases 1–5 the sources give a
numbered task list and an `Exit:` line, and the transition is implicit: reaching the previous
phase's exit criterion. That is a real thinness, not an oversight I should paper over.

| Phase | ID | Entry criterion | Exit criterion (quoted) |
|---|---|---|---|
| **0 — Setup** | `PHASE_SETUP` | "session start for fresh projects" | "Both workspaces identified, toolchain verified, build health reported, ELF located." |
| **1 — ELF Analysis** | `PHASE_ELF_ANALYSIS` | *not stated* (implicit: Phase 0 exit) | "All TOMLs exist with analyzer data. State file records each binary path." |
| **2 — TOML Configuration** | `PHASE_TOML_CONFIG` | *not stated* | "TOML has overrides to bypass setup loops." |
| **3 — Recompilation** | `PHASE_RECOMPILATION` | *not stated* | "`out_*.cpp` files generated without fatal panics." |
| **4 — Build & Runtime** | `PHASE_RUNTIME_BUILD` | *not stated* | "Executable builds and advances past bootloader." |
| **5 — I/O & Menus** | `PHASE_IO_MODULE` | *not stated* | "Game reads files and sends GIF/DMA packets." |

Notable content inside the phases:

- **Phase 0** rates build configurations (clang-cl+Ninja+Release = "⚡ Optimal … Do NOT
  reconfigure"; MSVC+VS = "❌ Critical … 25h→1h difference") and reports build health
  separately from configuration (✅ Complete / ⚠ Needs rebuild / 🆕 Never built).
- **Phase 0** explicitly forbids two agent reflexes: listing the 32,000-file runner directory,
  and auto-rebuilding or reconfiguring.
- **Phase 1** contains a mandatory *question to the user*: "Ask the user if there are additional
  binaries to recompile."
- **Phase 3** exit criterion is **insufficient by the corpus's own standard.** "without fatal
  panics" does not mean the generated code is sound — Phase 3's own step 2 requires a manual
  grep ("Check output for `// Unhandled opcode` comments"), and 10 §1's flowchart has no branch
  for "recompiler emitted a runtime throw instead of failing". Our own `dead_ends.jsonl#0041`
  records exactly this: *"expect an unhandled opcode to fail the build — the recompiler emits a
  runtime throw into the generated C++."* The corpus states the exit criterion but not the
  check that would make it true.
- **Phase 4** carries the BUILD GATE and the 7-step standard test protocol (A–G), which is the
  corpus's only fully-specified per-iteration procedure.

---

## Decision procedure

### How a decision is made

**The loop** — 13 §1, run "for EVERY problem. No shortcuts, no skipping steps":

```
OBSERVE  -> LOCATE  -> UNDERSTAND -> DECIDE -> VERIFY
(symptom)  (which    (why does the  (which    (build -> run ->
            layer)    ORIGINAL     ONE of    compare)
                       work?)       the 4)         |
                                     ^            | still broken
                                     |            v
                       "If you can't pick ONE -> back to OBSERVE
                        you didn't finish        with NEW DATA,
                        UNDERSTAND. Go back."    not the same guess."
```

> **13 §1, the Golden Rule:** "**If you cannot explain WHY your fix is correct in one
> sentence, you are guessing.** Go back to UNDERSTAND."

Two different checklists gate the DECIDE step, and they are not the same:

- **10 §3.3, five questions, in order:** "1. **WHAT failed?** 2. **WHERE in the
  architecture?** 3. **WHY did it fail?** 4. **WHICH tool fixes this?** (exactly ONE) 5. **WHAT
  could break?** (regression risk?)" — "If you can't answer one, STOP — you need more
  information."
- **13 §2, four questions:** "1. Why does this crash/bug happen? 2. What did the original PS2
  code expect here? 3. Why does my fix address the root cause? 4. What will break if my fix is
  wrong?" — "If you can't answer all four, you are NOT ready to write code."

13 §2 supplies the standard of a good answer by contrast. A **bad** answer to Q2 is "I don't
know, I'll stub it"; a **good** one is "GhydraMCP shows the MIPS loads a pointer from
`gp+0x3A40` which is initialized by `sub_100200` during boot — the runtime never calls that
init function." A **bad** answer to Q4 is "Nothing"; a **good** one is "If the offset is wrong,
every function using `gp+0x3A40` will read garbage — that's ~15 functions in the subsystem."

### Escalation — the Diagnosis Ladder (13 §3)

"escalate through these levels IN ORDER. Each level gives you more information."

| Level | Instrument | Source of truth |
|---|---|---|
| 1 | STDOUT/STDERR | crash address → Ghidra; error message; assertion; stack trace |
| 2 | SUBSYSTEM MAP (10 §3.4/§3.5) | "Which Runtime file handles this address range?" |
| 3 | GHIDRA MCP (static) | "Read the ORIGINAL MIPS function. What does it actually do?" |
| 4 | PCSX2 MCP (runtime A/B) | "**First divergence = root cause**" |
| 5 | CIRCUIT BREAKER → **ask the user** | "Present what you know, what you tried, what you suspect." |

"Most bugs are solved at levels 1-2." Level 5 terminates with: "**Do NOT keep looping without
new information.**"

13 §5 adds the rule that governs this ladder procedurally: "'I'll add more logging and try
again' — **WRONG (after the first round).** If one round of logging didn't diagnose it, more
logging won't either."

### What counts as evidence

The corpus's evidence standard is **a fresh, cited, tool-produced reading — not recall and not
pattern**. The three canonical contrasts:

| Not evidence | Evidence |
|---|---|
| "This function returns 0" (remembered from 30 tool calls ago) | "`view_file` on the function → yes, line 47 returns 0" |
| "The other syscalls use this pattern, so this one must too" | "Let me check db-syscalls.md for this specific syscall number" |
| "There's a null pointer" | a mechanism traced through the original MIPS or the live runtime state |

Concretely, the corpus names these as *discriminating* observations:

- **Binary architectural questions.** 10 §3.2: "Is the address inside the recompiled ELF
  range?" — YES/NO splits the entire crash tree into two disjoint branches.
- **A divergence point.** 13 §3 Level 4: "The first register/memory divergence IS the root
  cause." Not "the values differ" — *the first place* they differ.
- **A named anti-signal.** 13 §4 gives each of the four tools a use-when table *and* an
  anti-signal; the anti-signal is what disqualifies a fix.
- **A regression question answered before the fact.** 10 §3.3 Q5 / the ATTACK step: "Does
  this break any previous milestone in the state file?"
- **A negative result read honestly.** 11 Step E: "Don't re-run hoping for different results —
  same code = same crash."

### How a decision is recorded

Only one target is ever named: **`PS2_PROJECT_STATE.md`**, with three record shapes —
a per-test one-liner (date / what / exact result), a Learned Pattern ("X causes Y, fix with Z")
on verified success, and a Known Upstream Issues entry with four mandatory fields on an
upstream workaround.

**What the corpus does not define, and this is a genuine gap:**

- **No falsifier field.** The words *falsify*, *falsifiable*, *disprove* and *refute* appear
  **nowhere** in any of these five files. "Hypothesis" appears once, as the label for the
  PROPOSE step ("State your hypothesis about *why* this fixes the crash"). The corpus's
  nearest equivalents to a falsifier are the ATTACK checklist, the ">80% sure without recent
  verification" rule, and "First divergence = root cause" — but a *measurement that would
  disprove a specific claim*, attached to that claim, is **not a concept the corpus has**.
- **No confidence or ranking scale.** Ranking appears only qualitatively ("highest ranked",
  "the simplest explanation"), never numerically.
- **No linkage requirement** between a decision and the evidence that justified it.
- **No status vocabulary** for an in-flight decision (open / applied / rejected / deferred).

---

## Gaps against our implementation

Compared against `ps2l/triage.py`, `ps2l/agent.py` and `knowledge/dead_ends.jsonl`.

### Where we are stronger than the corpus

Stated first, because it is load-bearing for the verdicts below.

1. **We made the falsifier explicit.** `triage.py` carries a `falsifier` field on every
   `Hypothesis` and closes every report with "A diagnosis without a falsifier is a guess."
   (triage.py:264, :552-553). Its rationale is stated exactly as a corpus-compatible
   extension: "the failure memory says the only way this project has ever been wrong is by
   naming a cause without a measurement that rules out the alternatives" (triage.py:23-24).
   **Verdict: keep it.** It is the mechanised form of ATTACK step 2 and of 13 §3's "first
   divergence" discipline, and the corpus has no equivalent.
2. **We mechanised the human-escalation rule.** 10 §3.1 says "STOP and ask the user" and 13 §3
   Level 5 says "ASK THE USER" — both are prose. `agent.py` returns exit 3 with "The loop cannot
   progress by itself: this needs a human", and refuses to invent a remedy: "Surfacing it
   rather than inventing a change" (agent.py:293-298, :319-320).
3. **We mechanised the signature catalogue's honesty rule.** 08 §Golden Rule ("If it's
   hardware, it's mapped… Read the docs!") restated as: "These are REAL signatures, not invented
   ones. Every pattern below was read out of the runtime's own source … A triage tool with
   invented signatures is worse than none: it confidently misclassifies" (triage.py:51-56).
   Note the "unclassified fault" hypothesis prints its own falsifier — "add a signature for this
   text to the catalogue" — so an unrecognised fault is reported as a *gap in our catalogue*,
   not as a diagnosis.

### G1. The loop has no falsification step, so it can never reach `rejected` — and therefore has no circuit breaker

**This is the most important disagreement, and it is the one I would fix first.**

`agent.py:323`:

```python
rec.status = "applied" if (remedy and remedy.kind == "cmd") else "deferred"
```

A hypothesis becomes `applied` the moment its remedy is **printed**. Nothing compares the
capture before the change to the capture after it. `Remedy.verified_by` exists
(agent.py:78, :88, :96) and is displayed, but no code path ever reads it back. `run_loop`
iterates `capture → classify → choose → print → save` and never diffs iteration *n* against
iteration *n-1*.

Consequences, stated plainly against the corpus:

- **10 §4 ladder steps 4 and 5 are unimplemented.** "COMPARE to expected behavior (what SHOULD
  happen? does it?)" and "Only THEN update `PS2_PROJECT_STATE.md` with success/failure" — our
  ledger writes a status *before* the verification that would justify it.
- **13 §5, "It compiles, so it works — **WRONG**", is unopposed by code.** Worse, our artifact
  asserts the opposite: `ledger_view` prints the tag `APPLIED`. `dead_ends.jsonl#0012` records
  the exact failure this invites: *"hope a RE4 guard fix works because the write succeeded —
  write sticks in RAM but the HUD never updates; success of a memory write is not proof."*
- **The 3-Strike Rule cannot fire.** Because the skip test is `if rec.status == "rejected"`
  (agent.py:285) and nothing ever writes `"rejected"`, the loop selects the same top hypothesis
  on iterations 1, 2 and 3 by construction. `rec.attempts` is incremented (agent.py:302) and
  then never read for escalation. With `--budget` defaulting to 3 (agent.py:498), a stock
  `lodestone agent run` on an unfixed fault *is* the `compile → test → fail → guess → compile`
  loop that 10 §5 names and forbids. 13 §3's terminal condition — "**Do NOT keep looping without
  new information**" — has no representation in the loop at all.
- **The "never re-proposes a rejected hypothesis" guarantee is currently vacuous.** It is real
  and correctly implemented (title-keyed, so volatile evidence cannot reset it — agent.py:163-168,
  which the selftest case 5 covers), but it is only ever exercised by a human hand-editing the
  JSON, which is precisely what selftest case 3 does (agent.py:439-442).

**Which is right:** the corpus. A ledger that cannot record a rejection is not a ledger of
learning; it is a list of things that were printed. The minimal fix is a post-remedy capture
comparison that diffs the signature set and `spin` detection, writes `rejected` +
`ruled_out_by` (the field exists at agent.py:126 and is *never* written by the agent), and
escalates to exit 3 at strike 3.

### G2. The shared failure memory is stored but not queryable by the loop

`cross_reference` (triage.py:425-429) does this:

```python
ids = re.findall(r"dead_ends#(\d{4})", h.next_action)
```

It regexes a **hardcoded string** inside each hypothesis's canned `next_action` prose, and
then checks those ids exist in `dead_ends.jsonl`. There is no similarity, tag or index lookup
over the 79 recorded entries. Consequently the only dead ends the tool can ever surface are
the two ids a developer typed by hand (`dead_ends#0063` at triage.py:285, `dead_ends#0077` at
triage.py:326) — and neither of those entries is reachable in reverse.

The entries that carry the project's most transferable lessons — `#0061` (a diagnostic behind a
build flag produced zero lines and the silence was read as a conclusion), `#0067` (the profiler
invalidated its own measurement), `#0070` (blaming the mechanism you happened to read last),
`#0072` (quoting a rate without saying what was counted), `#0074` (an instrument reporting an
impossible number), `#0080` (one read of the project's own memory map beat three rounds of
profiling) — are **inert**. The loop cannot find them.

This directly contradicts the value proposition in `agent.py`'s own docstring: "the failure
memory is shared, so **the ninth game starts knowing what the first eight already ruled out**."
Today the ninth game starts knowing nothing; a human has to go read the file.

**Which is right:** the corpus, on the principle that carries 10 §2 and 13 §3 Level 5 —
documentation that cannot be retrieved when the same trap is approached again is documentation
that has not been written. The fix is a retrieval step, not more writing: a signature→tags map
plus a `requires_ref` field on `Remedy` that forces a `db-*.md` read before a hardware-touching
remedy is surfaced (see G4).

### G3. The `ruled_out_by` field and the harness-timeout budget contradict the corpus's context rules

- `Runner.capture` (agent.py:192-211) does `subprocess.run(stdout=PIPE, stderr=PIPE)` and
  returns the **entire** stderr, unbounded. `analyse` then regex-scans all of it and appends
  every match to `b.guest_pcs`, an unbounded list. 11 Phase 4 Step C is explicit: "**NEVER**
  read more than 10K chars total from a single test run", and 10 §1: "Max 200 lines per read …
  You forget context is finite (~200K tokens)". Our reader has no cap at all.
- `--timeout` defaults to **120 seconds** (agent.py:498). 11 Phase 4 Step B mandates "Boot
  tests: 10-15 seconds max … Menu tests: 30 seconds max." We are 4–12× over the corpus's cap
  by default.
- `self.log.write_text(text)` (agent.py:210) does overwrite per run, which complies with
  "**Overwrite every time**" — but the consequence is that iteration *n*'s capture is destroyed
  by iteration *n+1*, so the post-change comparison G1 needs has no retained "before" to
  compare against. The rule the corpus gives ("Overwrite every time. Better: read from stdout
  directly") and the evidence-retention rule the corpus gives ("read the registers/stack …
  If the state is different from last time") pull in opposite directions here, and our
  implementation resolved that tension in the wrong direction.

**Which is right:** the corpus on the cap (it is a correctness rule for the agent, not a
stylistic one). On retention, the corpus is silent about *where* captures live, so I would keep
overwriting the working log but have the ledger store a bounded digest of each iteration's
capture alongside the signature set.

### G4. No layer, no reference, and no upstream fields — three prohibitions that are stated but unenforceable

- **"You have exactly 4 tools … There is no 5th option."** `Remedy` (agent.py:71-78) has
  `kind: str  # "cmd" | "edit"` and no notion of *which architectural layer* a fix touches.
  There is no field that could refuse a remedy aimed at a machine-generated file. Today this
  is inert because the catalogue holds only **two** entries and neither can modify anything —
  one is a `cmd` that is printed, not executed ("printed, not executed — apply it, then
  re-run", agent.py:315), and the other is explicitly `action="no edit — re-read the caller and
  callee in the generated sources"`. **So the prohibition is unenforced rather than violated.**
  The moment a real `edit` remedy is added, `10 §3.1`'s "no 5th option" becomes a rule with no
  teeth. Add a `layer` field; refuse anything whose target file is generated.
- **"If you're about to write code that touches PS2 hardware and you haven't loaded the relevant
  db file THIS SESSION → STOP and load it first."** There is no `requires_ref` on `Remedy` and
  no session-scoped reference-load state anywhere. 10 §6's 14-row trigger table is not encoded
  in any form. **This is the rule I would most want mechanised** — it is the corpus's
  single highest-value guardrail, it is stated with unusual force ("This is not optional"), and
  it is exactly the kind of check that only works if something enforces it.
- **10 §2's Known Upstream Issues register is not a register.** `dead_ends.jsonl` already
  carries eight genuine upstream-tool entries (`#0039`, `#0040`, `#0041`, `#0043`, `#0044`,
  `#0045`, `#0049`, `#0051`, all `project: ran-j/PS2Recomp`), which is the substance of the
  requirement. But the schema has no field distinguishing *our bug* from *upstream bug with a
  workaround applied*, and no `url` field — while 10 §2 asks for "Link to the GitHub issue if
  one exists (or suggest opening one)" and, decisively, for future sessions to "know which
  workarounds are 'permanent' vs 'waiting for a tool fix.'" That distinction is exactly what the
  existing `project` field erases. Add `origin` (ours/upstream) and `url`; add `lifetime`
  (permanent / pending-upstream-fix).

### G5. Smaller, non-blocking gaps

| Rule in the corpus | Our state |
|---|---|
| 11: phases named `PHASE_SETUP` … `PHASE_IO_MODULE`, tracked in a `## Current Phase` field | No phase field anywhere. `knowledge/` holds `PS2_REFERENCE.md` and `dead_ends.jsonl` only; `knowledge/ports/<port>.json` has no phase. |
| 13 §3: escalate through Diagnosis Ladder levels **in order** | `triage.py` ranks hypotheses from **one capture** with no notion of an escalation level. "Escalate rather than re-log" (13 §5) is unrepresented — a stall gets the same treatment on try 1 and try 50. |
| 11 Phase 3 exit: "`out_*.cpp` files generated **without fatal panics**" | Insufficient criterion, and we have already proven it (our own `#0041`). We should encode the grep-for-`Unhandled` check the corpus itself asks for in Phase 3 step 2. |
| 10 §1: "Put ALL temp files in `/tmp/`. Clean up before ending." | Compliant — `_selftest` uses `tempfile.TemporaryDirectory()` throughout (agent.py:401, :412, :427, :447). No violation. |
| 10 §3.4: "Spending >10 minutes on a single crash without a diagnosis" | No time-based guard. `agent.py` has iteration budget and per-run timeout but no wall-clock cap on a single un-diagnosed fault. |
| 13 §3 Level 5: escalate "Present what you know, what you tried, what you suspect" | The exit-3 path stops the loop correctly but does not print the falsifiers or evidence. `ledger_view` shows what was tried; the escalation message itself shows almost nothing. |

### What the corpus gets wrong, and we should not adopt

- **Phase 3's exit criterion is unsound** ("without fatal panics" when unhandled opcodes
  compile fine and become runtime throws). Adopting it verbatim would import a false gate.
- **The bounded-read hygiene rules (max 200 lines, `OutputCharacterCount=5000`) are tool-specific**
  (`view_file`, `command_status`, `send_command_input` are PS2Recomp-session tool names). The
  *principle* — bounded reads, because context is finite — transfers; the numbers do not, and
  they should be re-derived for whatever harness actually runs.
- **The corpus has no retired-knowledge mechanism at all** (§3 above). Absence of a rule is not
  permission to accumulate; but neither is it licence to invent one and call it compliance. If
  we want supersession semantics for `dead_ends.jsonl`, we should say plainly that they are
  ours.
- **Note `#0080` already corrects `#0065`** ("0x83 is a REAL kernel syscall … which RE4
  overrides, not a private number as dead_ends#0065 concluded"). The corpus's *retirement* rule
  would have been: when a later entry reverses an earlier one, the earlier entry must be marked
  superseded, not left to be re-read as still-true. Our store has no such marker. This is the
  concrete instance of the §3 gap, and it is already biting.