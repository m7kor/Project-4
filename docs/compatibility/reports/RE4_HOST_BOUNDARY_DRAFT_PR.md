# Reduce VU helper call-boundary overhead in an isolated RE4 experiment

Existing compiled VU blocks repeatedly cross shared helper boundaries. Force inlining five unchanged FMAC/queue helper bodies to reduce that overhead, preserving retirement and floating-point operations. Keep the reference executable and the experimental build separate; no package promotion.

Seven alternating RE4 measurement pairs in one fixed scene gave a median paired gain of 4.9357% (median speed 0.205848x to 0.215486x). Isolated workloads improved by 2.8251% and 3.1200%. Full-state replay covered 3200 snapshots, 964/1024 commands, small budgets, continuation, queues and GIF; C++ passed 635/635 for each implementation. 37 matching guest-tagged frames and the common committed raw PCM prefix agreed.

Limitations: Clang23.1.1 only; not whole-campaign acceptance, hardware validation of this candidate, speaker/AV-sync proof, or a new save/reload acceptance. Two full-suite invocations retained failures; aggregate gate includes repaired framework paths and all104 Python tests. Existing47/55 hardware results belong to a separate pinned Zmbor engine. External quicksave remains unimplemented.

Runtime-only diff: `RE4_HOST_BOUNDARY_RUNTIME.patch`. Arabic evidence and exact identities: `RE4_HOST_BOUNDARY_ENGINEERING_AR.md`. Private traces, generated guest code, binaries, assets and saves are excluded. This is a local draft; no remote PR was created, no push or merge attempted. Historical GitHub403 remains unresolved; do not infer present write access.
