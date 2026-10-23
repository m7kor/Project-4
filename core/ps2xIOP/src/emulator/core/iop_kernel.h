#pragma once

#include "iop_cpu.h"

#include <cstddef>
#include <cstdint>
#include <map>
#include <deque>
#include <string>
#include <set>
#include <optional>

namespace ps2x::iop::detail
{
    class IopMemory;

    enum class IopThreadState : uint8_t
    {
        Dormant,
        Ready,
        Running,
        Sleep,
        Delay,
        Semaphore,
        EventFlag,
        Mailbox,
        Suspended,
        Dead,
    };

    struct IopThread
    {
        int id = 0;
        IopThreadState state = IopThreadState::Dormant;
        IopCpuState cpu;
        uint32_t interruptControl = 1u;
        uint32_t entry = 0;
        uint32_t stackBase = 0;
        uint32_t stackSize = 0;
        uint32_t priority = 0x40;
        uint32_t initialPriority = 0x40;
        uint32_t option = 0;
        uint32_t attr = 0;
        uint64_t wakeCycle = 0;
        int waitId = 0;
        uint32_t waitBits = 0;
        uint32_t waitMode = 0;
        uint32_t waitResultAddress = 0;
        int wakeupCount = 0;
        uint64_t waitSequence = 0;
        uint64_t readyOrder = 0;
    };

    class IopKernel
    {
    public:
        struct RpcCompletion { uint64_t token; uint32_t result; bool faulted; };
        explicit IopKernel(IopMemory &memory) noexcept;

        void reset();

        [[nodiscard]] bool dispatchThreadImport(uint16_t ordinal, IopCpuState &cpu, uint64_t currentCycle);
        [[nodiscard]] bool dispatchSemaphoreImport(uint16_t ordinal, IopCpuState &cpu);
        [[nodiscard]] bool dispatchEventImport(uint16_t ordinal, IopCpuState &cpu);
        [[nodiscard]] bool dispatchMailboxImport(uint16_t ordinal, IopCpuState &cpu);

        [[nodiscard]] int createInternalEventFlag(uint32_t attr, uint32_t option, uint32_t bits);
        [[nodiscard]] bool setInternalEventFlag(int id, uint32_t bits);

        void sleepCurrent(IopCpuState &cpu);
        void parkRpcCurrent(IopCpuState &cpu);
        [[nodiscard]] bool canStartRpcCall(int threadId) const;
        [[nodiscard]] bool hasThread(int threadId) const { return m_threads.contains(threadId); }
        [[nodiscard]] bool hasRpcCall(uint64_t token) const;
        [[nodiscard]] bool startRpcCall(int threadId, uint64_t token, uint32_t function,
            uint32_t number, uint32_t buffer, uint32_t bytes, uint32_t gp, uint32_t returnSentinel);
        [[nodiscard]] std::optional<RpcCompletion> finishRpcCall(IopThread &thread, uint32_t returnSentinel);
        void cancelRpcCall(uint64_t token);
        void delayCurrentUntil(uint64_t wakeCycle, IopCpuState &cpu);

        [[nodiscard]] IopThread *beginNextReady(uint64_t currentCycle);
        [[nodiscard]] uint64_t nextWakeCycle(uint64_t fallback) const;
        void endTimeslice(IopThread &thread, uint32_t returnSentinel);
        void cleanupDeadThreads();
        void terminateThreadsInRange(uint32_t base, uint32_t size);

        [[nodiscard]] size_t threadCount() const noexcept { return m_threads.size(); }
        [[nodiscard]] std::string describeThreads() const;

    private:
        struct RpcFrame { uint64_t token; IopCpuState cpu; uint32_t interruptControl; };
        std::map<int, RpcFrame> m_rpcFrames;
        std::set<int> m_rpcWaiters;
        struct Mailbox
        {
            uint32_t attr = 0;
            uint32_t option = 0;
            std::deque<uint32_t> messages;
        };
        void updateMailboxLinks(const Mailbox &mailbox);
        struct Semaphore
        {
            int id = 0;
            uint32_t attr = 0;
            uint32_t option = 0;
            int current = 0;
            int maximum = 1;
        };

        struct EventFlag
        {
            int id = 0;
            uint32_t bits = 0;
            uint32_t attr = 0;
            uint32_t option = 0;
        };

        [[nodiscard]] bool dispatchThreadImportImpl(uint16_t ordinal, IopCpuState &cpu, uint64_t currentCycle);
        [[nodiscard]] bool dispatchSemaphoreImportImpl(uint16_t ordinal, IopCpuState &cpu);
        [[nodiscard]] bool dispatchEventImportImpl(uint16_t ordinal, IopCpuState &cpu);
        [[nodiscard]] bool dispatchMailboxImportImpl(uint16_t ordinal, IopCpuState &cpu);
        // A syscall of the running thread that readies a higher-priority
        // thread is a voluntary dispatch point, even inside CpuSuspendIntr.
        void noteSyscallReadiedThreads() noexcept;
        [[nodiscard]] bool referThreadStatus(int id, uint32_t outputAddress);
        void wakeOneSemaphore(int id);
        [[nodiscard]] static bool eventSatisfied(const EventFlag &event, uint32_t bits, uint32_t mode);
        void wakeEventWaiters(EventFlag &event);

        // Only a negative ready result is cached. Every scheduling mutation
        // invalidates it; guest time and peripheral deadlines are unchanged.
        void invalidateIdleSchedule() noexcept { m_idleScheduleValid = false; }
        void makeReady(IopThread &thread, bool front = false) noexcept;
        uint64_t m_readyFront = uint64_t{1} << 63;
        uint64_t m_readyBack = uint64_t{1} << 63;
        bool m_idleScheduleValid = false;
        uint64_t m_idleWakeCycle = UINT64_MAX;

        IopMemory &m_memory;
        std::map<int, IopThread> m_threads;
        std::map<int, Semaphore> m_semaphores;
        std::map<int, EventFlag> m_eventFlags;
        std::map<int, Mailbox> m_mailboxes;
        uint32_t m_nextThreadId = 1;
        uint32_t m_nextSemaphoreId = 1;
        uint32_t m_nextEventFlagId = 1;
        uint32_t m_nextMailboxId = 1;
        uint64_t m_waitSequence = 0;
        uint32_t m_mailboxTraceCount = 0;
        IopThread *m_currentThread = nullptr;
        // The thread of the last host slice. While it keeps interrupts
        // suspended it cannot be preempted (timer, SIF and other external
        // wakeups are interrupts on the real IOP), only by its own syscalls.
        int m_sliceThreadId = 0;
        bool m_syscallReadiedHigher = false;
    };
}
