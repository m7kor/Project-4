# EE repeated suspension â€” 2026-10-10

The scheduler previously incremented `suspendCount` on every SuspendThread, including SUSPEND and WAITSUSPEND. This permits repeated suspends to outnumber resumes indefinitely. [ps2tek BIOS37h/38h](https://psi-rockin.github.io/ps2tek/index.html) describes repeated suspension of these states as having no effect, and ResumeThread as changing SUSPEND to READY and WAITSUSPEND to WAIT.

`EeScheduler::suspendThread` now preserves an already suspended state. Its retained internal field is a binary membership flag; one ResumeThread clears it. The change does not wake a sleeping waiter. Tests exercise 100 repeated calls both on READY->SUSPEND and Sleep->WAITSUSPEND, one resume restoring the previous state, and wakeup while suspended. All525 C++ tests pass.

RE4's full movie service is registered in group6 and executed by17C318. The baseline rare-target run20261010T030411Z-106cdb7f ended124/360.141s/no faults, field7144, with only four selected entries and no exhausted cap. The one full pump occurred during reset while its global guard was set; after reset it did not reappear in the selected dispatch targets. Thread7 ended WaitingSuspended. This motivates checking thread lifecycle, but does not prove repeated suspension is the cause of this game's wait. The patched runner/game comparison is pending. No user package update has been made for this kernel change.

Original ELF comparison checked281 unique instruction comments across11 service/worker functions, with zero mismatches. It verifies instruction identity only, not the generated execution or all guest callbacks.

## Guest return ABI — prepared after the first comparison build

A second independent bug was found in the syscall wrappers: successful SuspendThread and ResumeThread returned internal KE_OK (zero) rather than the target thread ID. Original RE4 helper17C510 propagates ResumeThread's result, and17CBB0 compares it with the stored worker ID at17CBD0/17CC08 before calling17C4A8 to wake the sleeping worker. Returning zero fails these gates for valid nonzero IDs.17C318 uses the same gate at17C3D8.

The syscall wrappers now translate internal success into the resolved target ID, retaining negative errors. This preserves the scheduler's internal KE_OK API. A new syscall-level test checks normal and negative interrupt variants, repeated suspension, successful resumption, and unchanged errors. It is prepared but not yet built/tested. The live84893 comparison contains only the earlier idempotence change, so it cannot validate the return-ABI fix.

References: [ps2tek BIOS37h/3Ah](https://psi-rockin.github.io/ps2tek/index.html), [PS2SDK declarations](https://github.com/ps2dev/ps2sdk/blob/master/ee/kernel/include/kernel.h), and the game's original instructions. No per-game wakeup/ready-bit override is introduced.

## Validation checkpoint

The idempotence-only runner built in158.3s. Its run20261010T031456Z-24fa66c4 ended124/361.531s/no faults, field7589. It reached the movie request but recorded the same four service entries as baseline and did not prove file delivery. This independently rejects a claim that idempotence alone fixes the movie wait.

The syscall return-ID test build initially failed because the test-local KE_NOT_SUSPEND constant was undeclared; adding its existing ABI value (-415) resolved that compilation error. All526 C++ tests then passed, including the syscall ID gate and preserved error results. The runner with both changes built successfully in141.2s.

## Closed game comparison

Run20261010T032611Z-dd23e771 ended124/361.562s with no fault markers, last EEfield3221. Under the same rare-service trace plan, selected entries increased from4 to16 without hitting the cap. Full service continued beyond reset and reached2C0458 ->2C0CD8 ->17D3A0, then2C0D50 with sector count0x3CA3. The file worker7 ended READY at17CAEC. This validates advancement to the movie file-open gate, not delivery of bytes or completed decoding:2C0458 yielded and the inspected late image remained gray. Lower field progress is not an FPS improvement. No live run/build remains. Package and memory card are unchanged; the kernel fixes are in the development runner, not the user package.

Evidence: `artifacts/research/20261010/movie-resume-id-trace.json`, `ee-thread-fix-validation.json`, and the run's `report.json`. Earlier pending-state paragraphs above describe historical checkpoints.
