# Resumable original IOP calls

## Implemented executor mechanism

`IopEmulator::beginGuestCall`, `resumeGuestCall`, and `cancelGuestCall` retain the complete `IopCpuState` across instruction-budget boundaries. This includes pending branch/load state and HI/LO, not just PC and general registers. Each suspended call owns an exclusive slot in the existing call-stack region. Legacy synchronous calls lease available slots too, preventing an intervening module entry or callback from overwriting suspended stack frames. Legacy overflow borrowing is disabled while resumable calls exist.

Returned, pending, yielded, faulted, and rejected requests have distinct states. Partial V0 is not published as a completed result. A yielded call remains suspended; this API does not invent a wakeup. Return and fault release the context and stack; cancellation and reset invalidate it. Tokens remain monotonic across reset so stale handles cannot address a replacement call. Zero budgets, invalid entries, nested API execution, and stack overload are rejected. Active CPU ownership is restored on exceptions.

## Verification

`artifacts/verification/iop-resumable-call-final.json` passes all five groups: 491 C++ tests, 106 Python tests, and three tool checks.

The added real MIPS guest executes 600,000 iterations, exceeding two million instructions, then returns the expected product and writes the expected counter and saved stack marker. During suspension another call crosses a MULTU boundary one instruction at a time, and a legacy synchronous IRX entry writes its own stack. The first call's result and saved frame remain intact. Further checks cover finite stack capacity, branch-delay resumption, zero-budget rejection without destroying the original call, cancellation, reset with stale tokens, and fault cleanup.

## Integration still required

This mechanism is not yet used by RE4 RPC dispatch. It does not prove card formatting or save/load. The normal packaged executable remains the last verified normal-play build; these executor changes have not been promoted to it.

Local `IopRpcBridge` still executes the service synchronously. Its SetRpcQueue shim only returns the queue pointer; RpcLoop sleeps without dispatching queued work. Proper integration must preserve request/buffer ownership, original server-thread identity and priority, semaphore wakeups, completion after the original function returns, reset cancellation, and the EE/IOP clock ratio. It must not resume a yielded context before its real wait condition is satisfied.

The [PS2SDK IOP SIF RPC source](https://github.com/ps2dev/ps2sdk/blob/master/iop/system/sifcmd/src/sifrpc.c), inspected on 2026-10-08, binds queues to thread IDs, dequeues requests in RpcLoop, and sends completion after executing the service function. This is an architectural reference, not proof that its structure layouts are byte-identical to the game's original modules. Queue and wait integration is the next required implementation step, followed by the original Format/create/save/restart/load sequence in RE4.
