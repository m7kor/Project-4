#include "MiniTest.h"
#include "ps2_runtime.h"
#include "ps2_runtime_macros.h"
#include "ps2_syscalls.h"
#include "ps2_stubs.h"
#include "runtime/ee_scheduler.h"
#include "runtime/ps2_call_capture_plan.h"
#include "Kernel/Stubs/SIF.h"

#include <array>
#include <atomic>
#include <cstdint>
#include <cstring>
#include <sstream>
#include <thread>
#include <vector>

using namespace ps2_syscalls;

namespace
{
    constexpr uint32_t K_PARAM_ADDR = 0x1000u;
    constexpr uint32_t K_STATUS_ADDR = 0x1400u;

    constexpr int KE_OK = 0;
    constexpr int KE_ERROR = -1;
    constexpr int KE_ILLEGAL_THID = -406;
    constexpr int KE_UNKNOWN_THID = -407;
    constexpr int KE_UNKNOWN_SEMID = -408;
    constexpr int KE_DORMANT = -413;
    constexpr int KE_NOT_SUSPEND = -415;
    constexpr int KE_SEMA_ZERO = -419;
    constexpr int KE_SEMA_OVF = -420;
    constexpr int KE_WAIT_DELETE = -425;
    constexpr int KE_RELEASE_WAIT = -418;
    constexpr uint32_t K_SEMA_WAIT_READY_ADDR = 0x1900u;

    constexpr int THS_WAIT = 0x04;
    constexpr int THS_SUSPEND = 0x08;
    constexpr int THS_WAITSUSPEND = 0x0C;
    constexpr int THS_DORMANT = 0x10;
    constexpr uint32_t TSW_SEMA = 2u;
    constexpr uint32_t TSW_EVENT = 3u;

    struct EeThreadStatusAbi
    {
        int32_t status;
        uint32_t func;
        uint32_t stack;
        int32_t stack_size;
        uint32_t gp_reg;
        int32_t initial_priority;
        int32_t current_priority;
        uint32_t attr;
        uint32_t option;
        uint32_t waitType;
        uint32_t waitId;
        uint32_t wakeupCount;
    };

    struct EeThreadCreateAbi
    {
        int32_t status;
        uint32_t func;
        uint32_t stack;
        int32_t stack_size;
        uint32_t gp_reg;
        int32_t initial_priority;
        int32_t current_priority;
        uint32_t attr;
        uint32_t option;
    };

    struct EeSemaStatus
    {
        int32_t count;
        int32_t max_count;
        int32_t init_count;
        int32_t wait_threads;
        uint32_t attr;
        uint32_t option;
    };

    static_assert(sizeof(EeThreadStatusAbi) == 0x30u, "Unexpected ee_thread_status_t size.");
    static_assert(sizeof(EeThreadCreateAbi) == 0x24u, "Unexpected ee_thread_t size.");
    static_assert(sizeof(EeSemaStatus) == 0x18u, "Unexpected ee_sema_t size.");

    void setRegU32(R5900Context &ctx, int reg, uint32_t value)
    {
        SET_GPR_U32(&ctx, reg, value);
    }

    int32_t getRegS32(const R5900Context &ctx, int reg)
    {
        return static_cast<int32_t>(::getRegU32(&ctx, reg));
    }

    void writeGuestU32(uint8_t *rdram, uint32_t addr, uint32_t value)
    {
        std::memcpy(rdram + addr, &value, sizeof(value));
    }

    void writeGuestWords(uint8_t *rdram, uint32_t addr, const uint32_t *words, size_t count)
    {
        for (size_t i = 0; i < count; ++i)
        {
            writeGuestU32(rdram, addr + static_cast<uint32_t>(i * sizeof(uint32_t)), words[i]);
        }
    }

    uint32_t readGuestU32(const uint8_t *rdram, uint32_t addr)
    {
        uint32_t value = 0;
        std::memcpy(&value, rdram + addr, sizeof(value));
        return value;
    }

    bool callSyscall(uint32_t syscallNumber, uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        return dispatchNumericSyscall(syscallNumber, rdram, ctx, runtime);
    }

    void overrideReturnHandler(uint8_t *, R5900Context *ctx, PS2Runtime *)
    {
        setReturnU32(ctx, ::getRegU32(ctx, 4) + ::getRegU32(ctx, 5));
        ctx->pc = ::getRegU32(ctx, 31);
    }

    void overrideBrokenHandler(uint8_t *, R5900Context *ctx, PS2Runtime *)
    {
        setReturnU32(ctx, 0xDEADBEEFu);
        ctx->pc = 0x12345678u;
    }

    void overrideRecursiveFindAddressHandler(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        runtime->handleSyscall(rdram, ctx, 0x83u);
        ctx->pc = ::getRegU32(ctx, 31);
    }

    void overrideKsegCompareHandler(uint8_t *, R5900Context *ctx, PS2Runtime *)
    {
        auto getLowU64 = [](const R5900Context *cpu, int reg) -> uint64_t
        {
            return (reg == 0) ? 0u : static_cast<uint64_t>(_mm_extract_epi64(cpu->r[reg], 0));
        };
        auto setLowS32 = [](R5900Context *cpu, int reg, uint32_t value)
        {
            SET_GPR_S32(cpu, reg, value);
        };
        auto setLowU64 = [](R5900Context *cpu, int reg, uint64_t value)
        {
            SET_GPR_U64(cpu, reg, value);
        };

        const uint32_t nextA0 = static_cast<uint32_t>(::getRegU32(ctx, 4) + 4u);
        setLowS32(ctx, 4, nextA0);
        setLowU64(ctx, 2, (getLowU64(ctx, 4) < getLowU64(ctx, 5)) ? 1u : 0u);
        if (getLowU64(ctx, 2) == 0u)
        {
            ctx->r[4] = _mm_setzero_si128();
        }
        setLowU64(ctx, 2, getLowU64(ctx, 4));
        ctx->pc = ::getRegU32(ctx, 31);
    }

    constexpr uint64_t K_EXPECTED_UPPER64 = 0x1122334455667788ull;

    void overridePreserveUpper64Handler(uint8_t *, R5900Context *ctx, PS2Runtime *)
    {
        const uint64_t hi = static_cast<uint64_t>(_mm_extract_epi64(ctx->r[4], 1));
        const uint64_t low = static_cast<uint64_t>(_mm_extract_epi64(ctx->r[4], 0));
        const uint64_t expectedLow = static_cast<uint64_t>(static_cast<int64_t>(static_cast<int32_t>(0x80000000u)));
        setReturnU32(ctx, (hi == K_EXPECTED_UPPER64 && low == expectedLow) ? 1u : 0u);
        ctx->pc = ::getRegU32(ctx, 31);
    }

    constexpr uint32_t K_OVERRIDE_ENTRY = 0x300500u;
    constexpr uint32_t K_OVERRIDE_RESUME = 0x300504u;
    constexpr uint32_t K_OVERRIDE_BLOCK_ENTRY = 0x300510u;
    constexpr uint32_t K_OVERRIDE_BLOCK_HANDLER = 0x300520u;
    constexpr uint32_t K_OVERRIDE_BLOCK_HANDLER_RESUME = 0x300524u;
    constexpr uint32_t K_OVERRIDE_BLOCK_DRIVER = 0x300530u;
    constexpr uint32_t K_OVERRIDE_BLOCK_BASE_RESUME = 0x300540u;
    constexpr uint32_t K_EXIT_MAIN = 0x300600u;
    constexpr uint32_t K_EXIT_HANDLER_A = 0x300610u;
    constexpr uint32_t K_EXIT_HANDLER_B = 0x300620u;
    constexpr uint32_t K_EXIT_OBSERVER = 0x300630u;
    uint32_t gOverrideSyscall = 0u;
    R5900Context gOverrideResult{};
    std::vector<int> gInvocationTrace;

    // Observe real scheduler transitions, not a register-copy helper. COP1 and
    // GPR sentinels distinguish shared VU hardware from saved EE thread state.
    std::vector<R5900Context> gVuBankObservations;
    int gVuBankWorker = 0;
    constexpr uint32_t K_VU_BANK_ENTRY = 0x301000u;
    constexpr uint32_t K_VU_BANK_CALLBACK = 0x301010u;
    constexpr uint32_t K_VU_BANK_RESUME = 0x301020u;
    constexpr uint32_t K_VU_BANK_NESTED_RESUME = 0x301030u;
    void seedVuBank(R5900Context &ctx, uint32_t seed)
    {
        ctx.vu0_vf[7] = _mm_set_ps(float(seed + 3), float(seed + 2), float(seed + 1), float(seed));
        ctx.vi[3] = static_cast<uint16_t>(seed);
        ctx.vu0_q = float(seed + 4);
        ctx.vu0_i = float(seed + 5);
        ctx.vu0_p = float(seed + 6);
        ctx.vu0_acc = _mm_set1_ps(float(seed + 7));
        ctx.vu0_r = _mm_castsi128_ps(_mm_set1_epi32(seed + 8));
        ctx.vu0_status = static_cast<uint16_t>(seed + 9);
        ctx.vu0_mac_flags = seed + 10;
        ctx.vu0_clip_flags = seed + 11;
        ctx.vu0_cmsar0 = seed + 12;
        ctx.vu0_tpc = (seed + 13) * 8;
    }
    void checkVuBank(TestCase &t, const R5900Context &ctx, uint32_t seed)
    {
        alignas(16) float lanes[4];
        _mm_store_ps(lanes, ctx.vu0_vf[7]);
        for (uint32_t lane = 0; lane < 4; ++lane)
            t.Equals(lanes[lane], float(seed + lane), "VF lanes survive execution-context changes");
        t.Equals(uint32_t(ctx.vi[3]), seed, "VI is shared hardware");
        t.Equals(ctx.vu0_q, float(seed + 4), "Q survives context change");
        t.Equals(ctx.vu0_i, float(seed + 5), "I survives context change");
        t.Equals(ctx.vu0_p, float(seed + 6), "P survives context change");
        t.Equals(_mm_cvtss_f32(ctx.vu0_acc), float(seed + 7), "ACC survives context change");
        t.Equals(uint32_t(_mm_cvtsi128_si32(_mm_castps_si128(ctx.vu0_r))), seed + 8, "R bits survive context change");
        t.Equals(uint32_t(ctx.vu0_status), seed + 9, "STATUS survives context change");
        t.Equals(ctx.vu0_mac_flags, seed + 10, "MAC survives context change");
        t.Equals(ctx.vu0_clip_flags, seed + 11, "CLIP survives context change");
        t.Equals(ctx.vu0_cmsar0, seed + 12, "CMSAR0 survives context change");
        t.Equals(ctx.vu0_tpc, (seed + 13) * 8, "TPC survives context change");
    }

    void schedulerOverrideEntry(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        ctx->pc = K_OVERRIDE_RESUME;
        runtime->handleSyscall(rdram, ctx, gOverrideSyscall);
    }

    void schedulerOverrideResume(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        gOverrideResult = *ctx;
        ctx->pc = 0u;
        runtime->requestStop();
    }

    void schedulerBlockingOverrideEntry(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        gInvocationTrace.push_back(1);
        EeThreadCreateParams driver{};
        driver.entry = K_OVERRIDE_BLOCK_DRIVER;
        driver.stack = 0x1E000u;
        driver.stackSize = 0x1000u;
        driver.priority = 10;
        const int driverId = runtime->eeScheduler().createThread(driver);
        runtime->eeScheduler().startThread(driverId, 0u, *ctx, false);
        ctx->pc = K_OVERRIDE_BLOCK_BASE_RESUME;
        runtime->handleSyscall(rdram, ctx, gOverrideSyscall);
    }

    void schedulerBlockingOverrideHandler(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        gInvocationTrace.push_back(2);
        ctx->pc = K_OVERRIDE_BLOCK_HANDLER_RESUME;
        SleepThread(rdram, ctx, runtime);
    }

    void schedulerBlockingOverrideHandlerResume(uint8_t *, R5900Context *ctx, PS2Runtime *)
    {
        gInvocationTrace.push_back(4);
        setReturnU32(ctx, 0xB10C0EDu);
        ctx->pc = 0u;
    }

    void schedulerBlockingOverrideDriver(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        gInvocationTrace.push_back(3);
        ctx->pc = 0u;
        runtime->eeScheduler().wakeupThread(EeScheduler::kMainThreadId, false);
        runtime->eeScheduler().transferIfRequested(false);
    }

    void schedulerBlockingOverrideBaseResume(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        gInvocationTrace.push_back(5);
        gOverrideResult = *ctx;
        ctx->pc = 0u;
        runtime->requestStop();
    }

    void schedulerExitHandlerA(uint8_t *, R5900Context *ctx, PS2Runtime *)
    {
        gInvocationTrace.push_back(getRegS32(*ctx, 4));
        ctx->pc = 0u;
    }

    void schedulerExitHandlerB(uint8_t *, R5900Context *ctx, PS2Runtime *)
    {
        gInvocationTrace.push_back(getRegS32(*ctx, 4));
        ctx->pc = 0u;
    }

    void schedulerExitObserver(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        const GuestThread *main = runtime->eeScheduler().thread(EeScheduler::kMainThreadId);
        gInvocationTrace.push_back(main && main->status == EeThreadStatus::Dormant ? 40 : -40);
        ctx->pc = 0u;
        runtime->requestStop();
    }

    void schedulerExitMain(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        gInvocationTrace.push_back(10);
        EeThreadCreateParams observer{};
        observer.entry = K_EXIT_OBSERVER;
        observer.stack = 0x1F000u;
        observer.stackSize = 0x1000u;
        observer.priority = 10;
        const int observerId = runtime->eeScheduler().createThread(observer);
        runtime->eeScheduler().startThread(observerId, 0u, *ctx, false);
        runtime->addEeExitHandler(EeScheduler::kMainThreadId, K_EXIT_HANDLER_A, 20u);
        runtime->addEeExitHandler(EeScheduler::kMainThreadId, K_EXIT_HANDLER_B, 30u);
        ExitThread(rdram, ctx, runtime);
    }

    void alarmNoopHandler(uint8_t *, R5900Context *ctx, PS2Runtime *)
    {
        ctx->pc = 0u;
    }

    constexpr uint32_t K_SCHED_MAIN = 0x300000u;
    constexpr uint32_t K_SCHED_A = 0x300100u;
    constexpr uint32_t K_SCHED_A_RESUME = 0x300104u;
    constexpr uint32_t K_SCHED_B = 0x300200u;
    constexpr uint32_t K_SCHED_B_RESUME = 0x300204u;
    constexpr uint32_t K_SCHED_HIGH = 0x300300u;
    constexpr uint32_t K_SCHED_SIGNAL = 0x300400u;
    constexpr uint32_t K_SCHED_SIGNAL_RESUME = 0x300404u;

    std::vector<int> *gSchedulerTrace = nullptr;
    int gSchedulerCreatedId = 0;
    int gSchedulerSemaphoreId = 0;
    int gSchedulerWaitResultA = 0;
    int gSchedulerWaitResultB = 0;
    std::atomic<int> gGuestActive{0};
    std::atomic<int> gGuestMaxActive{0};
    std::atomic<size_t> gGuestExecutorHash{0u};
    std::atomic<bool> gGuestExecutorMismatch{false};
    std::atomic<bool> gGuestExecutingFlagMissing{false};

    struct GuestExecutionProbe
    {
        explicit GuestExecutionProbe(PS2Runtime *runtime)
        {
            const int active = gGuestActive.fetch_add(1, std::memory_order_acq_rel) + 1;
            int maximum = gGuestMaxActive.load(std::memory_order_acquire);
            while (active > maximum &&
                   !gGuestMaxActive.compare_exchange_weak(maximum, active, std::memory_order_acq_rel))
            {
            }
            const size_t hash = std::hash<std::thread::id>{}(std::this_thread::get_id());
            size_t expected = 0u;
            if (!gGuestExecutorHash.compare_exchange_strong(expected, hash, std::memory_order_acq_rel) &&
                expected != hash)
            {
                gGuestExecutorMismatch.store(true, std::memory_order_release);
            }
            if (!runtime->eeScheduler().isExecutingGuest())
            {
                gGuestExecutingFlagMissing.store(true, std::memory_order_release);
            }
        }

        ~GuestExecutionProbe()
        {
            gGuestActive.fetch_sub(1, std::memory_order_acq_rel);
        }
    };

    void schedulerMainExit(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        GuestExecutionProbe probe(runtime);
        gSchedulerTrace->push_back(1);
        ExitThread(rdram, ctx, runtime);
    }

    void schedulerTraceA(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        GuestExecutionProbe probe(runtime);
        gSchedulerTrace->push_back(10);
        ctx->pc = 0u;
        if (gSchedulerTrace->size() >= 4u)
        {
            runtime->requestStop();
        }
    }

    void schedulerTraceB(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        GuestExecutionProbe probe(runtime);
        gSchedulerTrace->push_back(20);
        ctx->pc = 0u;
        if (gSchedulerTrace->size() >= 4u)
        {
            runtime->requestStop();
        }
    }

    void schedulerRotateA(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        gSchedulerTrace->push_back(10);
        ctx->pc = K_SCHED_A_RESUME;
        setRegU32(*ctx, 4, 5u);
        RotateThreadReadyQueue(rdram, ctx, runtime);
    }

    void schedulerRotateAResume(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        gSchedulerTrace->push_back(11);
        ctx->pc = 0u;
        runtime->requestStop();
    }

    void schedulerPreemptLow(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        gSchedulerTrace->push_back(30);
        ctx->pc = K_SCHED_A_RESUME;
        setRegU32(*ctx, 4, static_cast<uint32_t>(gSchedulerCreatedId));
        setRegU32(*ctx, 5, 0u);
        StartThread(rdram, ctx, runtime);
    }

    void schedulerPreemptLowResume(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        gSchedulerTrace->push_back(31);
        ctx->pc = 0u;
        runtime->requestStop();
    }

    void schedulerHigh(uint8_t *, R5900Context *ctx, PS2Runtime *)
    {
        gSchedulerTrace->push_back(5);
        ctx->pc = 0u;
    }

    void schedulerWaitA(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        if (ctx->pc == K_SCHED_A)
        {
            gSchedulerTrace->push_back(10);
            ctx->pc = K_SCHED_A_RESUME;
            setRegU32(*ctx, 4, static_cast<uint32_t>(gSchedulerSemaphoreId));
            WaitSema(rdram, ctx, runtime);
            return;
        }
        gSchedulerWaitResultA = getRegS32(*ctx, 2);
        gSchedulerTrace->push_back(11);
        ctx->pc = 0u;
    }

    void schedulerWaitB(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        if (ctx->pc == K_SCHED_B)
        {
            gSchedulerTrace->push_back(20);
            ctx->pc = K_SCHED_B_RESUME;
            setRegU32(*ctx, 4, static_cast<uint32_t>(gSchedulerSemaphoreId));
            WaitSema(rdram, ctx, runtime);
            return;
        }
        gSchedulerWaitResultB = getRegS32(*ctx, 2);
        gSchedulerTrace->push_back(21);
        ctx->pc = 0u;
        runtime->requestStop();
    }

    void schedulerSignalTwice(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        if (ctx->pc == K_SCHED_SIGNAL)
        {
            gSchedulerTrace->push_back(30);
            ctx->pc = K_SCHED_SIGNAL_RESUME;
            setRegU32(*ctx, 4, static_cast<uint32_t>(gSchedulerSemaphoreId));
            SignalSema(rdram, ctx, runtime);
            return;
        }
        gSchedulerTrace->push_back(31);
        setRegU32(*ctx, 4, static_cast<uint32_t>(gSchedulerSemaphoreId));
        SignalSema(rdram, ctx, runtime);
        ctx->pc = 0u;
        runtime->requestStop();
    }

    constexpr uint32_t K_EVENT_FIFO_MAIN = 0x301000u;
    constexpr uint32_t K_EVENT_FIFO_A = 0x301010u;
    constexpr uint32_t K_EVENT_FIFO_A_RESUME = 0x301014u;
    constexpr uint32_t K_EVENT_FIFO_B = 0x301020u;
    constexpr uint32_t K_EVENT_FIFO_B_RESUME = 0x301024u;
    constexpr uint32_t K_EVENT_FIFO_SIGNAL = 0x301030u;
    constexpr uint32_t K_EVENT_FIFO_SIGNAL_AGAIN = 0x301034u;
    constexpr uint32_t K_EVENT_FIFO_DONE = 0x301038u;
    constexpr uint32_t K_EVENT_FIFO_RESULT_A = 0x1A00u;
    constexpr uint32_t K_EVENT_FIFO_RESULT_B = 0x1A04u;
    constexpr uint32_t WEF_OR = 0x01u;
    constexpr uint32_t WEF_CLEAR = 0x10u;
    constexpr uint32_t WEF_CLEAR_ALL = 0x20u;
    int gEventFifoId = 0;
    std::vector<int> gEventFifoTrace;

    void schedulerEventFifoWaitA(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        if (ctx->pc == K_EVENT_FIFO_A)
        {
            gEventFifoTrace.push_back(1);
            ctx->pc = K_EVENT_FIFO_A_RESUME;
            runtime->eeScheduler().waitEventFlag(gEventFifoId, 1u, WEF_OR | WEF_CLEAR,
                                                  K_EVENT_FIFO_RESULT_A);
        }
        gEventFifoTrace.push_back(4);
        ctx->pc = 0u;
    }

    void schedulerEventFifoWaitB(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        if (ctx->pc == K_EVENT_FIFO_B)
        {
            gEventFifoTrace.push_back(2);
            ctx->pc = K_EVENT_FIFO_B_RESUME;
            runtime->eeScheduler().waitEventFlag(gEventFifoId, 1u, WEF_OR | WEF_CLEAR,
                                                  K_EVENT_FIFO_RESULT_B);
        }
        gEventFifoTrace.push_back(6);
        ctx->pc = 0u;
    }

    void schedulerEventFifoSignal(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        gEventFifoTrace.push_back(3);
        ctx->pc = K_EVENT_FIFO_SIGNAL_AGAIN;
        runtime->eeScheduler().setEventFlag(gEventFifoId, 1u, false);
        runtime->eeScheduler().transferIfRequested(false);
    }

    void schedulerEventFifoSignalAgain(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        gEventFifoTrace.push_back(5);
        ctx->pc = K_EVENT_FIFO_DONE;
        runtime->eeScheduler().setEventFlag(gEventFifoId, 1u, false);
        runtime->eeScheduler().transferIfRequested(false);
    }

    void schedulerEventFifoDone(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        gEventFifoTrace.push_back(7);
        ctx->pc = 0u;
        runtime->requestStop();
    }

    void schedulerEventFifoMain(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        EeScheduler &scheduler = runtime->eeScheduler();
        gEventFifoId = scheduler.createEventFlag(0u, 0x02u, 0u);
        const auto create = [&](uint32_t entry, uint32_t stack, int priority)
        {
            EeThreadCreateParams params{};
            params.entry = entry;
            params.stack = stack;
            params.stackSize = 0x800u;
            params.priority = priority;
            const int id = scheduler.createThread(params);
            scheduler.startThread(id, 0u, *ctx, false);
        };
        create(K_EVENT_FIFO_A, 0x21000u, 5);
        create(K_EVENT_FIFO_B, 0x22000u, 5);
        create(K_EVENT_FIFO_SIGNAL, 0x23000u, 10);
        ctx->pc = 0u;
    }

    struct TestEnv
    {
        std::vector<uint8_t> rdram;
        R5900Context ctx{};
        PS2Runtime runtime;

        TestEnv() : rdram(PS2_RAM_SIZE, 0)
        {
            std::memset(&ctx, 0, sizeof(ctx));
        }
    };
}

void register_ps2_runtime_kernel_tests()
{
    MiniTest::Case("PS2RuntimeKernel", [](TestCase &tc)
    {
        tc.Run("call snapshot plan captures walking and aiming boundaries once", [](TestCase &t) {
            PS2CallCapturePlan plan;
            t.IsTrue(plan.configure("6650,7390", 0), "two increasing field bounds accepted");
            t.IsFalse(plan.due(6649), "walking snapshot cannot fire early");
            t.IsTrue(plan.due(6651), "a later actual call remains eligible");
            t.Equals(plan.consume(), uint64_t{6650}, "record requested field separately from actual field");
            t.IsFalse(plan.due(6651), "the same field does not trigger aiming capture");
            t.IsTrue(plan.due(7390), "aiming bound becomes eligible");
            t.Equals(plan.consume(), uint64_t{7390}, "second capture has a unique suffix");
            t.IsFalse(plan.due(UINT64_MAX), "completed plan cannot repeatedly dump RAM");
        });
        tc.Run("call snapshot plan preserves legacy one-shot behavior", [](TestCase &t) {
            PS2CallCapturePlan plan;
            t.IsTrue(plan.configure("", 53), "missing list uses original capture-from field");
            t.IsFalse(plan.due(52), "legacy lower bound honored");
            t.Equals(plan.consume(), uint64_t{53}, "legacy requested field retained");
            t.IsFalse(plan.due(100), "legacy capture remains one-shot");
        });
        tc.Run("invalid or excessive snapshot lists disable capture instead of dumping unexpectedly", [](TestCase &t) {
            for (const auto text : {"1,1", "2,1", "1,", ",1", "1, 2", "-1", "abc", "18446744073709551616", "1,2,3,4,5,6,7,8,9"}) {
                PS2CallCapturePlan plan;
                t.IsFalse(plan.configure(text, 0), "bad list must be rejected");
                t.IsFalse(plan.due(UINT64_MAX), "bad list cannot fall back to an unrelated capture");
            }
        });
        tc.Run("DECI2 Release writes complete through guest callbacks exactly once", [](TestCase &t)
        {
            TestEnv env;
            constexpr uint32_t handler = 0x200200u;
            R5900Context main{};
            env.runtime.eeScheduler().reset(env.rdram.data(), main);
            env.runtime.registerFunction(handler, [](uint8_t *ram, R5900Context *ctx, PS2Runtime *runtime)
            {
                const uint32_t event = ::getRegU32(ctx, 4);
                const uint32_t opt = ::getRegU32(ctx, 6);
                writeGuestU32(ram, opt + 4u, readGuestU32(ram, opt + 4u) * 10u + event);
                writeGuestU32(ram, opt + 8u, ::getRegU32(ctx, 28));
                const uint32_t ra = ::getRegU32(ctx, 31);
                if (event == 3u)
                {
                    const uint32_t args[] = {readGuestU32(ram, opt), 0x1800u, 4u, 0u};
                    writeGuestWords(ram, 0x1600u, args, 4u);
                    setRegU32(*ctx, 4, uint32_t(-6)); setRegU32(*ctx, 5, 0x1600u);
                    Deci2Call(ram, ctx, runtime);
                    writeGuestU32(ram, opt + 16u, ::getRegU32(ctx, 2));
                }
                else if (event == 4u)
                {
                    writeGuestU32(ram, opt + 12u, 0u);
                    runtime->eeScheduler().requestStop();
                }
                ctx->pc = ra;
            });
            auto call = [&](int code, std::array<uint32_t, 4> args)
            {
                writeGuestWords(env.rdram.data(), 0x1500u, args.data(), args.size());
                setRegU32(env.ctx, 4, uint32_t(code)); setRegU32(env.ctx, 5, 0x1500u);
                Deci2Call(env.rdram.data(), &env.ctx, &env.runtime);
                return getRegS32(env.ctx, 2);
            };
            setRegU32(env.ctx, 28, 0x123400u);
            const int socket = call(1, {0x210u, 0x1700u, handler, 0u});
            const int other = call(1, {0x210u, 0x1780u, handler, 0u});
            t.IsTrue(socket > 0 && other > socket, "distinct sockets");
            writeGuestU32(env.rdram.data(), 0x1700u, uint32_t(socket));
            writeGuestU32(env.rdram.data(), 0x170Cu, 1u);
            writeGuestU32(env.rdram.data(), 0x1800u, 0x214B4F54u);
            t.Equals(call(3, {uint32_t(socket), 'H', 0u, 0u}), 0, "request accepted");
            t.Equals(readGuestU32(env.rdram.data(), 0x170Cu), 1u, "no premature completion");
            t.Equals(call(3, {uint32_t(socket), 'H', 0u, 0u}), -7, "pending request cannot be duplicated");
            t.Equals(call(4, {uint32_t(socket), 0u, 0u, 0u}), 0, "poll queues write");
            call(4, {uint32_t(socket), 0u, 0u, 0u}); // does not queue a duplicate
            env.runtime.eeScheduler().run();
            t.Equals(readGuestU32(env.rdram.data(), 0x1704u), 34u, "WRITE precedes WRITE_DONE exactly once");
            t.Equals(readGuestU32(env.rdram.data(), 0x1708u), 0x123400u, "callback retains registered GP");
            t.Equals(readGuestU32(env.rdram.data(), 0x170Cu), 0u, "guest callback clears busy flag");
            t.Equals(readGuestU32(env.rdram.data(), 0x1710u), 4u, "all text bytes accepted");
            t.Equals(call(-6, {uint32_t(socket), PS2_RAM_SIZE - 2u, 4u, 0u}), -5, "cross-boundary send rejected");
            t.Equals(call(2, {uint32_t(socket), 0u, 0u, 0u}), 0, "close succeeds");
            t.Equals(call(4, {uint32_t(socket), 0u, 0u, 0u}), -2, "closed socket rejected");
            TestEnv isolated;
            writeGuestWords(isolated.rdram.data(), 0x1500u, std::array<uint32_t,4>{uint32_t(other),0u,0u,0u}.data(),4u);
            setRegU32(isolated.ctx, 4, 4u); setRegU32(isolated.ctx, 5, 0x1500u);
            Deci2Call(isolated.rdram.data(), &isolated.ctx, &isolated.runtime);
            t.Equals(getRegS32(isolated.ctx, 2), -2, "sessions are runtime-owned");
            setRegU32(isolated.ctx, 4, 2u);
            Deci2Call(isolated.rdram.data(), &isolated.ctx, &isolated.runtime);
            t.Equals(getRegS32(isolated.ctx, 2), -1, "other runtime cannot close a session");
            setRegU32(env.ctx, 4, 4u); setRegU32(env.ctx, 5, PS2_RAM_SIZE - 2u);
            Deci2Call(env.rdram.data(), &env.ctx, &env.runtime);
            t.Equals(getRegS32(env.ctx, 2), -5, "truncated argument is rejected");
            t.Equals(call(4, {uint32_t(other), 0u, 0u, 0u}), 0, "foreign close preserved the owner's session");
        });
        tc.Run("queued SIF command packets preserve native game heap and their own bytes", [](TestCase &t)
        {
            TestEnv env;
            constexpr uint32_t handler = 0x00200100u;
            env.runtime.registerFunction(handler, [](uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
            {
                const uint32_t packet = ::getRegU32(ctx, 4);
                const uint32_t value = readGuestU32(rdram, packet + 12u);
                const uint32_t slot = readGuestU32(rdram, 0x1800u);
                writeGuestU32(rdram, 0x1810u + slot * 12u, value);
                writeGuestU32(rdram, 0x1814u + slot * 12u, packet);
                writeGuestU32(rdram, 0x1818u + slot * 12u, ::getRegU32(ctx, 29));
                writeGuestU32(rdram, 0x1800u, slot + 1u);
                if (slot == 1u) runtime->eeScheduler().requestStop();
                ctx->pc = ::getRegU32(ctx, 31);
            });
            R5900Context main{};
            env.runtime.eeScheduler().reset(env.rdram.data(), main);
            setRegU32(env.ctx, 4, 0x44u);
            setRegU32(env.ctx, 5, handler);
            setRegU32(env.ctx, 6, 0u);
            ps2_stubs::sceSifAddCmdHandler(env.rdram.data(), &env.ctx, &env.runtime);
            // Model a native allocator owning the same address the host heap
            // would hand out next, as observed for RE4's MODULES.DAT buffer.
            const uint32_t nativeBuffer = env.runtime.guestMalloc(128u, 16u);
            env.runtime.guestFree(nativeBuffer);
            std::memset(env.rdram.data() + nativeBuffer, 0x5Au, 128u);
            std::array<uint32_t, 4> packet{16u, 0u, 0x44u, 0x11223344u};
            t.IsTrue(ps2_stubs::dispatchSifCommand(env.rdram.data(), &env.runtime, 0x44u, packet.data(), sizeof(packet)),
                     "first command queued");
            packet[3] = 0x55667788u;
            t.IsTrue(ps2_stubs::dispatchSifCommand(env.rdram.data(), &env.runtime, 0x44u, packet.data(), sizeof(packet)),
                     "second command queued");
            packet.fill(0u); // Caller storage dies before either callback executes.
            env.runtime.eeScheduler().run();
            t.Equals(readGuestU32(env.rdram.data(), 0x1800u), 2u, "both callbacks executed");
            t.Equals(readGuestU32(env.rdram.data(), 0x1810u), 0x11223344u, "first payload retained");
            t.Equals(readGuestU32(env.rdram.data(), 0x181Cu), 0x55667788u, "second payload retained");
            for (uint32_t slot = 0; slot < 2u; ++slot)
            {
                const uint32_t address = readGuestU32(env.rdram.data(), 0x1814u + slot * 12u);
                const uint32_t stack = readGuestU32(env.rdram.data(), 0x1818u + slot * 12u);
                t.IsTrue(stack + 16u <= address && address < PS2_RAM_SIZE - 16u,
                         "packet lives above the callback's argument save area");
            }
            t.IsTrue(std::all_of(env.rdram.begin() + nativeBuffer, env.rdram.begin() + nativeBuffer + 128u,
                                [](uint8_t value) { return value == 0x5Au; }), "native allocation is untouched");
        });
        tc.Run("sparse generated functions resolve outside dense RAM", [](TestCase &t)
        {
            TestEnv env;
            t.IsTrue(env.runtime.hasFunction(0x80075000u), "first sparse entry is callable");
            t.IsTrue(env.runtime.hasFunction(0x80076000u), "last sparse entry is callable");
            t.IsTrue(!env.runtime.hasFunction(0x80075004u), "lookup remains exact");
            t.IsTrue(!env.runtime.hasFunction(0x80075001u), "unaligned address is absent");
            t.IsTrue(!env.runtime.hasFunction(0x80074000u), "address before sparse range is absent");
            t.IsTrue(!env.runtime.hasFunction(0x80077000u), "address after sparse range is absent");
            env.runtime.lookupFunction(0x80075000u)(env.rdram.data(), &env.ctx, &env.runtime);
            t.Equals(env.ctx.pc, 0x1234u, "first sparse function actually executes");
            env.runtime.lookupFunction(0x80076000u)(env.rdram.data(), &env.ctx, &env.runtime);
            t.Equals(env.ctx.pc, 0x5678u, "last sparse function actually executes");
        });

        tc.Run("unsigned loads and ABI word writes extend independently", [](TestCase &t)
        {
            constexpr uint64_t kUpper = 0x1122334455667788ull;
            R5900Context ctx{};
            ctx.r[2] = _mm_set_epi64x(static_cast<int64_t>(kUpper), 0);

            SET_GPR_ZE32(&ctx, 2, 0x80000000u);
            t.Equals(static_cast<uint64_t>(_mm_extract_epi64(ctx.r[2], 0)),
                     0x0000000080000000ull,
                     "SET_GPR_ZE32 must zero-extend values used by LWU/LHU/LBU");
            t.Equals(static_cast<uint64_t>(_mm_extract_epi64(ctx.r[2], 1)),
                     kUpper,
                     "SET_GPR_ZE32 must preserve the upper 64 bits of the 128-bit GPR");

            SET_GPR_U32(&ctx, 2, 0x80000000u);
            t.Equals(static_cast<uint64_t>(_mm_extract_epi64(ctx.r[2], 0)),
                     0xFFFFFFFF80000000ull,
                     "SET_GPR_U32 must retain the existing EE 32-bit ABI extension semantics");
            t.Equals(static_cast<uint64_t>(_mm_extract_epi64(ctx.r[2], 1)),
                     kUpper,
                     "SET_GPR_U32 must preserve the upper 64 bits of the 128-bit GPR");
        });

        tc.Run("CreateThread and CreateSema decode the exact PS2SDK EE layouts", [](TestCase &t)
        {
            TestEnv env;
            EeThreadCreateAbi threadParam{};
            threadParam.status = 0x11111111;
            threadParam.func = K_SCHED_HIGH;
            threadParam.stack = 0x00018000u;
            threadParam.stack_size = 0x1000;
            threadParam.gp_reg = 0x00123400u;
            threadParam.initial_priority = 37;
            threadParam.current_priority = 99;
            threadParam.attr = 0xABCDEF01u;
            threadParam.option = 0x10203040u;
            std::memcpy(env.rdram.data() + K_PARAM_ADDR, &threadParam, sizeof(threadParam));

            setRegU32(env.ctx, 4, K_PARAM_ADDR);
            CreateThread(env.rdram.data(), &env.ctx, &env.runtime);
            const int threadId = getRegS32(env.ctx, 2);
            const GuestThread *thread = env.runtime.eeScheduler().thread(threadId);
            t.IsTrue(threadId >= 2 && thread != nullptr, "the EE descriptor should create a guest thread");
            t.Equals(thread->entry, threadParam.func, "func must be decoded from offset 0x04");
            t.Equals(thread->stack, threadParam.stack, "stack must be decoded from offset 0x08");
            t.Equals(thread->stackSize, static_cast<uint32_t>(threadParam.stack_size),
                     "stack_size must be decoded from offset 0x0C");
            t.Equals(thread->gp, threadParam.gp_reg, "gp_reg must be decoded from offset 0x10");
            t.Equals(thread->initialPriority, threadParam.initial_priority,
                     "initial_priority must be decoded from offset 0x14");
            t.Equals(thread->currentPriority, threadParam.initial_priority,
                     "a new thread starts at its initial priority, not the status-only current_priority field");
            t.Equals(thread->attr, threadParam.attr, "attr must be decoded from offset 0x1C");
            t.Equals(thread->option, threadParam.option, "option must be decoded from offset 0x20");
            t.IsTrue(thread->status == EeThreadStatus::Dormant, "a newly created EE thread must be dormant");

            setRegU32(env.ctx, 4, PS2_RAM_SIZE - static_cast<uint32_t>(sizeof(EeThreadCreateAbi)) + 4u);
            CreateThread(env.rdram.data(), &env.ctx, &env.runtime);
            t.Equals(getRegS32(env.ctx, 2), KE_ERROR,
                     "the entire EE descriptor must fit in a valid guest range");

            EeSemaStatus semaParam{};
            semaParam.count = 91;
            semaParam.max_count = 7;
            semaParam.init_count = 3;
            semaParam.wait_threads = 82;
            semaParam.attr = 0x55667788u;
            semaParam.option = 0x99AABBCCu;
            std::memcpy(env.rdram.data() + K_PARAM_ADDR, &semaParam, sizeof(semaParam));
            setRegU32(env.ctx, 4, K_PARAM_ADDR);
            CreateSema(env.rdram.data(), &env.ctx, &env.runtime);
            const int semaId = getRegS32(env.ctx, 2);
            const EeSemaphore *semaphore = env.runtime.eeScheduler().semaphore(semaId);
            t.IsTrue(semaId > 0 && semaphore != nullptr, "the EE semaphore descriptor should create an object");
            t.Equals(semaphore->count, semaParam.init_count,
                     "CreateSema must use init_count at offset 0x08, not the status count field");
            t.Equals(semaphore->maxCount, semaParam.max_count, "max_count must be decoded from offset 0x04");
            t.Equals(semaphore->attr, semaParam.attr, "semaphore attr must be decoded from offset 0x10");
            t.Equals(semaphore->option, semaParam.option, "semaphore option must be decoded from offset 0x14");
        });

        tc.Run("EE kernel accepts reserved priority zero and restores the original priority", [](TestCase &t)
        {
            TestEnv env;
            auto &ee = env.runtime.eeScheduler();
            ee.reset(env.rdram.data(), env.ctx);
            const int internal = ee.createThread(EeThreadCreateParams{0, 0x200400u, 0x20000u, 0x800u, 0, 0, 0});
            t.IsTrue(internal > 1, "libkernel internal priority-zero thread can be created");
            if (internal <= 1) return;
            t.Equals(ee.thread(internal)->initialPriority, 0, "priority zero is retained");
            int old = -1;
            t.Equals(ee.changePriority(1, 24, false, old), 0, "temporary priority change succeeds");
            t.Equals(old, 0, "original priority is recorded");
            t.Equals(ee.changePriority(1, 0, false, old), 0, "restore priority zero succeeds");
            t.Equals(old, 24, "temporary priority is returned");
            t.Equals(ee.thread(1)->currentPriority, 0, "main thread really restored");
            t.Equals(ee.thread(1)->initialPriority, 0, "initial priority remains stable");
            t.IsTrue(ee.createThread(EeThreadCreateParams{0, 0x200400u, 0x21000u, 0x800u, 0, -1, 0}) < 0, "negative priority rejected");
            t.IsTrue(ee.createThread(EeThreadCreateParams{0, 0x200400u, 0x21000u, 0x800u, 0, 128, 0}) < 0, "priority limit rejected");
        });
        tc.Run("EE priority syscalls return the saved priority for guest restoration", [](TestCase &t)
        {
            TestEnv env;
            auto &ee = env.runtime.eeScheduler();
            ee.reset(env.rdram.data(), env.ctx);
            auto change = [&](uint32_t syscall, int priority)
            {
                setRegU32(env.ctx, 3, syscall);
                setRegU32(env.ctx, 4, 0); // TH_SELF
                setRegU32(env.ctx, 5, static_cast<uint32_t>(priority));
                env.runtime.handleSyscall(env.rdram.data(), &env.ctx, 0);
                return getRegS32(env.ctx, 2);
            };
            t.Equals(change(0x29u, 24), 0, "first change returns boot priority zero");
            const int saved = change(0x29u, 1);
            t.Equals(saved, 24, "critical section saves the actual previous priority");
            t.Equals(change(0x29u, saved), 1, "restoration returns temporary priority");
            t.Equals(ee.thread(1)->currentPriority, 24, "guest restores priority 24, not success code zero");
            t.Equals(change(0x2Au, 16), 24, "positive interrupt syscall preserves return contract");
            t.Equals(change(static_cast<uint32_t>(-0x2A), 18), 16, "negative interrupt syscall preserves return contract");
            t.IsTrue(change(0x29u, 128) < 0, "invalid priority returns an error");
            t.Equals(ee.thread(1)->currentPriority, 18, "failed change leaves priority intact");
        });
        tc.Run("EE scheduler selects absolute priority then FIFO", [](TestCase &t)
        {
            TestEnv env;
            std::vector<int> trace;
            gSchedulerTrace = &trace;
            gGuestActive.store(0, std::memory_order_release);
            gGuestMaxActive.store(0, std::memory_order_release);
            gGuestExecutorHash.store(0u, std::memory_order_release);
            gGuestExecutorMismatch.store(false, std::memory_order_release);
            gGuestExecutingFlagMissing.store(false, std::memory_order_release);
            env.runtime.registerFunction(K_SCHED_MAIN, schedulerMainExit);
            env.runtime.registerFunction(K_SCHED_A, schedulerTraceA);
            env.runtime.registerFunction(K_SCHED_B, schedulerTraceB);

            env.ctx.pc = K_SCHED_MAIN;
            EeScheduler &ee = env.runtime.eeScheduler();
            ee.reset(env.rdram.data(), env.ctx);
            const int lowA = ee.createThread(EeThreadCreateParams{0, K_SCHED_A, 0x20000u, 0x800u, 0, 20, 0});
            const int highA = ee.createThread(EeThreadCreateParams{0, K_SCHED_A, 0x21000u, 0x800u, 0, 5, 0});
            const int highB = ee.createThread(EeThreadCreateParams{0, K_SCHED_B, 0x22000u, 0x800u, 0, 5, 0});
            ee.startThread(lowA, 0, env.ctx, false);
            ee.startThread(highA, 0, env.ctx, false);
            ee.startThread(highB, 0, env.ctx, false);
            ee.run();

            t.Equals(trace.size(), size_t{4}, "all runnable contexts should execute once");
            t.Equals(trace[0], 1, "main priority zero executes first");
            t.Equals(trace[1], 10, "first priority-5 thread preserves FIFO order");
            t.Equals(trace[2], 20, "second priority-5 thread follows FIFO order");
            t.Equals(trace[3], 10, "priority-20 thread executes only after priority-5 queue drains");
            t.Equals(gGuestMaxActive.load(std::memory_order_acquire), 1,
                     "there must never be two simultaneous guest executions");
            t.IsFalse(gGuestExecutorMismatch.load(std::memory_order_acquire),
                      "all EE guest functions must execute on the single scheduler host thread");
            t.IsFalse(gGuestExecutingFlagMissing.load(std::memory_order_acquire),
                      "the scheduler must publish guest execution only around the active guest call");
        });

        tc.Run("VU0 bank flows into a callback and back without restoring stale EE copies", [](TestCase &t)
        {
            TestEnv env;
            gVuBankObservations.clear();
            env.runtime.registerFunction(K_VU_BANK_ENTRY, [](uint8_t *, R5900Context *ctx, PS2Runtime *runtime) {
                seedVuBank(*ctx, 11);
                ctx->f[4] = 17;
                SET_GPR_U32(ctx, 16, 123);
                ctx->pc = K_VU_BANK_RESUME;
                GuestInvocation invocation{};
                invocation.kind = GuestInvocationKind::HleCall;
                invocation.context.pc = K_VU_BANK_CALLBACK;
                invocation.context.f[4] = 39;
                SET_GPR_U32(&invocation.context, 16, 456);
                runtime->eeScheduler().invokeCurrent(std::move(invocation));
            });
            env.runtime.registerFunction(K_VU_BANK_CALLBACK, [](uint8_t *, R5900Context *ctx, PS2Runtime *) {
                gVuBankObservations.push_back(*ctx);
                seedVuBank(*ctx, 22);
                ctx->pc = 0;
            });
            env.runtime.registerFunction(K_VU_BANK_RESUME, [](uint8_t *, R5900Context *ctx, PS2Runtime *runtime) {
                gVuBankObservations.push_back(*ctx);
                ctx->pc = 0;
                runtime->requestStop();
            });
            env.ctx.pc = K_VU_BANK_ENTRY;
            env.runtime.eeScheduler().reset(env.rdram.data(), env.ctx);
            env.runtime.eeScheduler().run();
            t.Equals(gVuBankObservations.size(), size_t{2}, "callback and base both execute");
            if (gVuBankObservations.size() != 2) return;
            checkVuBank(t, gVuBankObservations[0], 11);
            checkVuBank(t, gVuBankObservations[1], 22);
            t.Equals(gVuBankObservations[0].f[4], 39.0f, "callback retains its own COP1 frame");
            t.Equals(gVuBankObservations[1].f[4], 17.0f, "base retains its own COP1 frame");
            t.Equals(getRegU32(&gVuBankObservations[0], 16), 456u, "callback retains its own GPR frame");
            t.Equals(getRegU32(&gVuBankObservations[1], 16), 123u, "base retains its own GPR frame");
            checkVuBank(t, env.runtime.cpu(), 22);
        });

        tc.Run("VU0 bank survives nested invocation vector growth and every unwind", [](TestCase &t)
        {
            TestEnv env;
            gVuBankObservations.clear();
            env.runtime.registerFunction(K_VU_BANK_ENTRY, [](uint8_t *, R5900Context *ctx, PS2Runtime *runtime) {
                seedVuBank(*ctx, 10);
                ctx->pc = K_VU_BANK_RESUME;
                GuestInvocation invocation{};
                invocation.context.pc = K_VU_BANK_CALLBACK;
                runtime->eeScheduler().invokeCurrent(std::move(invocation));
            });
            env.runtime.registerFunction(K_VU_BANK_CALLBACK, [](uint8_t *, R5900Context *ctx, PS2Runtime *runtime) {
                const uint32_t depth = getRegU32(ctx, 4);
                gVuBankObservations.push_back(*ctx);
                seedVuBank(*ctx, 11 + depth);
                ctx->pc = K_VU_BANK_NESTED_RESUME;
                if (depth < 15) {
                    GuestInvocation invocation{};
                    invocation.context.pc = K_VU_BANK_CALLBACK;
                    SET_GPR_U32(&invocation.context, 4, depth + 1);
                    runtime->eeScheduler().invokeCurrent(std::move(invocation));
                }
                ctx->pc = 0;
            });
            env.runtime.registerFunction(K_VU_BANK_NESTED_RESUME, [](uint8_t *, R5900Context *ctx, PS2Runtime *) {
                gVuBankObservations.push_back(*ctx);
                ctx->pc = 0;
            });
            env.runtime.registerFunction(K_VU_BANK_RESUME, [](uint8_t *, R5900Context *ctx, PS2Runtime *runtime) {
                gVuBankObservations.push_back(*ctx);
                ctx->pc = 0;
                runtime->requestStop();
            });
            env.ctx.pc = K_VU_BANK_ENTRY;
            env.runtime.eeScheduler().reset(env.rdram.data(), env.ctx);
            env.runtime.eeScheduler().run();
            t.Equals(gVuBankObservations.size(), size_t{32}, "16 entries and 16 resumed frames execute");
            if (gVuBankObservations.size() != 32) return;
            for (uint32_t i = 0; i < 16; ++i) checkVuBank(t, gVuBankObservations[i], 10 + i);
            for (uint32_t i = 16; i < 32; ++i) checkVuBank(t, gVuBankObservations[i], 26);
            checkVuBank(t, env.runtime.cpu(), 26);
        });

        tc.Run("VU0 bank crosses sleeping threads and survives ExitDeleteThread", [](TestCase &t)
        {
            TestEnv env;
            gVuBankObservations.clear();
            env.runtime.registerFunction(K_VU_BANK_ENTRY, [](uint8_t *ram, R5900Context *ctx, PS2Runtime *runtime) {
                seedVuBank(*ctx, 31);
                ctx->f[4] = 17;
                EeThreadCreateParams worker{};
                worker.entry = K_VU_BANK_CALLBACK;
                worker.stack = 0x24000;
                worker.stackSize = 0x1000;
                worker.priority = 10;
                gVuBankWorker = runtime->eeScheduler().createThread(worker);
                runtime->eeScheduler().startThread(gVuBankWorker, 0, *ctx, false);
                ctx->pc = K_VU_BANK_RESUME;
                SleepThread(ram, ctx, runtime);
            });
            env.runtime.registerFunction(K_VU_BANK_CALLBACK, [](uint8_t *, R5900Context *ctx, PS2Runtime *runtime) {
                gVuBankObservations.push_back(*ctx);
                seedVuBank(*ctx, 42);
                runtime->eeScheduler().wakeupThread(EeScheduler::kMainThreadId, true);
                runtime->eeScheduler().exitCurrent(true);
            });
            env.runtime.registerFunction(K_VU_BANK_RESUME, [](uint8_t *, R5900Context *ctx, PS2Runtime *runtime) {
                gVuBankObservations.push_back(*ctx);
                ctx->pc = 0;
                runtime->requestStop();
            });
            env.ctx.pc = K_VU_BANK_ENTRY;
            env.runtime.eeScheduler().reset(env.rdram.data(), env.ctx);
            env.runtime.eeScheduler().run();
            t.Equals(gVuBankObservations.size(), size_t{2}, "worker and resumed main execute");
            if (gVuBankObservations.size() != 2) return;
            checkVuBank(t, gVuBankObservations[0], 31);
            checkVuBank(t, gVuBankObservations[1], 42);
            t.Equals(gVuBankObservations[1].f[4], 17.0f, "sleeping main COP1 remains private");
            t.IsTrue(env.runtime.eeScheduler().thread(gVuBankWorker) == nullptr, "worker record was actually deleted");
            checkVuBank(t, env.runtime.cpu(), 42);
        });

        tc.Run("real INTC dispatch observes and publishes the same VU0 bank", [](TestCase &t)
        {
            TestEnv env;
            gVuBankObservations.clear();
            env.runtime.registerFunction(K_VU_BANK_ENTRY, [](uint8_t *, R5900Context *ctx, PS2Runtime *runtime) {
                seedVuBank(*ctx, 55);
                ctx->f[4] = 17;
                runtime->eeScheduler().addIrqHandler(false, 7u, K_VU_BANK_CALLBACK, true, 0xCAFEu, 0u, 0u);
                ctx->pc = K_VU_BANK_RESUME;
                runtime->eeScheduler().postEvent({EeEventType::Intc, 7u, 0u});
            });
            env.runtime.registerFunction(K_VU_BANK_CALLBACK, [](uint8_t *, R5900Context *ctx, PS2Runtime *) {
                gVuBankObservations.push_back(*ctx);
                seedVuBank(*ctx, 66);
                ctx->pc = 0;
            });
            env.runtime.registerFunction(K_VU_BANK_RESUME, [](uint8_t *, R5900Context *ctx, PS2Runtime *runtime) {
                gVuBankObservations.push_back(*ctx);
                ctx->pc = 0;
                runtime->requestStop();
            });
            env.ctx.pc = K_VU_BANK_ENTRY;
            env.runtime.eeScheduler().reset(env.rdram.data(), env.ctx);
            env.runtime.eeScheduler().run();
            t.Equals(gVuBankObservations.size(), size_t{2}, "INTC handler and interrupted frame both execute");
            if (gVuBankObservations.size() != 2) return;
            checkVuBank(t, gVuBankObservations[0], 55);
            checkVuBank(t, gVuBankObservations[1], 66);
            t.Equals(getRegU32(&gVuBankObservations[0], 5), 0xCAFEu, "real IRQ ABI carries the registered argument");
            t.Equals(gVuBankObservations[1].f[4], 17.0f, "interrupted COP1 frame remains private");
            checkVuBank(t, env.runtime.cpu(), 66);
        });

        tc.Run("VU0 constant vector survives fresh contexts and EE thread restart", [](TestCase &t)
        {
            auto checkConstant = [&](const R5900Context &context)
            {
                alignas(16) std::array<float, 4> lanes{};
                _mm_store_ps(lanes.data(), context.vu0_vf[0]);
                t.Equals(lanes[0], 0.0f, "VF0.x is the hardware constant zero");
                t.Equals(lanes[1], 0.0f, "VF0.y is the hardware constant zero");
                t.Equals(lanes[2], 0.0f, "VF0.z is the hardware constant zero");
                t.Equals(lanes[3], 1.0f, "VF0.w supplies homogeneous matrix coordinates");
            };
            R5900Context fresh{};
            checkConstant(fresh);
            TestEnv env;
            EeScheduler &ee = env.runtime.eeScheduler();
            ee.reset(env.rdram.data(), env.ctx);
            ee.bindMainContextForSyscall(env.ctx, env.rdram.data());
            const int id = ee.createThread(EeThreadCreateParams{0u, K_SCHED_HIGH, 0x24000u, 0x800u,
                                                               0u, 20, 0u});
            t.Equals(ee.startThread(id, 0u, env.ctx, false), KE_OK, "fresh worker starts");
            checkConstant(ee.thread(id)->context);
            uint32_t ownedStack = 0u;
            t.Equals(ee.terminateThread(id, ownedStack, false), KE_OK, "worker becomes dormant");
            t.Equals(ee.startThread(id, 0u, env.ctx, false), KE_OK, "worker restarts with reset context");
            checkConstant(ee.thread(id)->context);
        });

        tc.Run("EE suspend and resume syscalls return the target ID used by guest wakeup gates", [](TestCase &t)
        {
            TestEnv env;
            EeScheduler &ee = env.runtime.eeScheduler();
            ee.reset(env.rdram.data(), env.ctx);
            ee.bindMainContextForSyscall(env.ctx, env.rdram.data());
            const int id = ee.createThread(EeThreadCreateParams{0u, K_SCHED_HIGH, 0x24000u, 0x800u,
                                                               0u, 20, 0u});
            t.Equals(ee.startThread(id, 0u, env.ctx, false), KE_OK, "worker starts below main priority");
            const auto call = [&](uint32_t number, int target)
            {
                setRegU32(env.ctx, 3, number);
                setRegU32(env.ctx, 4, static_cast<uint32_t>(target));
                env.runtime.handleSyscall(env.rdram.data(), &env.ctx, 0);
                return getRegS32(env.ctx, 2);
            };
            t.Equals(call(0x37u, id), id, "SuspendThread success returns the target ID");
            t.Equals(call(0x37u, id), id, "repeated suspend preserves the ID and state");
            const int resumed = call(0x39u, id);
            t.Equals(resumed, id, "ResumeThread must satisfy a guest result == thread ID gate");
            t.IsTrue(ee.thread(id)->status == EeThreadStatus::Ready,
                     "guest success result corresponds to restored readiness");
            t.Equals(call(static_cast<uint32_t>(-0x38), id), id,
                     "interrupt suspend preserves the same return ABI");
            t.Equals(call(static_cast<uint32_t>(-0x3A), id), id,
                     "interrupt resume preserves the same return ABI");
            t.Equals(call(0x39u, 999), KE_UNKNOWN_THID, "unknown thread error remains negative");
            t.Equals(call(0x39u, id), KE_NOT_SUSPEND, "non-suspended target error is preserved");
        });

        tc.Run("thread lifecycle, repeated suspend, WAIT-SUSPEND, and wakeup count are centralized", [](TestCase &t)
        {
            TestEnv env;
            EeScheduler &ee = env.runtime.eeScheduler();
            ee.reset(env.rdram.data(), env.ctx);
            ee.bindMainContextForSyscall(env.ctx, env.rdram.data());

            const int id = ee.createThread(EeThreadCreateParams{0u, K_SCHED_HIGH, 0x24000u, 0x800u,
                                                                 0u, 20, 0u});
            t.Equals(ee.startThread(id, 0xCAFEu, env.ctx, false), KE_OK, "StartThread should make a dormant thread ready");
            t.IsTrue(ee.thread(id)->status == EeThreadStatus::Ready, "started thread should be in one ready queue");
            t.Equals(ee.suspendThread(id, false), KE_OK, "first suspend should remove the ready thread");
            for (int repeat = 0; repeat < 100; ++repeat)
                t.Equals(ee.suspendThread(id, false), KE_OK, "repeated suspend should leave SUSPEND unchanged");
            t.IsTrue(ee.thread(id)->status == EeThreadStatus::Suspended && ee.thread(id)->suspendCount == 1,
                     "EE suspension must not accumulate a nesting count");
            t.Equals(ee.resumeThread(id, false), KE_OK, "one resume should restore readiness after repeated suspends");
            t.IsTrue(ee.thread(id)->status == EeThreadStatus::Ready && ee.thread(id)->suspendCount == 0,
                     "final resume should enqueue the thread exactly once");

            t.Equals(ee.wakeupThread(id, false), KE_OK, "wakeup against a non-sleeping thread should accumulate");
            t.Equals(ee.wakeupThread(id, false), KE_OK, "a second wakeup should accumulate independently");
            t.Equals(ee.cancelWakeup(id), 2, "CancelWakeupThread should return and clear the exact accumulated count");
            t.Equals(ee.cancelWakeup(id), 0, "the wakeup count should remain cleared");

            uint32_t ownedStack = 0u;
            t.Equals(ee.terminateThread(id, ownedStack, false), KE_OK,
                     "TerminateThread should remove a ready thread and make it dormant");
            t.IsTrue(ee.thread(id)->status == EeThreadStatus::Dormant, "terminated thread should be dormant");
            t.Equals(ee.deleteThread(id, ownedStack), KE_OK, "a dormant thread record should be deletable");
            t.IsTrue(ee.thread(id) == nullptr, "deleted thread must leave every scheduler collection");

            bool slept = false;
            try
            {
                ee.sleepCurrent();
            }
            catch (const EeDispatcherTransfer &)
            {
                slept = true;
            }
            t.IsTrue(slept && ee.thread(EeScheduler::kMainThreadId)->status == EeThreadStatus::Waiting,
                     "SleepThread should transfer the running context into a typed wait");
            t.Equals(ee.suspendThread(EeScheduler::kMainThreadId, false), KE_OK,
                     "suspending a waiter should produce WAIT-SUSPEND");
            t.IsTrue(ee.thread(EeScheduler::kMainThreadId)->status == EeThreadStatus::WaitingSuspended,
                     "the sleeping context should remain in its wait object while suspended");
            for (int repeat = 0; repeat < 100; ++repeat)
                t.Equals(ee.suspendThread(EeScheduler::kMainThreadId, false), KE_OK,
                         "repeated suspend must preserve WAIT-SUSPEND without nesting");
            t.Equals(ee.resumeThread(EeScheduler::kMainThreadId, false), KE_OK,
                     "one resume must restore the original sleeping wait");
            t.IsTrue(ee.thread(EeScheduler::kMainThreadId)->status == EeThreadStatus::Waiting &&
                         ee.thread(EeScheduler::kMainThreadId)->wait.reason == EeWaitReason::Sleep,
                     "resume must preserve SleepThread rather than wake it");
            t.Equals(ee.suspendThread(EeScheduler::kMainThreadId, false), KE_OK,
                     "the restored waiter can be suspended again");
            t.Equals(ee.wakeupThread(EeScheduler::kMainThreadId, false), KE_OK,
                     "waking WAIT-SUSPEND should complete the wait without enqueueing yet");
            t.IsTrue(ee.thread(EeScheduler::kMainThreadId)->status == EeThreadStatus::Suspended,
                     "completed WAIT-SUSPEND should become plain suspended");
            t.Equals(ee.resumeThread(EeScheduler::kMainThreadId, false), KE_OK,
                     "resuming the final suspend should make the completed waiter ready");
            t.IsTrue(ee.thread(EeScheduler::kMainThreadId)->status == EeThreadStatus::Ready,
                     "the resumed waiter should re-enter its priority queue once");
        });

        tc.Run("iWakeupThread from an interrupt counts a wakeup for the interrupted running thread", [](TestCase &t)
        {
            // libsif's RPC end function wakes the calling thread with
            // iWakeupThread; the reply can arrive before that thread sleeps.
            TestEnv env;
            EeScheduler &ee = env.runtime.eeScheduler();
            ee.reset(env.rdram.data(), env.ctx);
            ee.bindMainContextForSyscall(env.ctx, env.rdram.data());

            t.Equals(ee.wakeupThread(EeScheduler::kMainThreadId, false), KE_ILLEGAL_THID,
                     "WakeupThread on the caller itself is illegal");
            t.Equals(ee.wakeupThread(EeScheduler::kMainThreadId, true), KE_OK,
                     "iWakeupThread on the interrupted running thread should succeed");
            t.Equals(static_cast<int>(ee.thread(EeScheduler::kMainThreadId)->wakeupCount), 1,
                     "the early wakeup should be counted");
            bool slept = false;
            try
            {
                ee.sleepCurrent();
            }
            catch (const EeDispatcherTransfer &)
            {
                slept = true;
            }
            t.IsTrue(!slept && ee.thread(EeScheduler::kMainThreadId)->wakeupCount == 0u,
                     "SleepThread should consume the counted wakeup and return without blocking");
        });

        tc.Run("semaphore signal, delete, and release complete blocked contexts with exact results", [](TestCase &t)
        {
            const auto blockMain = [](TestEnv &env, int &semaId)
            {
                EeScheduler &ee = env.runtime.eeScheduler();
                ee.reset(env.rdram.data(), env.ctx);
                ee.bindMainContextForSyscall(env.ctx, env.rdram.data());
                semaId = ee.createSemaphore(0, 1, 0u, 0u);
                try
                {
                    ee.waitSemaphore(semaId);
                }
                catch (const EeDispatcherTransfer &)
                {
                }
            };

            TestEnv signaled;
            int signalId = 0;
            blockMain(signaled, signalId);
            t.Equals(signaled.runtime.eeScheduler().signalSemaphore(signalId, false), signalId,
                     "SignalSema should transfer directly to the FIFO waiter");
            t.Equals(getRegS32(signaled.runtime.eeScheduler().thread(1)->context, 2), signalId,
                     "the resumed semaphore waiter should receive the semaphore id");
            t.Equals(signaled.runtime.eeScheduler().semaphore(signalId)->count, 0,
                     "direct semaphore handoff must not increment count");

            TestEnv deleted;
            int deleteId = 0;
            blockMain(deleted, deleteId);
            t.Equals(deleted.runtime.eeScheduler().deleteSemaphore(deleteId, false), deleteId,
                     "DeleteSema should remove the semaphore object");
            t.Equals(getRegS32(deleted.runtime.eeScheduler().thread(1)->context, 2), KE_WAIT_DELETE,
                     "DeleteSema should resume its waiter with KE_WAIT_DELETE");
            t.IsTrue(deleted.runtime.eeScheduler().semaphore(deleteId) == nullptr,
                     "deleted semaphore must no longer own a waiter queue");

            TestEnv released;
            int releaseId = 0;
            blockMain(released, releaseId);
            t.Equals(released.runtime.eeScheduler().releaseWait(EeScheduler::kMainThreadId, false), KE_OK,
                     "ReleaseWaitThread should detach the context from its wait object");
            t.Equals(getRegS32(released.runtime.eeScheduler().thread(1)->context, 2), KE_RELEASE_WAIT,
                     "released waiter should resume with KE_RELEASE_WAIT");
            t.Equals(released.runtime.eeScheduler().semaphore(releaseId)->waiters.size(), size_t{0},
                     "ReleaseWaitThread must remove the exact semaphore waiter");
        });

        tc.Run("event waiters are FIFO and clear modes apply before testing the next waiter", [](TestCase &t)
        {
            TestEnv env;
            env.runtime.registerFunction(K_EVENT_FIFO_MAIN, schedulerEventFifoMain);
            env.runtime.registerFunction(K_EVENT_FIFO_A, schedulerEventFifoWaitA);
            env.runtime.registerFunction(K_EVENT_FIFO_A_RESUME, schedulerEventFifoWaitA);
            env.runtime.registerFunction(K_EVENT_FIFO_B, schedulerEventFifoWaitB);
            env.runtime.registerFunction(K_EVENT_FIFO_B_RESUME, schedulerEventFifoWaitB);
            env.runtime.registerFunction(K_EVENT_FIFO_SIGNAL, schedulerEventFifoSignal);
            env.runtime.registerFunction(K_EVENT_FIFO_SIGNAL_AGAIN, schedulerEventFifoSignalAgain);
            env.runtime.registerFunction(K_EVENT_FIFO_DONE, schedulerEventFifoDone);
            gEventFifoTrace.clear();
            env.ctx.pc = K_EVENT_FIFO_MAIN;
            env.runtime.eeScheduler().reset(env.rdram.data(), env.ctx);
            env.runtime.eeScheduler().run();

            const std::vector<int> expected{1, 2, 3, 4, 5, 6, 7};
            t.IsTrue(gEventFifoTrace == expected,
                     "the first clear waiter must consume the first signal before the second FIFO waiter is tested");
            t.Equals(readGuestU32(env.rdram.data(), K_EVENT_FIFO_RESULT_A), 1u,
                     "first waiter should receive its pre-clear observed bits");
            t.Equals(readGuestU32(env.rdram.data(), K_EVENT_FIFO_RESULT_B), 1u,
                     "second waiter should require and receive the second signal");
            t.Equals(env.runtime.eeScheduler().eventFlag(gEventFifoId)->bits, 0u,
                     "both WEF_CLEAR completions should consume their matched bit");

            const int clearAllId = env.runtime.eeScheduler().createEventFlag(0x7u, 0x02u, 0u);
            uint32_t observed = 0u;
            t.Equals(env.runtime.eeScheduler().pollEventFlag(clearAllId, 0x2u, WEF_OR | WEF_CLEAR_ALL, observed), KE_OK,
                     "WEF_CLEAR_ALL poll should complete when any requested bit is present");
            t.Equals(observed, 0x7u, "event result should contain the bits observed before clearing");
            t.Equals(env.runtime.eeScheduler().eventFlag(clearAllId)->bits, 0u,
                     "WEF_CLEAR_ALL should clear the entire event pattern");
        });

        tc.Run("RotateThreadReadyQueue is the only same-priority rotation", [](TestCase &t)
        {
            TestEnv env;
            std::vector<int> trace;
            gSchedulerTrace = &trace;
            env.runtime.registerFunction(K_SCHED_MAIN, schedulerMainExit);
            env.runtime.registerFunction(K_SCHED_A, schedulerRotateA);
            env.runtime.registerFunction(K_SCHED_A_RESUME, schedulerRotateAResume);
            env.runtime.registerFunction(K_SCHED_B, schedulerTraceB);
            env.ctx.pc = K_SCHED_MAIN;

            EeScheduler &ee = env.runtime.eeScheduler();
            ee.reset(env.rdram.data(), env.ctx);
            const int first = ee.createThread(EeThreadCreateParams{0, K_SCHED_A, 0x20000u, 0x800u, 0, 5, 0});
            const int second = ee.createThread(EeThreadCreateParams{0, K_SCHED_B, 0x21000u, 0x800u, 0, 5, 0});
            ee.startThread(first, 0, env.ctx, false);
            ee.startThread(second, 0, env.ctx, false);
            ee.run();

            const std::vector<int> expected{1, 10, 20, 11};
            t.IsTrue(trace == expected, "explicit rotation should move the current head behind its FIFO peer");
        });

        tc.Run("starting a strictly higher-priority thread preempts immediately", [](TestCase &t)
        {
            TestEnv env;
            std::vector<int> trace;
            gSchedulerTrace = &trace;
            env.runtime.registerFunction(K_SCHED_MAIN, schedulerMainExit);
            env.runtime.registerFunction(K_SCHED_A, schedulerPreemptLow);
            env.runtime.registerFunction(K_SCHED_A_RESUME, schedulerPreemptLowResume);
            env.runtime.registerFunction(K_SCHED_HIGH, schedulerHigh);
            env.ctx.pc = K_SCHED_MAIN;

            EeScheduler &ee = env.runtime.eeScheduler();
            ee.reset(env.rdram.data(), env.ctx);
            const int low = ee.createThread(EeThreadCreateParams{0, K_SCHED_A, 0x20000u, 0x800u, 0, 20, 0});
            gSchedulerCreatedId = ee.createThread(EeThreadCreateParams{0, K_SCHED_HIGH, 0x21000u, 0x800u, 0, 5, 0});
            ee.startThread(low, 0, env.ctx, false);
            ee.run();

            const std::vector<int> expected{1, 30, 5, 31};
            t.IsTrue(trace == expected, "higher priority should run before the starter continues");
        });

        tc.Run("semaphore waiters are FIFO and signal transfers one token directly", [](TestCase &t)
        {
            TestEnv env;
            std::vector<int> trace;
            gSchedulerTrace = &trace;
            gSchedulerWaitResultA = 0;
            gSchedulerWaitResultB = 0;
            env.runtime.registerFunction(K_SCHED_MAIN, schedulerMainExit);
            env.runtime.registerFunction(K_SCHED_A, schedulerWaitA);
            env.runtime.registerFunction(K_SCHED_A_RESUME, schedulerWaitA);
            env.runtime.registerFunction(K_SCHED_B, schedulerWaitB);
            env.runtime.registerFunction(K_SCHED_B_RESUME, schedulerWaitB);
            env.runtime.registerFunction(K_SCHED_SIGNAL, schedulerSignalTwice);
            env.runtime.registerFunction(K_SCHED_SIGNAL_RESUME, schedulerSignalTwice);
            env.ctx.pc = K_SCHED_MAIN;

            EeScheduler &ee = env.runtime.eeScheduler();
            ee.reset(env.rdram.data(), env.ctx);
            gSchedulerSemaphoreId = ee.createSemaphore(0, 1, 0, 0);
            const int waiterA = ee.createThread(EeThreadCreateParams{0, K_SCHED_A, 0x20000u, 0x800u, 0, 5, 0});
            const int waiterB = ee.createThread(EeThreadCreateParams{0, K_SCHED_B, 0x21000u, 0x800u, 0, 5, 0});
            const int signaler = ee.createThread(EeThreadCreateParams{0, K_SCHED_SIGNAL, 0x22000u, 0x800u, 0, 20, 0});
            ee.startThread(waiterA, 0, env.ctx, false);
            ee.startThread(waiterB, 0, env.ctx, false);
            ee.startThread(signaler, 0, env.ctx, false);
            ee.run();

            const std::vector<int> expected{1, 10, 20, 30, 11, 31, 21};
            t.IsTrue(trace == expected, "each signal should wake exactly the FIFO head");
            t.Equals(gSchedulerWaitResultA, gSchedulerSemaphoreId, "first waiter receives sid on resume");
            t.Equals(gSchedulerWaitResultB, gSchedulerSemaphoreId, "second waiter receives sid on resume");
            t.Equals(ee.semaphore(gSchedulerSemaphoreId)->count, 0, "direct handoff must not increment count");
        });

        tc.Run("setup heap and allocator primitives track end-of-heap", [](TestCase &t)
        {
            TestEnv env;

            setRegU32(env.ctx, 4, 0x00180010u);
            setRegU32(env.ctx, 5, 0x00001000u);
            t.IsTrue(callSyscall(0x3Du, env.rdram.data(), &env.ctx, &env.runtime), "SetupHeap syscall should dispatch");
            const uint32_t heapBase = static_cast<uint32_t>(getRegS32(env.ctx, 2));
            t.Equals(heapBase, 0x00180010u, "SetupHeap should return configured base");

            t.IsTrue(callSyscall(0x3Eu, env.rdram.data(), &env.ctx, &env.runtime), "EndOfHeap syscall should dispatch");
            const uint32_t heapLimit = static_cast<uint32_t>(getRegS32(env.ctx, 2));
            t.Equals(heapLimit, 0x00181010u, "EndOfHeap should report the upper limit of the configured heap");

            const uint32_t alignedAlloc = env.runtime.guestMalloc(0x20u, 64u);
            t.IsTrue(alignedAlloc != 0u, "guestMalloc should allocate inside configured heap");
            t.Equals(alignedAlloc & 0x3Fu, 0u, "guestMalloc should honor 64-byte alignment");

            env.runtime.guestFree(alignedAlloc);

            const uint32_t a = env.runtime.guestMalloc(0x100u, 16u);
            const uint32_t b = env.runtime.guestMalloc(0x100u, 16u);
            t.IsTrue(a != 0u && b != 0u, "guestMalloc should provide two adjacent blocks in this heap window");
            env.runtime.guestFree(b);

            const uint32_t grown = env.runtime.guestRealloc(a, 0x180u, 16u);
            t.Equals(grown, a, "guestRealloc should grow in place when adjacent free space is available");

            env.runtime.guestFree(grown);
            const uint32_t reused = env.runtime.guestMalloc(0x80u, 16u);
            t.Equals(reused, heapBase, "guestFree should make the head block reusable");
        });

        tc.Run("memalign stubs allocate aligned guest memory", [](TestCase &t)
        {
            TestEnv env;

            env.runtime.configureGuestHeap(0x00180010u, 0x00182010u);

            setRegU32(env.ctx, 4, 128u);
            setRegU32(env.ctx, 5, 0x40u);
            ps2_stubs::memalign(env.rdram.data(), &env.ctx, &env.runtime);
            const uint32_t direct = ::getRegU32(&env.ctx, 2);
            t.IsTrue(direct != 0u, "memalign should return a guest address");
            t.Equals(direct & 0x7Fu, 0u, "memalign should honor 128-byte alignment");

            setRegU32(env.ctx, 5, 64u);
            setRegU32(env.ctx, 6, 0x40u);
            ps2_stubs::memalign_r(env.rdram.data(), &env.ctx, &env.runtime);
            const uint32_t reent = ::getRegU32(&env.ctx, 2);
            t.IsTrue(reent != 0u, "_memalign_r should return a guest address");
            t.Equals(reent & 0x3Fu, 0u, "_memalign_r should honor 64-byte alignment");
            t.IsTrue(reent != direct, "_memalign_r should allocate a distinct block");
        });

        tc.Run("allocator compatibility stubs use the runtime guest heap", [](TestCase &t)
        {
            TestEnv env;

            env.runtime.configureGuestHeap(0x00180010u, 0x00183010u);

            setRegU32(env.ctx, 5, 0x20u);
            ps2_stubs::malloc_r(env.rdram.data(), &env.ctx, &env.runtime);
            const uint32_t initial = ::getRegU32(&env.ctx, 2);
            t.IsTrue(initial != 0u, "_malloc_r should allocate guest memory");

            writeGuestU32(env.rdram.data(), initial, 0xAABBCCDDu);

            setRegU32(env.ctx, 5, initial);
            setRegU32(env.ctx, 6, 0x80u);
            ps2_stubs::realloc_r(env.rdram.data(), &env.ctx, &env.runtime);
            const uint32_t grown = ::getRegU32(&env.ctx, 2);
            t.IsTrue(grown != 0u, "_realloc_r should return a guest block");
            t.Equals(readGuestU32(env.rdram.data(), grown), 0xAABBCCDDu,
                     "_realloc_r should preserve existing guest bytes");

            setRegU32(env.ctx, 5, grown);
            ps2_stubs::free_r(env.rdram.data(), &env.ctx, &env.runtime);

            setRegU32(env.ctx, 5, 0x100u);
            ps2_stubs::malloc_extend_top(env.rdram.data(), &env.ctx, &env.runtime);
            t.Equals(::getRegU32(&env.ctx, 2), 0u,
                     "malloc_extend_top should be a safe runtime-owned heap no-op");

            ps2_stubs::__malloc_lock(env.rdram.data(), &env.ctx, &env.runtime);
            ps2_stubs::__malloc_unlock(env.rdram.data(), &env.ctx, &env.runtime);
        });

        tc.Run("libc helper stubs cover memclr and libgcc div", [](TestCase &t)
        {
            TestEnv env;

            constexpr uint32_t kBuf = 0x5000u;
            std::memset(env.rdram.data() + kBuf, 0xCD, 16u);
            setRegU32(env.ctx, 4, kBuf);
            setRegU32(env.ctx, 5, 12u);
            ps2_stubs::memclr(env.rdram.data(), &env.ctx, &env.runtime);
            for (uint32_t i = 0; i < 12u; ++i)
            {
                t.Equals(env.rdram[kBuf + i], static_cast<uint8_t>(0),
                         "memclr should zero the requested byte range");
            }
            t.Equals(env.rdram[kBuf + 12u], static_cast<uint8_t>(0xCD),
                     "memclr should not write past the requested byte range");

            SET_GPR_S64(&env.ctx, 4, -9);
            SET_GPR_S64(&env.ctx, 5, 2);
            ps2_stubs::__divdi3(env.rdram.data(), &env.ctx, &env.runtime);
            t.Equals(getRegS32(env.ctx, 2), -4, "__divdi3 should divide signed 64-bit values");
        });

        tc.Run("ReleaseAlarm aliases CancelAlarm and cache syscalls succeed", [](TestCase &t)
        {
            TestEnv env;

            constexpr uint32_t kAlarmHandlerAddr = 0x00270000u;
            env.runtime.registerFunction(kAlarmHandlerAddr, &alarmNoopHandler);

            setRegU32(env.ctx, 4, 0xFFFFu);
            setRegU32(env.ctx, 5, kAlarmHandlerAddr);
            setRegU32(env.ctx, 6, 0u);
            SetAlarm(env.rdram.data(), &env.ctx, &env.runtime);
            const int32_t alarmId = getRegS32(env.ctx, 2);
            t.IsTrue(alarmId > 0, "SetAlarm should create a cancellable alarm");

            setRegU32(env.ctx, 4, static_cast<uint32_t>(alarmId));
            ReleaseAlarm(env.rdram.data(), &env.ctx, &env.runtime);
            t.Equals(getRegS32(env.ctx, 2), KE_OK, "ReleaseAlarm should cancel active alarms");

            setRegU32(env.ctx, 4, static_cast<uint32_t>(alarmId));
            CancelAlarm(env.rdram.data(), &env.ctx, &env.runtime);
            t.Equals(getRegS32(env.ctx, 2), KE_ERROR,
                     "CancelAlarm should report missing alarms after ReleaseAlarm consumes them");

            EnableCache(env.rdram.data(), &env.ctx, &env.runtime);
            t.Equals(getRegS32(env.ctx, 2), KE_OK, "EnableCache should succeed as a no-op");

            DisableCache(env.rdram.data(), &env.ctx, &env.runtime);
            t.Equals(getRegS32(env.ctx, 2), KE_OK, "DisableCache should succeed as a no-op");

            setRegU32(env.ctx, 2, 0xDEADBEEFu);
            setRegU32(env.ctx, 4, 0u); // PS2SDK WRITEBACK_DCACHE
            t.IsTrue(callSyscall(static_cast<uint32_t>(-0x68), env.rdram.data(), &env.ctx, &env.runtime),
                     "-0x68 should dispatch iFlushCache");
            t.Equals(getRegS32(env.ctx, 2), KE_OK,
                     "iFlushCache should succeed when guest and host memory are coherent");
            setRegU32(env.ctx, 2, 0xdeadbeefu);
            t.IsTrue(callSyscall(0x6bu, env.rdram.data(), &env.ctx, &env.runtime),
                     "sceSifStopDma must dispatch");
            t.Equals(getRegS32(env.ctx, 2), 0,
                     "synchronous SIF transfers leave no pending DMA to stop");
        });

        tc.Run("StartThread diagnoses untranslated entry without changing kernel failure", [](TestCase &t)
        {
            TestEnv env;
            env.ctx.pc = 0x221700u;
            auto &ee = env.runtime.eeScheduler();
            ee.bindMainContextForSyscall(env.ctx, env.rdram.data());
            EeThreadCreateParams params{};
            params.entry = 0x1189ca0u;
            params.stack = 0x20000u;
            params.stackSize = 0x800u;
            params.priority = 20;
            const int id = ee.createThread(params);
            t.IsTrue(id > 0, "Missing entry may be represented by a dormant guest thread");
            setRegU32(env.ctx, 4, static_cast<uint32_t>(id));
            setRegU32(env.ctx, 5, 0xcafeu);
            std::ostringstream captured;
            auto *previous = std::cerr.rdbuf(captured.rdbuf());
            StartThread(env.rdram.data(), &env.ctx, &env.runtime);
            std::cerr.rdbuf(previous);
            t.Equals(getRegS32(env.ctx, 2), KE_ERROR, "Untranslated entry still returns the kernel error");
            t.IsTrue(ee.thread(id)->status == EeThreadStatus::Dormant, "Rejected thread remains dormant");
            t.Equals(env.ctx.pc, 0x221700u, "Diagnostic does not redirect the caller PC");
            t.IsTrue(!env.runtime.isStopRequested(), "Diagnostic alone does not stop runtime");
            t.IsTrue(captured.str().find("[EE thread:missing-entry]") != std::string::npos,
                     "Capture tools can distinguish untranslated entry from ordinary StartThread errors");
            t.IsTrue(captured.str().find("entry=0x1189ca0") != std::string::npos &&
                     captured.str().find("arg=0xcafe") != std::string::npos,
                     "Diagnostic preserves target and argument evidence");
        });

        tc.Run("setup heap and thread invalid ids use documented kernel errors", [](TestCase &t)
        {
            TestEnv env;

            setRegU32(env.ctx, 4, 0u);
            CreateThread(env.rdram.data(), &env.ctx, &env.runtime);
            t.Equals(getRegS32(env.ctx, 2), KE_ERROR, "CreateThread with null param should fail");

            setRegU32(env.ctx, 4, 0u);
            DeleteThread(env.rdram.data(), &env.ctx, &env.runtime);
            t.Equals(getRegS32(env.ctx, 2), KE_ILLEGAL_THID, "DeleteThread(0) should be KE_ILLEGAL_THID");

            setRegU32(env.ctx, 4, 0x7FFFu);
            StartThread(env.rdram.data(), &env.ctx, &env.runtime);
            t.Equals(getRegS32(env.ctx, 2), KE_UNKNOWN_THID, "StartThread should reject unknown thread ids");

            setRegU32(env.ctx, 4, 0x7FFFu);
            WakeupThread(env.rdram.data(), &env.ctx, &env.runtime);
            t.Equals(getRegS32(env.ctx, 2), KE_UNKNOWN_THID, "WakeupThread should reject unknown thread ids");

            setRegU32(env.ctx, 4, 0x7FFFu);
            PollSema(env.rdram.data(), &env.ctx, &env.runtime);
            t.Equals(getRegS32(env.ctx, 2), KE_UNKNOWN_SEMID, "PollSema should reject unknown semaphore ids");

            setRegU32(env.ctx, 4, 0xFFFFFFFFu);
            t.IsTrue(callSyscall(0x3Du, env.rdram.data(), &env.ctx, &env.runtime), "SetupHeap syscall should dispatch");
            const uint32_t clampedBase = static_cast<uint32_t>(getRegS32(env.ctx, 2));
            t.IsTrue(clampedBase < PS2_RAM_SIZE, "SetupHeap should normalize out-of-range base into guest RAM");

            t.IsTrue(callSyscall(0x3Eu, env.rdram.data(), &env.ctx, &env.runtime), "EndOfHeap syscall should dispatch");
            const uint32_t heapEnd = static_cast<uint32_t>(getRegS32(env.ctx, 2));
            t.IsTrue(heapEnd >= clampedBase, "EndOfHeap should be at or above normalized heap base");

            setRegU32(env.ctx, 4, 1u);
            setRegU32(env.ctx, 5, 0u);
            setRegU32(env.ctx, 6, 0u);
            setRegU32(env.ctx, 29, 0x0010FFF0u);
            t.IsTrue(callSyscall(0x3Cu, env.rdram.data(), &env.ctx, &env.runtime), "SetupThread syscall should dispatch");
            const uint32_t setupSp = static_cast<uint32_t>(getRegS32(env.ctx, 2));
            t.Equals(setupSp & 0xFu, 0u, "SetupThread should always return a 16-byte aligned stack pointer");
        });

        tc.Run("automatic stack survives native heap initialization and runtime scratch stays separate", [](TestCase &t)
        {
            TestEnv env;
            env.ctx.pc = 0x100000u;
            setRegU32(env.ctx, 5, 0xffffffffu);
            setRegU32(env.ctx, 6, 0x50000u);
            callSyscall(0x3Cu, env.rdram.data(), &env.ctx, &env.runtime);
            const uint32_t frame = ::getRegU32(&env.ctx, 2) - 0x240u;
            writeGuestU32(env.rdram.data(), frame, 0x228dccu);
            std::memset(env.rdram.data() + 0xf98800u, 0, 0x1017800u);
            t.Equals(readGuestU32(env.rdram.data(), frame), 0x228dccu,
                     "RE4 heap clearing must preserve the live return address");
            const uint32_t scratch = env.runtime.nativeRpcScratch();
            t.IsTrue(scratch >= 0x80000u && scratch + 32768u <= 0x100000u,
                     "RPC scratch occupies protected HLE pages, separate from heap and stack");
            const uint32_t callback = env.runtime.reserveAsyncCallbackStack(0x4000u);
            t.IsTrue(callback >= 0x80000u && callback < 0x100000u,
                     "callbacks occupy the same isolated arena");
            env.runtime.configureGuestHeap(0x70000u, 0x120000u);
            const uint32_t below = env.runtime.guestMalloc(0x10000u, 16u);
            const uint32_t above = env.runtime.guestMalloc(0x20000u, 16u);
            t.Equals(below, 0x70000u, "heap can use free bytes below private pages");
            t.Equals(above, 0x100000u, "heap skips private pages for the next allocation");
        });

        tc.Run("SetupThread exposes stable main stack metadata through ReferThreadStatus", [](TestCase &t)
        {
            TestEnv env;
            constexpr uint32_t kInitialLoaderSp = PS2_RAM_SIZE - 0x10u;
            constexpr uint32_t kMainStackSize = 0x00020000u;
            constexpr uint32_t kExpectedStack = PS2_RAM_SIZE - kMainStackSize;
            constexpr uint32_t kMainGp = 0x0036A7F0u;

            env.ctx.pc = 0x00100000u;
            setRegU32(env.ctx, 29, kInitialLoaderSp);
            setRegU32(env.ctx, 4, kMainGp);
            setRegU32(env.ctx, 5, 0xFFFFFFFFu);
            setRegU32(env.ctx, 6, kMainStackSize);
            t.IsTrue(callSyscall(0x3Cu, env.rdram.data(), &env.ctx, &env.runtime),
                     "SetupThread syscall should dispatch");
            t.Equals(::getRegU32(&env.ctx, 2), PS2_RAM_SIZE,
                     "automatic stack starts at its top so frames grow inside its range");

            // ReferThreadStatus can be called after many nested frames have moved $sp.
            // It must report the initial stack recorded by SetupThread, not this live snapshot.
            constexpr uint32_t kTransientSp = PS2_RAM_SIZE - 0x80u;
            setRegU32(env.ctx, 29, kTransientSp);
            setRegU32(env.ctx, 4, 0u);
            setRegU32(env.ctx, 5, K_STATUS_ADDR);
            t.IsTrue(callSyscall(0x30u, env.rdram.data(), &env.ctx, &env.runtime),
                     "ReferThreadStatus syscall should dispatch");
            t.Equals(getRegS32(env.ctx, 2), KE_OK, "ReferThreadStatus should accept the current-thread id alias");

            EeThreadStatusAbi status{};
            std::memcpy(&status, env.rdram.data() + K_STATUS_ADDR, sizeof(status));
            t.Equals(status.stack, kExpectedStack,
                     "main thread status must expose SetupThread's stable initial stack");
            t.Equals(status.stack_size, static_cast<int32_t>(kMainStackSize),
                     "main thread status must preserve SetupThread's stack size");
            t.Equals(status.gp_reg, kMainGp,
                     "main thread status must preserve SetupThread's global pointer");
            t.IsTrue(status.stack != kInitialLoaderSp && status.stack != kTransientSp,
                     "main thread status must never expose a live stack-pointer snapshot");

            // Run this suite with PS2X_TRACE_EE to cross the auxiliary log
            // cap. Suppressing diagnostics must not suppress ABI writes.
            bool repeatedStatusSucceeded = true;
            for (unsigned query = 0; query < 600u; ++query)
            {
                std::memset(env.rdram.data() + K_STATUS_ADDR, 0xA5, sizeof(status));
                setRegU32(env.ctx, 4, 0u);
                setRegU32(env.ctx, 5, K_STATUS_ADDR);
                repeatedStatusSucceeded &= callSyscall(0x30u, env.rdram.data(), &env.ctx, &env.runtime);
                repeatedStatusSucceeded &= getRegS32(env.ctx, 2) == KE_OK;
            }
            t.IsTrue(repeatedStatusSucceeded, "repeated status queries must remain serviced after the diagnostic cap");
            t.IsTrue(std::memcmp(env.rdram.data() + K_STATUS_ADDR, &status, sizeof(status)) == 0,
                     "status ABI must still be fully rewritten after diagnostic logging stops");
        });

        tc.Run("OSD config2 syscalls round-trip extended config", [](TestCase &t)
        {
            TestEnv env;
            constexpr uint32_t kConfig2Addr = 0x00005000u;
            constexpr uint32_t kConfig2OutAddr = 0x00005010u;
            constexpr uint32_t kConfig1OutAddr = 0x00005020u;
            constexpr uint32_t kInitialConfig1 =
                (1u << 0) |  // SPDIF disabled
                (1u << 4) |  // non-Japanese language flag
                (1u << 13) | // OSD2
                (1u << 16);  // English
            constexpr uint32_t kConfig2Raw =
                0xABu |        // format
                (0xB0u << 8) | // daylightSaving=1, timeFormat=1, dateFormat=2
                (2u << 16) |   // extended OSD version
                (10u << 24);   // traditional Chinese

            writeGuestU32(env.rdram.data(), K_PARAM_ADDR, kInitialConfig1);
            setRegU32(env.ctx, 4, K_PARAM_ADDR);
            t.IsTrue(callSyscall(0x4Au, env.rdram.data(), &env.ctx, &env.runtime),
                     "SetOsdConfigParam syscall should dispatch");
            t.Equals(getRegS32(env.ctx, 2), KE_OK, "SetOsdConfigParam should seed base OSD state");

            writeGuestU32(env.rdram.data(), kConfig2Addr, kConfig2Raw);
            setRegU32(env.ctx, 4, kConfig2Addr);
            setRegU32(env.ctx, 5, 4u);
            setRegU32(env.ctx, 6, 0u);
            t.IsTrue(callSyscall(0x6Eu, env.rdram.data(), &env.ctx, &env.runtime),
                     "SetOsdConfigParam2 syscall should dispatch");
            t.Equals(getRegS32(env.ctx, 2), KE_OK, "SetOsdConfigParam2 should succeed");

            writeGuestU32(env.rdram.data(), kConfig2OutAddr, 0xFFFFFFFFu);
            setRegU32(env.ctx, 4, kConfig2OutAddr);
            setRegU32(env.ctx, 5, 4u);
            setRegU32(env.ctx, 6, 0u);
            t.IsTrue(callSyscall(0x6Fu, env.rdram.data(), &env.ctx, &env.runtime),
                     "GetOsdConfigParam2 syscall should dispatch");
            t.Equals(getRegS32(env.ctx, 2), KE_OK, "GetOsdConfigParam2 should succeed");
            const uint32_t readConfig2 = readGuestU32(env.rdram.data(), kConfig2OutAddr);
            t.Equals(readConfig2, kConfig2Raw, "GetOsdConfigParam2 should round-trip the sanitized Config2Param bytes");
            t.Equals((readConfig2 >> 12) & 1u, 1u, "Config2 daylightSaving should live at bit 12 for libosd callers");

            setRegU32(env.ctx, 4, kConfig1OutAddr);
            t.IsTrue(callSyscall(0x4Bu, env.rdram.data(), &env.ctx, &env.runtime),
                     "GetOsdConfigParam syscall should dispatch after Config2 update");
            const uint32_t readConfig1 = readGuestU32(env.rdram.data(), kConfig1OutAddr);
            t.Equals((readConfig1 >> 13) & 0x7u, 2u, "SetOsdConfigParam2 should sync ConfigParam.version");
            t.Equals((readConfig1 >> 16) & 0x1Fu, 10u, "SetOsdConfigParam2 should sync ConfigParam.language");
        });

        tc.Run("numeric syscall 0x83 finds matching table entry", [](TestCase &t)
        {
            TestEnv env;
            constexpr uint32_t kTableBase = 0x00002000u;
            constexpr uint32_t kValues[] = {
                0x11111111u,
                0x11223344u,
                0x55555555u,
                0x89ABCDEFu
            };

            writeGuestWords(env.rdram.data(), kTableBase, kValues, std::size(kValues));
            setRegU32(env.ctx, 4, kTableBase);
            setRegU32(env.ctx, 5, kTableBase + static_cast<uint32_t>(sizeof(kValues)));
            setRegU32(env.ctx, 6, 0x11223344u);

            t.IsTrue(callSyscall(0x83u, env.rdram.data(), &env.ctx, &env.runtime),
                     "syscall 0x83 should dispatch");
            t.Equals(static_cast<uint32_t>(getRegS32(env.ctx, 2)),
                     kTableBase + 4u,
                     "FindAddress should return address of first matching word");
        });

        tc.Run("numeric syscall 0x83 supports KSEG aliases", [](TestCase &t)
        {
            TestEnv env;
            constexpr uint32_t kTableBasePhys = 0x00003000u;
            constexpr uint32_t kTableBaseKseg = 0x80003000u;
            constexpr uint32_t kValues[] = {
                0x00123456u,
                0x8000AAAAu
            };

            writeGuestWords(env.rdram.data(), kTableBasePhys, kValues, std::size(kValues));
            setRegU32(env.ctx, 4, kTableBaseKseg);
            setRegU32(env.ctx, 5, kTableBaseKseg + static_cast<uint32_t>(sizeof(kValues)));
            setRegU32(env.ctx, 6, 0x80123456u); // Alias of first table value

            t.IsTrue(callSyscall(0x83u, env.rdram.data(), &env.ctx, &env.runtime),
                     "syscall 0x83 should dispatch");
            t.Equals(static_cast<uint32_t>(getRegS32(env.ctx, 2)),
                     kTableBaseKseg,
                     "FindAddress should match KSEG aliases and preserve guest segment in return value");
        });

        tc.Run("numeric syscall 0x83 returns 0 when entry is absent", [](TestCase &t)
        {
            TestEnv env;
            constexpr uint32_t kTableBase = 0x00004000u;
            constexpr uint32_t kValues[] = {
                0x00000001u,
                0x00000002u,
                0x00000003u
            };

            writeGuestWords(env.rdram.data(), kTableBase, kValues, std::size(kValues));
            setRegU32(env.ctx, 4, kTableBase);
            setRegU32(env.ctx, 5, kTableBase + static_cast<uint32_t>(sizeof(kValues)));
            setRegU32(env.ctx, 6, 0xDEADBEEFu);

            t.IsTrue(callSyscall(0x83u, env.rdram.data(), &env.ctx, &env.runtime),
                     "syscall 0x83 should dispatch");
            t.Equals(static_cast<uint32_t>(getRegS32(env.ctx, 2)),
                     0u,
                     "FindAddress should return 0 when no matching word exists");
        });

        tc.Run("SetSyscall mirrors guest kernel table entries into low memory", [](TestCase &t)
        {
            TestEnv env;
            initializeGuestKernelState(env.rdram.data(), &env.runtime);

            constexpr uint32_t kGuestSyscallTableGuestBase = 0x80011F80u;
            constexpr uint32_t kSyscallIndex = 0x82u;
            constexpr uint32_t kHandler = 0x00383548u;
            constexpr uint32_t kExpectedGuestAddr = kGuestSyscallTableGuestBase + (kSyscallIndex * 4u);
            constexpr uint32_t kExpectedPhysAddr = kExpectedGuestAddr & 0x1FFFFFFFu;

            setRegU32(env.ctx, 4, kSyscallIndex);
            setRegU32(env.ctx, 5, kHandler);
            t.IsTrue(callSyscall(0x74u, env.rdram.data(), &env.ctx, &env.runtime),
                     "SetSyscall syscall should dispatch");

            uint32_t mirrored = 0u;
            std::memcpy(&mirrored, env.rdram.data() + kExpectedPhysAddr, sizeof(mirrored));
            t.Equals(mirrored,
                     kHandler,
                     "SetSyscall should mirror handler pointers into the guest kernel syscall table");

            setRegU32(env.ctx, 4, 0x80000000u);
            setRegU32(env.ctx, 5, 0x80080000u);
            setRegU32(env.ctx, 6, kHandler);
            t.IsTrue(callSyscall(0x83u, env.rdram.data(), &env.ctx, &env.runtime),
                     "FindAddress syscall should dispatch");
            t.Equals(static_cast<uint32_t>(getRegS32(env.ctx, 2)),
                     kExpectedGuestAddr,
                     "FindAddress should discover mirrored SetSyscall entries in low guest memory");
        });

        tc.Run("SetSyscall honors signed kernel-table offsets", [](TestCase &t)
        {
            TestEnv env;
            initializeGuestKernelState(env.rdram.data(), &env.runtime);

            constexpr uint32_t kPatchIndex = 0xFFFFC402u;
            constexpr uint32_t kHandler = 0xDEADBEEFu;
            constexpr uint32_t kExpectedGuestAddr = 0x80002F88u;
            constexpr uint32_t kExpectedPhysAddr = kExpectedGuestAddr & 0x1FFFFFFFu;

            setRegU32(env.ctx, 4, kPatchIndex);
            setRegU32(env.ctx, 5, kHandler);
            t.IsTrue(callSyscall(0x74u, env.rdram.data(), &env.ctx, &env.runtime),
                     "SetSyscall syscall should dispatch for signed offsets");

            uint32_t mirrored = 0u;
            std::memcpy(&mirrored, env.rdram.data() + kExpectedPhysAddr, sizeof(mirrored));
            t.Equals(mirrored,
                     kHandler,
                     "SetSyscall should treat the syscall index as a signed offset from the kernel table base");
        });

        tc.Run("guest kernel syscall overrides and mirrors are isolated per runtime", [](TestCase &t)
        {
            TestEnv first;
            TestEnv second;
            initializeGuestKernelState(first.rdram.data(), &first.runtime);
            initializeGuestKernelState(second.rdram.data(), &second.runtime);

            constexpr uint32_t kGuestSyscallTableGuestBase = 0x80011F80u;
            constexpr uint32_t kGuestSyscallTableProbeBase = 0x000002F0u;
            constexpr uint32_t kSyscallIndex = 0x5Au;
            constexpr uint32_t kFirstHandler = 0x00383510u;
            constexpr uint32_t kSecondHandler = 0x00383520u;
            constexpr uint32_t kEntryPhysAddr = (kGuestSyscallTableGuestBase + (kSyscallIndex * 4u)) & 0x1FFFFFFFu;

            setRegU32(first.ctx, 4, kSyscallIndex);
            setRegU32(first.ctx, 5, kFirstHandler);
            t.IsTrue(callSyscall(0x74u, first.rdram.data(), &first.ctx, &first.runtime),
                     "SetSyscall should install the first runtime's override");

            uint32_t firstHandler = 0u;
            uint32_t secondHandler = 0u;
            t.IsTrue(first.runtime.findEeSyscallOverride(kSyscallIndex, firstHandler),
                     "the first runtime should own its override");
            t.IsFalse(second.runtime.findEeSyscallOverride(kSyscallIndex, secondHandler),
                      "a different runtime must not observe the first runtime's override");

            setRegU32(second.ctx, 4, kSyscallIndex);
            setRegU32(second.ctx, 5, kSecondHandler);
            t.IsTrue(callSyscall(0x74u, second.rdram.data(), &second.ctx, &second.runtime),
                     "SetSyscall should install an independent second-runtime override");

            uint32_t firstMirrored = 0u;
            uint32_t secondMirrored = 0u;
            std::memcpy(&firstMirrored, first.rdram.data() + kEntryPhysAddr, sizeof(firstMirrored));
            std::memcpy(&secondMirrored, second.rdram.data() + kEntryPhysAddr, sizeof(secondMirrored));
            t.Equals(firstMirrored, kFirstHandler, "the first runtime should retain its own mirror value");
            t.Equals(secondMirrored, kSecondHandler, "the second runtime should publish only its own mirror value");

            initializeGuestKernelState(first.rdram.data(), &first.runtime);
            std::memcpy(&firstMirrored, first.rdram.data() + kEntryPhysAddr, sizeof(firstMirrored));
            t.Equals(firstMirrored, kFirstHandler,
                     "reinitializing one runtime should rebuild its mirror from its instance-owned overrides");

            uint32_t probeHi = 0u;
            uint32_t probeLo = 0u;
            std::memcpy(&probeHi, first.rdram.data() + kGuestSyscallTableProbeBase + 0u, sizeof(probeHi));
            std::memcpy(&probeLo, first.rdram.data() + kGuestSyscallTableProbeBase + 8u, sizeof(probeLo));
            t.Equals(probeHi,
                     kGuestSyscallTableGuestBase >> 16,
                     "Guest kernel initialization should seed the syscall table probe high word");
            t.Equals(probeLo,
                     kGuestSyscallTableGuestBase & 0xFFFFu,
                     "Guest kernel initialization should seed the syscall table probe low word");
        });

        tc.Run("transport completion waits for virtual time and reset cancels old replies", [](TestCase &t)
        {
            TestEnv env;
            auto &scheduler = env.runtime.eeScheduler();
            R5900Context idle{};
            scheduler.reset(env.rdram.data(), idle);
            int cancelled = 0;
            scheduler.scheduleTransportCompletion(16u, [&] { ++cancelled; });
            scheduler.reset(env.rdram.data(), idle);
            std::vector<int> order;
            uint64_t arrival = 0u;
            scheduler.scheduleTransportCompletion(64u, [&] {
                arrival = scheduler.currentCycle();
                order.push_back(1);
            });
            scheduler.scheduleTransportCompletion(64u, [&] {
                order.push_back(2);
                scheduler.requestStop();
            });
            t.IsTrue(order.empty(), "a completed host transport must not deliver inline");
            scheduler.run();
            t.Equals(cancelled, 0, "reset must discard replies belonging to the old machine");
            t.IsTrue(arrival >= 64u, "reply must not arrive before its virtual deadline");
            t.IsTrue(order == std::vector<int>({1, 2}), "equal-deadline replies must keep enqueue order");
        });

        tc.Run("SetSyscall override runs as a scheduler invocation", [](TestCase &t)
        {
            TestEnv env;
            constexpr uint32_t kSyscallIndex = 0x91u;
            constexpr uint32_t kHandler = 0x00200000u;

            env.runtime.registerFunction(kHandler, overrideReturnHandler);
            env.runtime.registerFunction(K_OVERRIDE_ENTRY, schedulerOverrideEntry);
            env.runtime.registerFunction(K_OVERRIDE_RESUME, schedulerOverrideResume);
            env.runtime.setEeSyscallOverride(env.rdram.data(), kSyscallIndex, kHandler);

            gOverrideSyscall = kSyscallIndex;
            R5900Context mainContext{};
            mainContext.pc = K_OVERRIDE_ENTRY;
            setRegU32(mainContext, 4, 7u);
            setRegU32(mainContext, 5, 5u);
            env.runtime.eeScheduler().reset(env.rdram.data(), mainContext);
            env.runtime.eeScheduler().run();

            t.Equals(static_cast<uint32_t>(getRegS32(gOverrideResult, 2)),
                     12u,
                     "the completed invocation should propagate the guest handler return value");
        });

        tc.Run("SetSyscall override preserves KSEG argument sign extension", [](TestCase &t)
        {
            TestEnv env;
            constexpr uint32_t kSyscallIndex = 0x92u;
            constexpr uint32_t kHandler = 0x00200030u;

            env.runtime.registerFunction(kHandler, overrideKsegCompareHandler);
            env.runtime.registerFunction(K_OVERRIDE_ENTRY, schedulerOverrideEntry);
            env.runtime.registerFunction(K_OVERRIDE_RESUME, schedulerOverrideResume);
            env.runtime.setEeSyscallOverride(env.rdram.data(), kSyscallIndex, kHandler);

            gOverrideSyscall = kSyscallIndex;
            R5900Context mainContext{};
            mainContext.pc = K_OVERRIDE_ENTRY;
            setRegU32(mainContext, 4, 0x80000000u);
            setRegU32(mainContext, 5, 0x80080000u);
            env.runtime.eeScheduler().reset(env.rdram.data(), mainContext);
            env.runtime.eeScheduler().run();

            t.Equals(static_cast<uint32_t>(getRegS32(gOverrideResult, 2)),
                     0x80000004u,
                     "Override invocation should preserve KSEG ordering after 32-bit guest writes");
        });

        tc.Run("SetSyscall override preserves upper 64 bits when writing 32-bit args", [](TestCase &t)
        {
            TestEnv env;
            constexpr uint32_t kSyscallIndex = 0x93u;
            constexpr uint32_t kHandler = 0x00200040u;

            env.runtime.registerFunction(kHandler, overridePreserveUpper64Handler);
            env.runtime.registerFunction(K_OVERRIDE_ENTRY, schedulerOverrideEntry);
            env.runtime.registerFunction(K_OVERRIDE_RESUME, schedulerOverrideResume);
            env.runtime.setEeSyscallOverride(env.rdram.data(), kSyscallIndex, kHandler);

            gOverrideSyscall = kSyscallIndex;
            R5900Context mainContext{};
            mainContext.pc = K_OVERRIDE_ENTRY;
            mainContext.r[4] = _mm_set_epi64x(static_cast<int64_t>(K_EXPECTED_UPPER64),
                                               static_cast<int64_t>(static_cast<int32_t>(0x80000000u)));
            env.runtime.eeScheduler().reset(env.rdram.data(), mainContext);
            env.runtime.eeScheduler().run();

            t.Equals(static_cast<uint32_t>(getRegS32(gOverrideResult, 2)),
                     1u,
                     "Override invocation should preserve the upper 64 bits of 128-bit GPRs when setting 32-bit args");
        });

        tc.Run("an override that branches to an invalid PC completes without builtin fallback", [](TestCase &t)
        {
            TestEnv env;
            constexpr uint32_t kHandler = 0x00200010u;

            env.runtime.registerFunction(kHandler, overrideBrokenHandler);
            env.runtime.registerFunction(K_OVERRIDE_ENTRY, schedulerOverrideEntry);
            env.runtime.registerFunction(K_OVERRIDE_RESUME, schedulerOverrideResume);
            env.runtime.setEeSyscallOverride(env.rdram.data(), 0x83u, kHandler);

            gOverrideSyscall = 0x83u;
            R5900Context mainContext{};
            mainContext.pc = K_OVERRIDE_ENTRY;
            env.runtime.eeScheduler().reset(env.rdram.data(), mainContext);
            env.runtime.eeScheduler().run();

            t.Equals(static_cast<uint32_t>(getRegS32(gOverrideResult, 2)),
                     0xDEADBEEFu,
                     "the dispatcher should preserve the invocation result and never call the builtin as a fallback");
        });

        tc.Run("reentrant override invokes the underlying builtin inside its invocation frame", [](TestCase &t)
        {
            TestEnv env;
            constexpr uint32_t kHandler = 0x00200020u;
            constexpr uint32_t kTableBase = 0x00003000u;
            constexpr uint32_t kValues[] = {
                0xCAFEBABEu,
                0x11223344u,
                0x55667788u
            };

            env.runtime.registerFunction(kHandler, overrideRecursiveFindAddressHandler);
            env.runtime.registerFunction(K_OVERRIDE_ENTRY, schedulerOverrideEntry);
            env.runtime.registerFunction(K_OVERRIDE_RESUME, schedulerOverrideResume);
            env.runtime.setEeSyscallOverride(env.rdram.data(), 0x83u, kHandler);

            writeGuestWords(env.rdram.data(), kTableBase, kValues, std::size(kValues));
            gOverrideSyscall = 0x83u;
            R5900Context mainContext{};
            mainContext.pc = K_OVERRIDE_ENTRY;
            setRegU32(mainContext, 4, kTableBase);
            setRegU32(mainContext, 5, kTableBase + static_cast<uint32_t>(sizeof(kValues)));
            setRegU32(mainContext, 6, 0x11223344u);
            env.runtime.eeScheduler().reset(env.rdram.data(), mainContext);
            env.runtime.eeScheduler().run();

            t.Equals(static_cast<uint32_t>(getRegS32(gOverrideResult, 2)),
                     kTableBase + 4u,
                     "only the recursive call should bypass the active override frame and reach the builtin");
        });

        tc.Run("a syscall invocation can block and resume without losing its base context", [](TestCase &t)
        {
            TestEnv env;
            constexpr uint32_t kSyscallIndex = 0x94u;
            env.runtime.registerFunction(K_OVERRIDE_BLOCK_ENTRY, schedulerBlockingOverrideEntry);
            env.runtime.registerFunction(K_OVERRIDE_BLOCK_HANDLER, schedulerBlockingOverrideHandler);
            env.runtime.registerFunction(K_OVERRIDE_BLOCK_HANDLER_RESUME, schedulerBlockingOverrideHandlerResume);
            env.runtime.registerFunction(K_OVERRIDE_BLOCK_DRIVER, schedulerBlockingOverrideDriver);
            env.runtime.registerFunction(K_OVERRIDE_BLOCK_BASE_RESUME, schedulerBlockingOverrideBaseResume);
            env.runtime.setEeSyscallOverride(env.rdram.data(), kSyscallIndex, K_OVERRIDE_BLOCK_HANDLER);

            gOverrideSyscall = kSyscallIndex;
            gInvocationTrace.clear();
            R5900Context mainContext{};
            mainContext.pc = K_OVERRIDE_BLOCK_ENTRY;
            env.runtime.eeScheduler().reset(env.rdram.data(), mainContext);
            env.runtime.eeScheduler().run();

            const std::vector<int> expected{1, 2, 3, 4, 5};
            t.IsTrue(gInvocationTrace == expected,
                     "the sleeping invocation should yield to the driver, resume its own frame, then restore the base frame");
            t.Equals(static_cast<uint32_t>(getRegS32(gOverrideResult, 2)), 0xB10C0EDu,
                     "the invocation result should reach the preserved base context after the wait");
        });

        tc.Run("exit handlers run as ordered invocation frames before the thread becomes dormant", [](TestCase &t)
        {
            TestEnv env;
            env.runtime.registerFunction(K_EXIT_MAIN, schedulerExitMain);
            env.runtime.registerFunction(K_EXIT_HANDLER_A, schedulerExitHandlerA);
            env.runtime.registerFunction(K_EXIT_HANDLER_B, schedulerExitHandlerB);
            env.runtime.registerFunction(K_EXIT_OBSERVER, schedulerExitObserver);

            gInvocationTrace.clear();
            R5900Context mainContext{};
            mainContext.pc = K_EXIT_MAIN;
            env.runtime.eeScheduler().reset(env.rdram.data(), mainContext);
            env.runtime.eeScheduler().run();

            const std::vector<int> expected{10, 20, 30, 40};
            t.IsTrue(gInvocationTrace == expected,
                     "exit handlers should retain registration order and complete before another guest thread observes dormancy");
        });

        tc.Run("Copy syscall (0x5A) performs a memory copy", [](TestCase &t)
        {
            TestEnv env;
            constexpr uint32_t kDestAddr = 0x00005000u;
            constexpr uint32_t kSrcAddr = 0x00006000u;
            constexpr uint32_t kSize = 16u;
            constexpr uint32_t kValues[] = {
                0x11223344u,
                0x55667788u,
                0x99AABBCCu,
                0xDDEEFF00u
            };

            writeGuestWords(env.rdram.data(), kSrcAddr, kValues, std::size(kValues));
            
            setRegU32(env.ctx, 4, kDestAddr);
            setRegU32(env.ctx, 5, kSrcAddr);
            setRegU32(env.ctx, 6, kSize);

            t.IsTrue(callSyscall(0x5Au, env.rdram.data(), &env.ctx, &env.runtime),
                     "Copy syscall should dispatch");
            
            for (size_t i = 0; i < std::size(kValues); ++i)
            {
                uint32_t destVal = readGuestU32(env.rdram.data(), kDestAddr + static_cast<uint32_t>(i * sizeof(uint32_t)));
                t.Equals(destVal, kValues[i], "Copy should correctly transfer bytes");
            }
        });

        tc.Run("GetEntryAddress syscall (0x5B) returns handler from guest table", [](TestCase &t)
        {
            TestEnv env;
            initializeGuestKernelState(env.rdram.data(), &env.runtime);

            constexpr uint32_t kGuestSyscallTableGuestBase = 0x80011F80u;
            constexpr uint32_t kSyscallIndex = 0x5Au;
            constexpr uint32_t kExpectedHandler = 0x00383548u;
            constexpr uint32_t kEntryPhysAddr = (kGuestSyscallTableGuestBase + (kSyscallIndex * 4u)) & 0x1FFFFFFFu;

            writeGuestU32(env.rdram.data(), kEntryPhysAddr, kExpectedHandler);

            setRegU32(env.ctx, 4, kSyscallIndex);

            t.IsTrue(callSyscall(0x5Bu, env.rdram.data(), &env.ctx, &env.runtime),
                     "GetEntryAddress syscall should dispatch");
            
            t.Equals(static_cast<uint32_t>(getRegS32(env.ctx, 2)),
                     kExpectedHandler,
                     "GetEntryAddress should read and return the handler address from the table");
        });
    });
}
