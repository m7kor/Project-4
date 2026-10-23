#include "MiniTest.h"
#include "ps2_runtime.h"
#include "ps2_syscalls.h"
#include "runtime/ee_scheduler.h"
#include "runtime/ps2_vu_control.h"

#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <exception>
#include <string_view>
#include <thread>
#include <utility>
#include <vector>

using namespace ps2_syscalls;

namespace
{
    constexpr int KE_OK = 0;
    constexpr int KE_EVF_COND = -421;

    constexpr uint32_t WEF_OR = 1u;
    constexpr uint32_t WEF_CLEAR = 0x10u;
    constexpr uint32_t WEF_CLEAR_ALL = 0x20u;

    struct Ps2EventFlagInfo
    {
        uint32_t attr;
        uint32_t option;
        uint32_t initBits;
        uint32_t currBits;
        int32_t numThreads;
        int32_t reserved1;
        int32_t reserved2;
    };

    static_assert(sizeof(Ps2EventFlagInfo) == 28u, "Unexpected Ps2EventFlagInfo layout.");

    struct TestEnv
    {
        std::vector<uint8_t> rdram;
        PS2Runtime runtime;

        TestEnv() : rdram(PS2_RAM_SIZE, 0u)
        {
        }
    };

    std::atomic<uint32_t> g_lastIntcArg{0u};
    constexpr uint32_t kIdleVSyncWaitPc = 0x00160000u;
    constexpr uint32_t kVSyncWaitPc = 0x00160100u;
    constexpr uint32_t kVSyncResumePc = 0x00160110u;
    constexpr uint32_t kIrqWaitPc = 0x00160200u;
    constexpr uint32_t kIrqResumePc = 0x00160210u;
    constexpr uint32_t kIntcHandlerPc = 0x00160220u;
    constexpr uint32_t kIrqStackWaitPc = 0x00160230u;
    constexpr uint32_t kIrqStackResumePc = 0x00160240u;
    constexpr uint32_t kIrqStackHandlerPc = 0x00160250u;
    constexpr uint32_t kIrqRegistrationSp = 0x001E0000u;
    constexpr uint32_t kIrqRegistrationGuardAddr = kIrqRegistrationSp - 16u;
    constexpr uint32_t kISemaWaitPc = 0x00160300u;
    constexpr uint32_t kISemaResumePc = 0x00160310u;
    constexpr uint32_t kISemaDriverPc = 0x00160320u;
    constexpr uint32_t kISemaHandlerPc = 0x00160330u;
    constexpr uint32_t kEventWaitPc = 0x00160400u;
    constexpr uint32_t kEventResumePc = 0x00160410u;
    constexpr uint32_t kEventProducerPc = 0x00160420u;
    constexpr uint32_t kTimer2WaitPc = 0x00160500u;
    constexpr uint32_t kTimer2ResumePc = 0x00160510u;
    constexpr uint32_t kTimer2HandlerPc = 0x00160520u;
    constexpr uint32_t kInvocationQueuePc = 0x00160530u;
    constexpr uint32_t kInvocationQueueResumePc = 0x00160540u;
    constexpr uint32_t kInvocationQueueHandlerPc = 0x00160550u;
    constexpr uint32_t kVu1IrqDriverPc = 0x00160600u;
    constexpr uint32_t kVu1IrqResumePc = 0x00160610u;
    constexpr uint32_t kVu1IrqHandlerPc = 0x00160620u;

    constexpr uint32_t kTimer2Count = 0x10001000u;
    constexpr uint32_t kTimer2Mode = 0x10001010u;
    constexpr uint32_t kTimer2Compare = 0x10001020u;
    constexpr uint32_t kTimerModeBusClockDiv256 = 2u;
    constexpr uint32_t kTimerModeCue = 1u << 7u;
    constexpr uint32_t kTimerModeCmpe = 1u << 8u;
    constexpr uint32_t kTimerModeEquf = 1u << 10u;

    constexpr uint32_t kVSyncFlagAddr = 0x1800u;
    constexpr uint32_t kVSyncTickAddr = 0x1810u;
    constexpr uint32_t kEventResultAddr = 0x1820u;

    std::vector<int> g_dispatchTrace;
    int g_testSemaphoreId = 0;
    int g_testEventFlagId = 0;
    int32_t g_resumedResult = 0;
    uint32_t g_vsyncFlag = 0;
    uint64_t g_vsyncTick = 0;
    uint64_t g_vsyncCsr = 0;
    std::atomic<bool> g_timer2Resumed{false};
    uint32_t g_irqObservedSp = 0u;
    uint32_t g_invocationQueueRuns = 0u;
    uint32_t g_invocationQueueSp = 0u;
    bool g_invocationQueueSpChanged = false;
    uint32_t g_vu1IrqControl = 0, g_vu1IrqCount = 0;
    uint32_t g_vu1IrqCause = 0, g_vu1IrqArgument = 0;
    uint32_t g_vu1StatusBeforeIrq = 0, g_vu1StatusInIrq = 0;
    bool g_vu1IrqEnabled = true;
    uint32_t g_foreignIntcPosts = 0;
    std::thread::id g_vu1DriverThread, g_vu1HandlerThread;

    void setRegU32(R5900Context &ctx, int reg, uint32_t value)
    {
        ctx.r[reg] = _mm_set_epi64x(0, static_cast<int64_t>(value));
    }

    int32_t getRegS32(const R5900Context &ctx, int reg)
    {
        return static_cast<int32_t>(::getRegU32(&ctx, reg));
    }

    bool callSyscall(uint32_t syscallNumber, uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        return dispatchNumericSyscall(syscallNumber, rdram, ctx, runtime);
    }

    void writeGuestU32(uint8_t *rdram, uint32_t addr, uint32_t value)
    {
        std::memcpy(rdram + addr, &value, sizeof(value));
    }

    uint32_t readGuestU32(const uint8_t *rdram, uint32_t addr)
    {
        uint32_t value = 0;
        std::memcpy(&value, rdram + addr, sizeof(value));
        return value;
    }

    uint64_t readGuestU64(const uint8_t *rdram, uint32_t addr)
    {
        uint64_t value = 0;
        std::memcpy(&value, rdram + addr, sizeof(value));
        return value;
    }

    template <typename Predicate>
    bool waitUntil(Predicate pred, std::chrono::milliseconds timeout)
    {
        const auto deadline = std::chrono::steady_clock::now() + timeout;
        while (std::chrono::steady_clock::now() < deadline)
        {
            if (pred())
            {
                return true;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        return pred();
    }

    void cleanupRuntime(TestEnv &env)
    {
        env.runtime.requestStop();
    }

    void idleVSyncWait(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        WaitVSyncTick(rdram, ctx, runtime, -1);
    }

    void schedulerVSyncWait(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        EeScheduler &scheduler = runtime->eeScheduler();
        scheduler.setVSyncFlag(kVSyncFlagAddr, kVSyncTickAddr);
        ctx->pc = kVSyncResumePc;
        scheduler.waitVSync(scheduler.currentVSyncTick());
    }

    void schedulerVSyncResume(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
    {
        g_vsyncFlag = readGuestU32(rdram, kVSyncFlagAddr);
        g_vsyncTick = readGuestU64(rdram, kVSyncTickAddr);
        g_vsyncCsr = runtime->memory().gs().csr.load(std::memory_order_acquire);
        g_resumedResult = getRegS32(*ctx, 2);
        ctx->pc = 0u;
        runtime->requestStop();
    }

    void schedulerIntcHandler(uint8_t *, R5900Context *ctx, PS2Runtime *)
    {
        g_dispatchTrace.push_back(2);
        g_lastIntcArg.store(getRegU32(ctx, 5), std::memory_order_relaxed);
        ctx->pc = 0u;
    }

    void schedulerIrqWait(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        g_dispatchTrace.push_back(1);
        EeScheduler &scheduler = runtime->eeScheduler();
        scheduler.addIrqHandler(false, 2u, kIntcHandlerPc, true, 0xCAFEu, 0u, 0u);
        ctx->pc = kIrqResumePc;
        scheduler.waitVSync(scheduler.currentVSyncTick());
    }

    void schedulerIrqResume(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        g_dispatchTrace.push_back(3);
        ctx->pc = 0u;
        runtime->requestStop();
    }

    void schedulerIrqStackHandler(uint8_t *rdram, R5900Context *ctx, PS2Runtime *)
    {
        g_irqObservedSp = getRegU32(ctx, 29);
        const uint64_t clobber = 0u;
        std::memcpy(rdram + g_irqObservedSp - sizeof(clobber), &clobber, sizeof(clobber));
        ctx->pc = 0u;
    }

    void schedulerIrqStackWait(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        EeScheduler &scheduler = runtime->eeScheduler();
        scheduler.addIrqHandler(false,
                                2u,
                                kIrqStackHandlerPc,
                                true,
                                0u,
                                0u,
                                kIrqRegistrationSp);
        ctx->pc = kIrqStackResumePc;
        scheduler.waitVSync(scheduler.currentVSyncTick());
    }

    void schedulerIrqStackResume(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        ctx->pc = 0u;
        runtime->requestStop();
    }

    void schedulerISemaHandler(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        g_dispatchTrace.push_back(3);
        runtime->eeScheduler().signalSemaphore(g_testSemaphoreId, true);
        g_dispatchTrace.push_back(4);
        ctx->pc = 0u;
    }

    void schedulerISemaDriver(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        g_dispatchTrace.push_back(2);
        ctx->pc = 0u;
        runtime->eeScheduler().dispatchIrq(true, 5u);
    }

    void schedulerISemaWait(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        g_dispatchTrace.push_back(1);
        EeScheduler &scheduler = runtime->eeScheduler();
        g_testSemaphoreId = scheduler.createSemaphore(0, 1, 0u, 0u);
        scheduler.addIrqHandler(true, 5u, kISemaHandlerPc, true, 0u, 0u, 0u);

        EeThreadCreateParams driver{};
        driver.entry = kISemaDriverPc;
        driver.stack = 0x1C000u;
        driver.stackSize = 0x1000u;
        driver.priority = 10;
        const int driverId = scheduler.createThread(driver);
        scheduler.startThread(driverId, 0u, *ctx, false);

        ctx->pc = kISemaResumePc;
        scheduler.waitSemaphore(g_testSemaphoreId);
    }

    void schedulerISemaResume(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        g_dispatchTrace.push_back(5);
        g_resumedResult = getRegS32(*ctx, 2);
        ctx->pc = 0u;
        runtime->requestStop();
    }

    void schedulerEventProducer(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        g_dispatchTrace.push_back(2);
        ctx->pc = 0u;
        runtime->eeScheduler().setEventFlag(g_testEventFlagId, 0x6u, false);
        runtime->eeScheduler().transferIfRequested(false);
    }

    void schedulerEventWait(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        g_dispatchTrace.push_back(1);
        EeScheduler &scheduler = runtime->eeScheduler();
        g_testEventFlagId = scheduler.createEventFlag(0u, 0u, 0u);

        EeThreadCreateParams producer{};
        producer.entry = kEventProducerPc;
        producer.stack = 0x1D000u;
        producer.stackSize = 0x1000u;
        producer.priority = 10;
        const int producerId = scheduler.createThread(producer);
        scheduler.startThread(producerId, 0u, *ctx, false);

        ctx->pc = kEventResumePc;
        scheduler.waitEventFlag(g_testEventFlagId, 0x2u, WEF_OR | WEF_CLEAR, kEventResultAddr);
    }

    void schedulerEventResume(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        g_dispatchTrace.push_back(3);
        g_resumedResult = getRegS32(*ctx, 2);
        ctx->pc = 0u;
        runtime->requestStop();
    }

    void schedulerTimer2Handler(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        g_dispatchTrace.push_back(2);
        PS2Memory &memory = runtime->memory();
        memory.writeIORegister(kTimer2Mode, memory.readIORegister(kTimer2Mode) | kTimerModeEquf);
        runtime->eeScheduler().signalSemaphore(g_testSemaphoreId, true);
        ctx->pc = 0u;
    }

    void schedulerTimer2Wait(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        g_dispatchTrace.push_back(1);
        EeScheduler &scheduler = runtime->eeScheduler();
        g_testSemaphoreId = scheduler.createSemaphore(0, 1, 0u, 0u);
        scheduler.addIrqHandler(false, 11u, kTimer2HandlerPc, true, 0u, 0u, 0u);

        PS2Memory &memory = runtime->memory();
        memory.writeIORegister(kTimer2Count, 0u);
        memory.writeIORegister(kTimer2Compare, 8u);
        memory.writeIORegister(kTimer2Mode,
                               kTimerModeBusClockDiv256 | kTimerModeCue | kTimerModeCmpe | kTimerModeEquf);

        ctx->pc = kTimer2ResumePc;
        scheduler.waitSemaphore(g_testSemaphoreId);
    }

    void schedulerTimer2Resume(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        g_dispatchTrace.push_back(3);
        g_resumedResult = getRegS32(*ctx, 2);
        g_timer2Resumed.store(true, std::memory_order_release);
        ctx->pc = 0u;
        runtime->requestStop();
    }

    void schedulerInvocationQueueHandler(uint8_t *, R5900Context *ctx, PS2Runtime *)
    {
        const uint32_t sp = getRegU32(ctx, 29);
        if (g_invocationQueueSp == 0u)
        {
            g_invocationQueueSp = sp;
        }
        else if (g_invocationQueueSp != sp)
        {
            g_invocationQueueSpChanged = true;
        }
        ++g_invocationQueueRuns;
        ctx->pc = 0u;
    }

    void schedulerQueueManyInvocations(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        constexpr uint32_t kInvocationCount = 96u;
        EeScheduler &scheduler = runtime->eeScheduler();
        for (uint32_t i = 0u; i < kInvocationCount; ++i)
        {
            GuestInvocation invocation{};
            invocation.kind = GuestInvocationKind::Interrupt;
            invocation.tag = i;
            invocation.context.pc = kInvocationQueueHandlerPc;
            setRegU32(invocation.context, 31, 0u);
            scheduler.queueInvocation(std::move(invocation));
        }
        ctx->pc = kInvocationQueueResumePc;
    }

    void schedulerInvocationQueueResume(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        ctx->pc = 0u;
        runtime->requestStop();
    }

    void schedulerVu1IrqHandler(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        ++g_vu1IrqCount;
        g_dispatchTrace.push_back(2);
        g_vu1HandlerThread = std::this_thread::get_id();
        g_vu1IrqCause = getRegU32(ctx, 4);
        g_vu1IrqArgument = getRegU32(ctx, 5);
        // The handler's own context observes the same retired hardware status.
        g_vu1StatusInIrq = ps2ReadVuStatus(*runtime, *ctx);
        ctx->pc = 0;
    }

    void schedulerVu1IrqDriver(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        g_dispatchTrace.push_back(1);
        g_vu1DriverThread = std::this_thread::get_id();
        auto &scheduler = runtime->eeScheduler();
        scheduler.addIrqHandler(false, 7u, kVu1IrqHandlerPc, true, 0xCAFEu, 0u, 0u);
        scheduler.setIrqCauseEnabled(false, 7u, g_vu1IrqEnabled);
        runtime->cpu().vu0_vpu_stat = 0xA5u; // Device-state fixture, not a guest write.
        ps2WriteVuFbrst(*runtime, *ctx, g_vu1IrqControl);
        if (g_foreignIntcPosts) {
            // Register an invalid source too: malformed device events must
            // be rejected instead of bypassing the 32-bit cause mask.
            scheduler.addIrqHandler(false, 32u, kVu1IrqHandlerPc, true, 0u, 0u, 0u);
            std::thread device([&] {
                for (uint32_t i = 0; i < g_foreignIntcPosts; ++i)
                    scheduler.postEvent({EeEventType::Intc, 7u, 0u});
                scheduler.postEvent({EeEventType::Intc, 32u, 0u});
            });
            device.join();
        } else {
            const uint32_t mscal = 0x14000000u;
            runtime->memory().processVIF1Data(reinterpret_cast<const uint8_t *>(&mscal), sizeof(mscal));
        }
        g_vu1StatusBeforeIrq = ps2ReadVuStatus(*runtime, *ctx);
        ctx->pc = kVu1IrqResumePc;
    }

    void schedulerVu1IrqResume(uint8_t *, R5900Context *ctx, PS2Runtime *runtime)
    {
        g_dispatchTrace.push_back(3);
        ctx->pc = 0;
        runtime->requestStop();
    }
}

void register_ps2_runtime_interrupt_tests()
{
    MiniTest::Case("PS2RuntimeInterrupt", [](TestCase &tc)
    {
        tc.Run("FBRST write is visible from a different EE context", [](TestCase &t) {
            TestEnv env;
            R5900Context writer{}, observer{};
            observer.vu0_fbrst = 0xCu; // Deliberately stale thread snapshot.
            ps2WriteVuFbrst(env.runtime, writer, 0xC00u);
            t.Equals(ps2ReadVuFbrst(env.runtime, observer), 0xC00u,
                     "a different EE context observes the same hardware control");
        });

        tc.Run("scheduler main-context copy preserves shared VU control and status", [](TestCase &t) {
            TestEnv env;
            env.runtime.cpu().vu0_fbrst = 0xC00u;
            env.runtime.cpu().vu0_vpu_stat = 0xA502u;
            env.runtime.registerFunction(kVu1IrqResumePc, schedulerVu1IrqResume);
            R5900Context main{};
            main.pc = kVu1IrqResumePc;
            env.runtime.eeScheduler().reset(env.rdram.data(), main);
            env.runtime.eeScheduler().run();
            t.Equals(env.runtime.cpu().vu0_fbrst, 0xC00u,
                     "publishing a stale main frame cannot overwrite hardware enables");
            t.Equals(env.runtime.cpu().vu0_vpu_stat, 0xA502u,
                     "publishing a stale main frame cannot overwrite hardware status");
        });

        tc.Run("VU1 VIF execution captures control written by another EE context", [](TestCase &t) {
            TestEnv env;
            t.IsTrue(env.runtime.memory().initialize(), "initialize microcode");
            t.IsTrue(env.runtime.syncCoreSubsystems(), "bind real VIF callback");
            const uint32_t code[] = {0u, 0x180002FFu, 0u, 0x400002FFu};
            std::memcpy(env.runtime.memory().getVU1Code(), code, sizeof(code));
            env.runtime.cpu().vu0_vpu_stat = 0xA5u;
            R5900Context writer{}, observer{};
            ps2WriteVuFbrst(env.runtime, writer, 0xC00u);
            const uint32_t mscal = 0x14000000u;
            env.runtime.memory().processVIF1Data(reinterpret_cast<const uint8_t *>(&mscal), sizeof(mscal));
            t.IsTrue(env.runtime.vu1().state().stoppedByD && env.runtime.vu1().state().stoppedByT,
                     "VIF sees D/T enables from the other context");
            t.Equals(ps2ReadVuStatus(env.runtime, observer), 0x6A5u,
                     "retired hardware stop is visible from a fresh observer");
        });

        tc.Run("VU0 fallback clears only its hardware status byte", [](TestCase &t) {
            TestEnv env;
            R5900Context context{};
            context.vu0_vpu_stat = env.runtime.cpu().vu0_vpu_stat = 0xABCDu;
            env.runtime.executeVU0Microprogram(env.rdram.data(), &context, PS2_VU0_CODE_SIZE);
            t.Equals(context.vu0_vpu_stat, 0xAB00u, "VU0 cannot clear the VU1 status byte");
            t.Equals(env.runtime.cpu().vu0_vpu_stat, 0xAB00u, "fallback retires only the VU0 byte");
        });

        for (uint32_t reset : {2u, 0x200u, 0x202u})
            tc.Run("FBRST reset stops only selected VU without clearing registers " + std::to_string(reset), [reset](TestCase &t) {
                TestEnv env;
                t.IsTrue(env.runtime.memory().initialize(), "initialize VU memories");
                R5900Context context{};
                env.runtime.cpu().vu0_vpu_stat = 0xABCDu;
                context.vu0_vpu_stat = 0x1234u; // A stale context must not replace hardware state.
                auto &memory = env.runtime.memory();
                memory.vif0_regs.stat = memory.vif1_regs.stat = 0x1234u;
                auto &vu0 = env.runtime.vu0().state();
                auto &vu1 = env.runtime.vu1().state();
                vu0.vf[7][2] = 17.5f;
                vu1.vf[9][1] = -43.25f;
                vu0.vi[3] = 81; vu1.vi[4] = 97;
                vu0.pc = 24; vu1.pc = 80;
                memory.getVU1Data()[17] = 0xA7;
                ps2WriteVuFbrst(env.runtime, context, reset | 0x0C0Cu);
                const uint32_t mask = (reset & 2u ? 0xFFu : 0u) | (reset & 0x200u ? 0xFF00u : 0u);
                t.Equals(context.vu0_vpu_stat, 0xABCDu & ~mask, "reset clears selected VPU status byte");
                t.Equals(context.vu0_fbrst, 0x0C0Cu & ~mask, "reset clears selected enable bits; action bits never latch");
                t.Equals(memory.vif0_regs.stat, reset & 2u ? 0x1230u : 0x1234u, "VU0 reset clears only VIF0 VEW");
                t.Equals(memory.vif1_regs.stat, reset & 0x200u ? 0x1230u : 0x1234u, "VU1 reset clears only VIF1 VEW");
                t.Equals(vu0.vf[7][2], 17.5f, "VU0 vector contents survive control reset");
                t.Equals(vu1.vf[9][1], -43.25f, "VU1 vector contents survive control reset");
                t.Equals(vu0.vi[3], 81, "VU0 integer contents survive control reset");
                t.Equals(vu1.vi[4], 97, "VU1 integer contents survive control reset");
                t.Equals(vu0.pc, 24u, "VU0 TPC survives control reset");
                t.Equals(vu1.pc, 80u, "VU1 TPC survives control reset");
                t.Equals(static_cast<uint32_t>(memory.getVU1Data()[17]), 0xA7u, "VU1 data memory survives reset");
            });

        tc.Run("FBRST ordinary enable write preserves VPU status and VIF wait flags", [](TestCase &t) {
            TestEnv env;
            R5900Context context{};
            env.runtime.cpu().vu0_vpu_stat = 0xABCDu;
            context.vu0_vpu_stat = 0x1234u;
            env.runtime.memory().vif0_regs.stat = 0x1234u;
            env.runtime.memory().vif1_regs.stat = 0x5678u;
            ps2WriteVuFbrst(env.runtime, context, 0xFFFFFCFCu);
            t.Equals(context.vu0_fbrst, 0x0C0Cu, "only D/T enables latch");
            t.Equals(context.vu0_vpu_stat, 0xABCDu, "enable-only write preserves status");
            t.Equals(env.runtime.memory().vif0_regs.stat, 0x1234u, "enable-only write preserves VIF0");
            t.Equals(env.runtime.memory().vif1_regs.stat, 0x5678u, "enable-only write preserves VIF1");
        });

        tc.Run("VU1 control reset cancels pending branch but MSCNT starts from retained TPC", [](TestCase &t) {
            TestEnv env;
            t.IsTrue(env.runtime.memory().initialize(), "initialize microcode and data");
            auto &memory = env.runtime.memory();
            auto &vu1 = env.runtime.vu1();
            const uint32_t code[] = {0u, 0x000002FFu, 0u, 0x000002FFu};
            std::memcpy(memory.getVU1Code(), code, sizeof(code));
            vu1.execute(memory.getVU1Code(), PS2_VU1_CODE_SIZE, memory.getVU1Data(), PS2_VU1_DATA_SIZE,
                        env.runtime.gs(), &memory, 0, 0, 0, 1);
            const auto pc = vu1.state().pc;
            const auto cycles = vu1.state().cycles;
            vu1.state().branchPending = true;
            vu1.state().branchDelay = 1;
            vu1.state().branchTarget = 0x100;
            R5900Context context{};
            ps2WriteVuFbrst(env.runtime, context, 0x200u);
            t.Equals(vu1.state().pc, pc, "control reset retains TPC");
            t.Equals(vu1.state().cycles, cycles, "control reset executes no instructions");
            t.IsTrue(!vu1.state().branchPending, "control reset cancels the old pending branch");
            vu1.resume(memory.getVU1Code(), PS2_VU1_CODE_SIZE, memory.getVU1Data(), PS2_VU1_DATA_SIZE,
                       env.runtime.gs(), &memory, 0, 0, 16);
            t.Equals(vu1.state().pc, pc + 16u * 8u, "MSCNT starts at retained TPC without reviving old branch");
            t.Equals(vu1.state().cycles, cycles + 16, "MSCNT is an explicit new execution request after reset");
            vu1.execute(memory.getVU1Code(), PS2_VU1_CODE_SIZE, memory.getVU1Data(), PS2_VU1_DATA_SIZE,
                        env.runtime.gs(), &memory, 0, 0, 0, 1);
            t.Equals(vu1.state().cycles, cycles + 17, "new MSCAL starts at the requested address");
        });

        for (uint32_t control : {0u, 0x400u, 0x800u, 0xC00u})
            tc.Run("VU1 D/T stop dispatches cause 7 with FBRST " + std::to_string(control), [control](TestCase &t) {
                TestEnv env;
                t.IsTrue(env.runtime.memory().initialize(), "initialize VU1 memory");
                t.IsTrue(env.runtime.syncCoreSubsystems(), "bind actual VIF/VU1 callbacks");
                const uint32_t code[] = {0u, 0x180002FFu, 0u, 0x400002FFu, 0u, 0x000002FFu};
                std::memcpy(env.runtime.memory().getVU1Code(), code, sizeof(code));
                env.runtime.registerFunction(kVu1IrqDriverPc, schedulerVu1IrqDriver);
                env.runtime.registerFunction(kVu1IrqResumePc, schedulerVu1IrqResume);
                env.runtime.registerFunction(kVu1IrqHandlerPc, schedulerVu1IrqHandler);
                g_vu1IrqControl = control;
                g_foreignIntcPosts = 0;
                g_vu1IrqEnabled = true;
                g_vu1IrqCount = g_vu1IrqCause = g_vu1IrqArgument = 0;
                g_vu1StatusBeforeIrq = g_vu1StatusInIrq = 0;
                g_dispatchTrace.clear();
                R5900Context mainContext{};
                mainContext.pc = kVu1IrqDriverPc;
                env.runtime.eeScheduler().reset(env.rdram.data(), mainContext);
                env.runtime.eeScheduler().run();
                const uint32_t expectedStatus = 0xA5u | (control >> 1);
                t.Equals(g_vu1StatusBeforeIrq, expectedStatus, "retirement preserves VU0 bits and updates only D/T");
                t.Equals(g_vu1IrqCount, control ? 1u : 0u, "one D/T instruction raises one cause-7 request; disabled enables raise none");
                const std::vector<int> expected = control ? std::vector<int>{1, 2, 3} : std::vector<int>{1, 3};
                t.IsTrue(g_dispatchTrace == expected, "VU1 interrupt must retire before interrupted guest resumes");
                if (control) {
                    t.Equals(g_vu1IrqCause, 7u, "interrupt handler receives the VU1 cause");
                    t.Equals(g_vu1IrqArgument, 0xCAFEu, "interrupt handler receives its registration argument");
                    t.Equals(g_vu1StatusInIrq, expectedStatus, "updated status is visible before handler activation");
                    t.IsTrue(g_vu1DriverThread == g_vu1HandlerThread, "handler must execute on EE, not on a worker");
                }
            });

        tc.Run("masked VU1 interrupt leaves the stop status visible without running the handler", [](TestCase &t) {
            TestEnv env;
            t.IsTrue(env.runtime.memory().initialize(), "initialize VU1 memory");
            t.IsTrue(env.runtime.syncCoreSubsystems(), "bind actual VIF/VU1 callbacks");
            const uint32_t code[] = {0u, 0x080002FFu};
            std::memcpy(env.runtime.memory().getVU1Code(), code, sizeof(code));
            env.runtime.registerFunction(kVu1IrqDriverPc, schedulerVu1IrqDriver);
            env.runtime.registerFunction(kVu1IrqResumePc, schedulerVu1IrqResume);
            env.runtime.registerFunction(kVu1IrqHandlerPc, schedulerVu1IrqHandler);
            g_vu1IrqControl = 0x800u;
            g_foreignIntcPosts = 0;
            g_vu1IrqEnabled = false;
            g_vu1IrqCount = 0;
            g_dispatchTrace.clear();
            R5900Context mainContext{};
            mainContext.pc = kVu1IrqDriverPc;
            env.runtime.eeScheduler().reset(env.rdram.data(), mainContext);
            env.runtime.eeScheduler().run();
            t.Equals(g_vu1StatusBeforeIrq, 0x4A5u, "masking INTC does not disable the VU1 T stop");
            t.Equals(g_vu1IrqCount, 0u, "masked INTC source cannot run its handler");
            t.IsTrue(g_dispatchTrace == std::vector<int>{1, 3}, "masked handler does not preempt base execution");
        });

        tc.Run("device INTC requests are owned and dispatched on EE with invalid causes rejected", [](TestCase &t) {
            TestEnv env;
            env.runtime.registerFunction(kVu1IrqDriverPc, schedulerVu1IrqDriver);
            env.runtime.registerFunction(kVu1IrqResumePc, schedulerVu1IrqResume);
            env.runtime.registerFunction(kVu1IrqHandlerPc, schedulerVu1IrqHandler);
            g_vu1IrqControl = 0;
            g_foreignIntcPosts = 16;
            g_vu1IrqEnabled = true;
            g_vu1IrqCount = 0;
            g_dispatchTrace.clear();
            R5900Context mainContext{};
            mainContext.pc = kVu1IrqDriverPc;
            env.runtime.eeScheduler().reset(env.rdram.data(), mainContext);
            env.runtime.eeScheduler().run();
            g_foreignIntcPosts = 0;
            t.Equals(g_vu1IrqCount, 16u, "each accepted device request executes exactly once; source 32 is invalid");
            t.Equals(g_vu1IrqCause, 7u, "device requests retain their cause after producer exits");
            t.Equals(g_vu1StatusInIrq, 0xA5u, "device event cannot mutate the interrupted context");
            t.IsTrue(g_vu1DriverThread == g_vu1HandlerThread, "foreign device must never run the guest handler itself");
            const std::vector<int> expected = [] {
                std::vector<int> order{1};
                order.insert(order.end(), 16u, 2);
                order.push_back(3);
                return order;
            }();
            t.IsTrue(g_dispatchTrace == expected, "requests retire before base resume in publication order");
        });

        tc.Run("scheduler reset cancels device INTC requests from the previous execution", [](TestCase &t) {
            TestEnv env;
            t.IsTrue(env.runtime.memory().initialize(), "initialize VU1 memory");
            t.IsTrue(env.runtime.syncCoreSubsystems(), "bind VIF/VU1 callbacks");
            const uint32_t code[] = {0u, 0x400002FFu, 0u, 0x000002FFu};
            std::memcpy(env.runtime.memory().getVU1Code(), code, sizeof(code));
            env.runtime.registerFunction(kVu1IrqDriverPc, schedulerVu1IrqDriver);
            env.runtime.registerFunction(kVu1IrqResumePc, schedulerVu1IrqResume);
            env.runtime.registerFunction(kVu1IrqHandlerPc, schedulerVu1IrqHandler);
            g_foreignIntcPosts = g_vu1IrqControl = g_vu1IrqCount = 0;
            g_vu1IrqEnabled = true;
            g_dispatchTrace.clear();
            R5900Context mainContext{};
            mainContext.pc = kVu1IrqDriverPc;
            env.runtime.eeScheduler().postEvent({EeEventType::Intc, 7u, 0u});
            env.runtime.eeScheduler().reset(env.rdram.data(), mainContext);
            // A handler exists even before the first guest dispatch, so an
            // uncleared old request would be observable rather than dropped.
            env.runtime.eeScheduler().addIrqHandler(false, 7u, kVu1IrqHandlerPc, true, 0xCAFEu, 0u, 0u);
            env.runtime.eeScheduler().run();
            t.Equals(g_vu1IrqCount, 0u, "reset must discard requests already owned by the old scheduler run");
            t.IsTrue(g_dispatchTrace == std::vector<int>{1, 3}, "old device event cannot enter a newly registered handler");
        });

        tc.Run("negative interrupt-safe EE syscall ids dispatch", [](TestCase &t)
        {
            TestEnv env;

            constexpr uint32_t kEventParamAddr = 0x1200u;
            constexpr uint32_t kStatusAddr = 0x1210u;

            const uint32_t eventParam[3] = {
                0u,
                0u,
                0u
            };
            std::memcpy(env.rdram.data() + kEventParamAddr, eventParam, sizeof(eventParam));

            R5900Context createCtx{};
            setRegU32(createCtx, 4, kEventParamAddr);
            CreateEventFlag(env.rdram.data(), &createCtx, &env.runtime);
            const int32_t eid = getRegS32(createCtx, 2);
            t.IsTrue(eid > 0, "CreateEventFlag should return a valid event id");

            R5900Context disableIntcCtx{};
            setRegU32(disableIntcCtx, 4, 2u);
            t.IsTrue(callSyscall(static_cast<uint32_t>(-0x1B), env.rdram.data(), &disableIntcCtx, &env.runtime),
                     "negative iDisableIntc syscall id should dispatch");
            t.Equals(getRegS32(disableIntcCtx, 2), KE_OK, "negative iDisableIntc should return KE_OK");

            R5900Context enableIntcCtx{};
            setRegU32(enableIntcCtx, 4, 2u);
            t.IsTrue(callSyscall(static_cast<uint32_t>(-0x1A), env.rdram.data(), &enableIntcCtx, &env.runtime),
                     "negative iEnableIntc syscall id should dispatch");
            t.Equals(getRegS32(enableIntcCtx, 2), KE_OK, "negative iEnableIntc should return KE_OK");

            R5900Context disableDmacCtx{};
            setRegU32(disableDmacCtx, 4, 5u);
            t.IsTrue(callSyscall(static_cast<uint32_t>(-0x1D), env.rdram.data(), &disableDmacCtx, &env.runtime),
                     "negative iDisableDmac syscall id should dispatch");
            t.Equals(getRegS32(disableDmacCtx, 2), KE_OK, "negative iDisableDmac should return KE_OK");

            R5900Context enableDmacCtx{};
            setRegU32(enableDmacCtx, 4, 5u);
            t.IsTrue(callSyscall(static_cast<uint32_t>(-0x1C), env.rdram.data(), &enableDmacCtx, &env.runtime),
                     "negative iEnableDmac syscall id should dispatch");
            t.Equals(getRegS32(enableDmacCtx, 2), KE_OK, "negative iEnableDmac should return KE_OK");

            R5900Context setEventFlagCtx{};
            setRegU32(setEventFlagCtx, 4, static_cast<uint32_t>(eid));
            setRegU32(setEventFlagCtx, 5, 0x6u);
            t.IsTrue(callSyscall(static_cast<uint32_t>(-0x53), env.rdram.data(), &setEventFlagCtx, &env.runtime),
                     "negative iSetEventFlag syscall id should dispatch");
            t.Equals(getRegS32(setEventFlagCtx, 2), KE_OK, "negative iSetEventFlag should return KE_OK");

            R5900Context referCtx{};
            setRegU32(referCtx, 4, static_cast<uint32_t>(eid));
            setRegU32(referCtx, 5, kStatusAddr);
            ReferEventFlagStatus(env.rdram.data(), &referCtx, &env.runtime);
            t.Equals(getRegS32(referCtx, 2), KE_OK, "ReferEventFlagStatus should succeed after iSetEventFlag");
            t.Equals(readGuestU32(env.rdram.data(), kStatusAddr + 12u), 0x6u,
                     "negative iSetEventFlag should publish the requested bits");

            R5900Context deleteCtx{};
            setRegU32(deleteCtx, 4, static_cast<uint32_t>(eid));
            DeleteEventFlag(env.rdram.data(), &deleteCtx, &env.runtime);

            cleanupRuntime(env);
        });

        tc.Run("PollEventFlag WEF_CLEAR clears only matched bits", [](TestCase &t)
        {
            TestEnv env;

            constexpr uint32_t kParamAddr = 0x1400u;
            constexpr uint32_t kResBitsAddr = 0x1410u;
            constexpr uint32_t kStatusAddr = 0x1420u;

            const uint32_t eventParam[3] = {
                0u, // attr
                0u, // option
                0x7u // init bits: 0b111
            };
            std::memcpy(env.rdram.data() + kParamAddr, eventParam, sizeof(eventParam));

            R5900Context createCtx{};
            setRegU32(createCtx, 4, kParamAddr);
            CreateEventFlag(env.rdram.data(), &createCtx, &env.runtime);
            const int32_t eid = getRegS32(createCtx, 2);
            t.IsTrue(eid > 0, "CreateEventFlag should return a valid id");

            R5900Context pollCtx{};
            setRegU32(pollCtx, 4, static_cast<uint32_t>(eid));
            setRegU32(pollCtx, 5, 0x1u);
            setRegU32(pollCtx, 6, WEF_OR | WEF_CLEAR);
            setRegU32(pollCtx, 7, kResBitsAddr);
            PollEventFlag(env.rdram.data(), &pollCtx, &env.runtime);
            t.Equals(getRegS32(pollCtx, 2), KE_OK, "PollEventFlag should succeed when condition is met");
            t.Equals(readGuestU32(env.rdram.data(), kResBitsAddr), 0x7u, "PollEventFlag should report bits before clear");

            R5900Context referCtx{};
            setRegU32(referCtx, 4, static_cast<uint32_t>(eid));
            setRegU32(referCtx, 5, kStatusAddr);
            ReferEventFlagStatus(env.rdram.data(), &referCtx, &env.runtime);
            t.Equals(getRegS32(referCtx, 2), KE_OK, "ReferEventFlagStatus should succeed");

            Ps2EventFlagInfo info{};
            std::memcpy(&info, env.rdram.data() + kStatusAddr, sizeof(info));
            t.Equals(info.currBits, 0x6u, "WEF_CLEAR should clear only requested bits, not all bits");

            R5900Context pollMissCtx{};
            setRegU32(pollMissCtx, 4, static_cast<uint32_t>(eid));
            setRegU32(pollMissCtx, 5, 0x1u);
            setRegU32(pollMissCtx, 6, WEF_OR);
            setRegU32(pollMissCtx, 7, 0u);
            PollEventFlag(env.rdram.data(), &pollMissCtx, &env.runtime);
            t.Equals(getRegS32(pollMissCtx, 2), KE_EVF_COND,
                     "after clearing bit 0, polling for bit 0 should fail condition");

            R5900Context deleteCtx{};
            setRegU32(deleteCtx, 4, static_cast<uint32_t>(eid));
            DeleteEventFlag(env.rdram.data(), &deleteCtx, &env.runtime);
            t.Equals(getRegS32(deleteCtx, 2), KE_OK, "DeleteEventFlag should succeed");

            cleanupRuntime(env);
        });

        tc.Run("VBlank deadline resumes the waiter and publishes flag tick and FIELD atomically", [](TestCase &t)
        {
            TestEnv env;
            t.IsTrue(env.runtime.memory().initialize(), "runtime memory initialize should succeed");
            env.runtime.gs().init(env.runtime.memory().getGSVRAM(), PS2_GS_VRAM_SIZE,
                                  &env.runtime.memory().gs());
            env.runtime.memory().gs().pmode = 1u;
            env.runtime.registerFunction(kVSyncWaitPc, schedulerVSyncWait);
            env.runtime.registerFunction(kVSyncResumePc, schedulerVSyncResume);

            g_resumedResult = -1;
            g_vsyncFlag = 0u;
            g_vsyncTick = 0u;
            g_vsyncCsr = 0u;
            R5900Context mainContext{};
            mainContext.pc = kVSyncWaitPc;
            env.runtime.eeScheduler().reset(env.rdram.data(), mainContext);
            env.runtime.eeScheduler().run();

            t.Equals(g_vsyncFlag, 1u, "VBlank start should set the registered guest flag");
            t.Equals(g_vsyncTick, 1ull, "the first centralized VBlank deadline should publish tick one");
            t.Equals(g_resumedResult, 0, "the first VBlank field should return even-field parity");
            t.Equals(g_vsyncCsr & 0x2000ull, 0x2000ull,
                     "the first VBlank should publish GS CSR.FIELD before resuming guest code");
            const auto presented = env.runtime.gs().getDebugSnapshot();
            t.IsTrue(presented.hasHostPresentationFrame, "VBlank must latch output without a host upload call");
            t.Equals(presented.hostPresentationRequest.vsyncTick, uint64_t(1),
                     "the completed field must be published before the guest waiter resumes");
        });

        tc.Run("VBlank IRQ invocation completes before the resumed base context", [](TestCase &t)
        {
            TestEnv env;
            env.runtime.registerFunction(kIrqWaitPc, schedulerIrqWait);
            env.runtime.registerFunction(kIrqResumePc, schedulerIrqResume);
            env.runtime.registerFunction(kIntcHandlerPc, schedulerIntcHandler);

            g_dispatchTrace.clear();
            g_lastIntcArg.store(0u, std::memory_order_relaxed);
            R5900Context mainContext{};
            mainContext.pc = kIrqWaitPc;
            env.runtime.eeScheduler().reset(env.rdram.data(), mainContext);
            env.runtime.eeScheduler().run();

            const std::vector<int> expected{1, 2, 3};
            t.IsTrue(g_dispatchTrace == expected,
                     "the dispatcher should run wait, IRQ frame, then the resumed base context in exact order");
            t.Equals(g_lastIntcArg.load(std::memory_order_relaxed), 0xCAFEu,
                     "the IRQ frame should receive its registered argument");
        });

        tc.Run("IRQ callbacks use an isolated invocation stack", [](TestCase &t)
        {
            TestEnv env;
            env.runtime.registerFunction(kIrqStackWaitPc, schedulerIrqStackWait);
            env.runtime.registerFunction(kIrqStackResumePc, schedulerIrqStackResume);
            env.runtime.registerFunction(kIrqStackHandlerPc, schedulerIrqStackHandler);

            constexpr uint64_t guard = 0x1122334455667788ull;
            std::memcpy(env.rdram.data() + kIrqRegistrationGuardAddr, &guard, sizeof(guard));
            g_irqObservedSp = 0u;

            R5900Context mainContext{};
            mainContext.pc = kIrqStackWaitPc;
            env.runtime.eeScheduler().reset(env.rdram.data(), mainContext);
            env.runtime.eeScheduler().run();

            uint64_t guardAfter = 0u;
            std::memcpy(&guardAfter,
                        env.rdram.data() + kIrqRegistrationGuardAddr,
                        sizeof(guardAfter));
            t.IsTrue(g_irqObservedSp != 0u && g_irqObservedSp != kIrqRegistrationSp,
                     "IRQ handler must not reuse the transient stack captured at registration");
            t.Equals(guardAfter, guard,
                     "IRQ handler stack writes must not clobber the registering thread's live frame");
        });

        tc.Run("pending async callbacks execute sequentially on a reusable invocation stack", [](TestCase &t)
        {
            TestEnv env;
            env.runtime.registerFunction(kInvocationQueuePc, schedulerQueueManyInvocations);
            env.runtime.registerFunction(kInvocationQueueResumePc, schedulerInvocationQueueResume);
            env.runtime.registerFunction(kInvocationQueueHandlerPc, schedulerInvocationQueueHandler);

            g_invocationQueueRuns = 0u;
            g_invocationQueueSp = 0u;
            g_invocationQueueSpChanged = false;

            R5900Context mainContext{};
            mainContext.pc = kInvocationQueuePc;
            env.runtime.eeScheduler().reset(env.rdram.data(), mainContext);

            bool exhausted = false;
            try
            {
                env.runtime.eeScheduler().run();
            }
            catch (const std::runtime_error &error)
            {
                exhausted = std::string_view(error.what()) == "EE invocation stack space exhausted";
            }

            t.IsFalse(exhausted, "queued callbacks must not consume one invocation stack per pending item");
            t.Equals(g_invocationQueueRuns, 96u, "every queued callback should execute exactly once");
            t.IsFalse(g_invocationQueueSpChanged, "sequential callbacks should reuse the same stack depth");
        });

        tc.Run("iSignalSema defers selection until IRQ return", [](TestCase &t)
        {
            TestEnv env;
            env.runtime.registerFunction(kISemaWaitPc, schedulerISemaWait);
            env.runtime.registerFunction(kISemaResumePc, schedulerISemaResume);
            env.runtime.registerFunction(kISemaDriverPc, schedulerISemaDriver);
            env.runtime.registerFunction(kISemaHandlerPc, schedulerISemaHandler);

            g_dispatchTrace.clear();
            g_resumedResult = -1;
            R5900Context mainContext{};
            mainContext.pc = kISemaWaitPc;
            env.runtime.eeScheduler().reset(env.rdram.data(), mainContext);
            env.runtime.eeScheduler().run();

            const std::vector<int> expected{1, 2, 3, 4, 5};
            t.IsTrue(g_dispatchTrace == expected,
                     "iSignalSema should make the waiter ready but finish the IRQ frame before selecting it");
            t.Equals(g_resumedResult, g_testSemaphoreId,
                     "the resumed waiter should receive the semaphore id from the direct FIFO handoff");
            const EeSemaphore *semaphore = env.runtime.eeScheduler().semaphore(g_testSemaphoreId);
            t.IsTrue(semaphore != nullptr, "the signaled semaphore should still exist");
            if (semaphore)
            {
                t.Equals(semaphore->count, 0, "direct handoff must not increment the semaphore count");
                t.Equals(static_cast<uint32_t>(semaphore->waiters.size()), 0u,
                         "the awakened waiter must be removed from the semaphore queue");
            }
        });

        tc.Run("event-flag completion writes observed bits before strict-priority resume", [](TestCase &t)
        {
            TestEnv env;
            env.runtime.registerFunction(kEventWaitPc, schedulerEventWait);
            env.runtime.registerFunction(kEventResumePc, schedulerEventResume);
            env.runtime.registerFunction(kEventProducerPc, schedulerEventProducer);

            g_dispatchTrace.clear();
            g_resumedResult = -1;
            R5900Context mainContext{};
            mainContext.pc = kEventWaitPc;
            env.runtime.eeScheduler().reset(env.rdram.data(), mainContext);
            env.runtime.eeScheduler().run();

            const std::vector<int> expected{1, 2, 3};
            t.IsTrue(g_dispatchTrace == expected,
                     "the higher-priority event waiter should resume at the producer scheduling point");
            t.Equals(g_resumedResult, KE_OK, "the resumed event waiter should receive KE_OK");
            t.Equals(readGuestU32(env.rdram.data(), kEventResultAddr), 0x6u,
                     "the event output should contain the bits observed before clear mode is applied");
            const EeEventFlag *flag = env.runtime.eeScheduler().eventFlag(g_testEventFlagId);
            t.IsTrue(flag != nullptr, "the event flag should still exist");
            if (flag)
            {
                t.Equals(flag->bits, 0x4u, "WEF_CLEAR should remove only the requested matched bit");
            }
        });

        tc.Run("EE Timer2 compare IRQ wakes a DelayThread-style semaphore wait", [](TestCase &t)
        {
            TestEnv env;
            t.IsTrue(env.runtime.memory().initialize(), "runtime memory initialize should succeed");
            env.runtime.registerFunction(kTimer2WaitPc, schedulerTimer2Wait);
            env.runtime.registerFunction(kTimer2ResumePc, schedulerTimer2Resume);
            env.runtime.registerFunction(kTimer2HandlerPc, schedulerTimer2Handler);

            g_dispatchTrace.clear();
            g_resumedResult = -1;
            g_timer2Resumed.store(false, std::memory_order_release);
            R5900Context mainContext{};
            mainContext.pc = kTimer2WaitPc;
            std::atomic<bool> schedulerThrew{false};
            std::thread gameThread([&]()
            {
                try
                {
                    env.runtime.eeScheduler().reset(env.rdram.data(), mainContext);
                    env.runtime.eeScheduler().run();
                }
                catch (...)
                {
                    schedulerThrew.store(true, std::memory_order_release);
                }
            });

            const bool resumed = waitUntil([]()
            {
                return g_timer2Resumed.load(std::memory_order_acquire);
            }, std::chrono::milliseconds(150));
            if (!resumed)
            {
                env.runtime.requestStop();
            }
            gameThread.join();

            t.IsTrue(resumed, "Timer2 compare should dispatch INTC_TIM2 and wake the semaphore waiter");
            t.IsFalse(schedulerThrew.load(std::memory_order_acquire), "Timer2 IRQ path should not throw");
            const std::vector<int> expected{1, 2, 3};
            t.IsTrue(g_dispatchTrace == expected,
                     "Timer2 flow should run wait, interrupt handler, then the resumed thread");
            t.Equals(g_resumedResult, g_testSemaphoreId,
                     "the Timer2 handler should hand the semaphore directly to the waiter");
        });

        tc.Run("scheduler stop wakes an idle VSync wait without a timeout", [](TestCase &t)
        {
            TestEnv env;
            env.runtime.registerFunction(kIdleVSyncWaitPc, idleVSyncWait);

            R5900Context mainContext{};
            mainContext.pc = kIdleVSyncWaitPc;
            std::atomic<bool> schedulerDone{false};
            std::atomic<bool> schedulerThrew{false};
            std::thread gameThread([&]()
            {
                try
                {
                    env.runtime.eeScheduler().reset(env.rdram.data(), mainContext);
                    env.runtime.eeScheduler().run();
                }
                catch (...)
                {
                    schedulerThrew.store(true, std::memory_order_release);
                }
                schedulerDone.store(true, std::memory_order_release);
            });

            const bool becameIdle = waitUntil([&]() {
                const EeKernelSnapshot snapshot = env.runtime.eeScheduler().snapshot();
                return snapshot.runningThreadId == 0 &&
                       !snapshot.threads.empty() &&
                       snapshot.threads.front().waitReason == EeWaitReason::VSync;
            }, std::chrono::milliseconds(80));

            env.runtime.requestStop();
            gameThread.join();

            t.IsTrue(becameIdle, "VSync wait should leave the sole guest thread waiting");
            t.IsTrue(schedulerDone.load(std::memory_order_acquire),
                     "requestStop should wake the scheduler's event wait");
            t.IsFalse(schedulerThrew.load(std::memory_order_acquire),
                      "the scheduler stop path should not throw");

            cleanupRuntime(env);
        });
    });
}
