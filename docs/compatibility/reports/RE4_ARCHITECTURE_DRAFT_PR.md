# Draft PR — proposed, not published

Repository: https://github.com/m7kor/Project-4

Title: Preserve VU full-state evidence and record input on the guest clock

The compatibility lab previously lacked a verified nonzero guest clock in its gameplay input evidence. This change verifies the existing pad/IOP tracing implementation in an isolated Phase4-based link, extracts a lossless button/axis fixture, and records precise provenance. It adds narrow read-only packed-counter analysis and audio evidence summaries, plus explicit experimental-mode selection in the existing test driver.

An independent AOT coverage prototype is retained for engineering reproducibility only. Its first version exposed a sequence/scoreboard mismatch; the corrected generator preserves existing specialized block boundaries and passes complete state comparison. Seven alternating benchmark pairs then showed no reproducible gain, so it remains rejected and default-off. No runtime performance optimization or user-package promotion is proposed.

Validation: C++635 in both modes; 964 recorded commands; all3200 snapshots and budget/resume subsets;512 queue cases;64 deterministic operand cases;1024 fresh recorded commands with GIF/full-state comparison; full suite117 passed jobs plus8 existing separate Zmbor hardware mismatches; final lab Python100. Graphics/audio/gameplay limitations and the failed initial controls remain documented.

This is a lab source-only review bundle. It depends on the existing private compatibility fixtures and engine source layout. It is not a standalone game distribution or a drop-in upstream runtime patch. Generated game code, executables, game assets, saves, private traces, RAM dumps and Ghidra databases must remain excluded. The review should not promote the AOT mode.

Publication status: no PR was created. The last historical integration write failed403; current read-only repository metadata advertises push permission but does not demonstrate a working write scope. Credentials and access controls were not changed. Retain local commits and source-only patch until the owner supplies a supported publishing path. Do not target PS2Recomp upstream or merge without owner approval.
