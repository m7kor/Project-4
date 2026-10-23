#include "iop_kernel.h"

#include "iop_memory.h"
#include "../iop_emulator_const.h"

#include <algorithm>
#include <cstdlib>
#include <iostream>
#include <sstream>

namespace ps2x::iop::detail
{
    namespace
    {
        uint32_t alignUp(uint32_t value, uint32_t alignment)
        {
            if (alignment <= 1u)
                return value;
            const uint32_t mask = alignment - 1u;
            return (value + mask) & ~mask;
        }
    }

    IopKernel::IopKernel(IopMemory &memory) noexcept
        : m_memory(memory)
    {
    }

    void IopKernel::reset()
    {
        invalidateIdleSchedule();
        m_threads.clear();
        m_rpcFrames.clear();
        m_rpcWaiters.clear();
        m_semaphores.clear();
        m_eventFlags.clear();
        m_mailboxes.clear();
        m_nextThreadId = 1;
        m_nextSemaphoreId = 1;
        m_nextEventFlagId = 1;
        m_nextMailboxId = 1;
        m_waitSequence = 0;
        m_readyFront = m_readyBack = uint64_t{1} << 63;
        m_mailboxTraceCount = 0;
        m_currentThread = nullptr;
        m_sliceThreadId = 0;
        m_syscallReadiedHigher = false;
    }

    bool IopKernel::dispatchThreadImport(uint16_t ordinal, IopCpuState &cpu, uint64_t currentCycle)
    {
        const bool handled = dispatchThreadImportImpl(ordinal, cpu, currentCycle);
        noteSyscallReadiedThreads();
        return handled;
    }

    bool IopKernel::dispatchThreadImportImpl(uint16_t ordinal, IopCpuState &cpu, uint64_t currentCycle)
    {
        invalidateIdleSchedule();
        const auto setV0 = [&](int32_t value)
        {
            cpu.gpr[2] = static_cast<uint32_t>(value);
        };

        switch (ordinal)
        {
        case 4: // CreateThread
        {
            const uint32_t descriptor = cpu.gpr[4];
            IopThread thread;
            thread.id = static_cast<int>(m_nextThreadId++);
            thread.attr = m_memory.read32(descriptor + 0u);
            thread.option = m_memory.read32(descriptor + 4u);
            thread.entry = m_memory.read32(descriptor + 8u);
            thread.stackSize = std::max<uint32_t>(m_memory.read32(descriptor + 12u), 0x100u);
            thread.priority = std::clamp<uint32_t>(m_memory.read32(descriptor + 16u), 1u, 126u);
            thread.initialPriority = thread.priority;
            if (std::getenv("PS2X_CAPTURE_DIR"))
                std::cerr << "[IOP thread create] id=" << thread.id << " entry=0x" << std::hex
                          << thread.entry << " attr=0x" << thread.attr << std::dec
                          << " priority=" << thread.priority << " stack=" << thread.stackSize << '\n';
            thread.stackBase = m_memory.allocate(thread.stackSize + kStackGuardBytes, 16u);
            if (thread.stackBase == 0u)
            {
                setV0(-400);
                return true;
            }
            const int id = thread.id;
            m_threads.emplace(id, std::move(thread));
            setV0(id);
            return true;
        }
        case 5: // DeleteThread
        {
            const int id = static_cast<int>(cpu.gpr[4]);
            const auto it = m_threads.find(id);
            if (it == m_threads.end())
            {
                setV0(-1);
                return true;
            }
            if (m_currentThread == &it->second)
            {
                setV0(-1);
                return true;
            }
            if (it->second.stackBase != 0u)
                (void)m_memory.freeAllocation(it->second.stackBase);
            m_rpcFrames.erase(id);
            m_rpcWaiters.erase(id);
            m_threads.erase(it);
            setV0(0);
            return true;
        }
        case 6: // StartThread
        case 7: // StartThreadArgs
        {
            const int id = static_cast<int>(cpu.gpr[4]);
            if (std::getenv("PS2X_CAPTURE_DIR"))
                std::cerr << "[IOP thread start] id=" << id << '\n';
            const auto it = m_threads.find(id);
            if (it == m_threads.end())
            {
                setV0(-1);
                return true;
            }
            IopThread &thread = it->second;
            thread.cpu = {};
            thread.interruptControl = 1u;
            thread.cpu.pc = thread.entry;
            thread.cpu.gpr[4] = cpu.gpr[5];
            thread.cpu.gpr[5] = ordinal == 7 ? cpu.gpr[6] : 0u;
            thread.cpu.gpr[28] = cpu.gpr[28];
            thread.cpu.gpr[29] = alignUp(thread.stackBase + thread.stackSize, 16u) - 16u;
            thread.cpu.gpr[31] = kThreadReturnSentinel;
            makeReady(thread);
            setV0(0);
            return true;
        }
        case 8: // ExitThread
        case 9: // ExitDeleteThread
            if (m_currentThread != nullptr)
            {
                m_currentThread->state = ordinal == 9 ? IopThreadState::Dead : IopThreadState::Dormant;
                cpu.stopped = true;
                cpu.yielded = true;
            }
            setV0(0);
            return true;
        case 10:
        case 11: // TerminateThread
        {
            const int id = static_cast<int>(cpu.gpr[4]);
            const auto it = m_threads.find(id);
            if (it == m_threads.end())
            {
                setV0(-1);
                return true;
            }
            it->second.state = IopThreadState::Dormant;
            setV0(0);
            return true;
        }
        case 12:
        case 13:
            setV0(0);
            return true;
        case 14:
        case 15:
        {
            int id = static_cast<int>(cpu.gpr[4]);
            if (id == 0 && m_currentThread != nullptr)
                id = m_currentThread->id;
            const auto it = m_threads.find(id);
            if (it == m_threads.end())
            {
                setV0(-1);
                return true;
            }
            const uint32_t oldPriority = it->second.priority;
            it->second.priority = std::clamp<uint32_t>(cpu.gpr[5], 1u, 126u);
            if (it->second.state == IopThreadState::Ready)
                makeReady(it->second);
            else if (m_currentThread == &it->second && it->second.priority > oldPriority)
                it->second.cpu.yielded = true;
            setV0(0);
            return true;
        }
        case 16:
        case 17:
        {
            const uint32_t priority = cpu.gpr[4] == 0u && m_currentThread
                                          ? m_currentThread->priority : cpu.gpr[4];
            IopThread *head = nullptr;
            for (auto &[id, thread] : m_threads)
                if (thread.state == IopThreadState::Ready && thread.priority == priority &&
                    (!head || thread.readyOrder < head->readyOrder)) head = &thread;
            if (m_currentThread && m_currentThread->priority == priority)
            {
                // Explicit rotation, unlike a host budget boundary, moves
                // the running thread to the back of its priority queue.
                m_currentThread->cpu.yielded = true;
            }
            else if (head) makeReady(*head);
            setV0(0);
            return true;
        }
        case 18:
        case 19:
        {
            const int id = static_cast<int>(cpu.gpr[4]);
            const auto it = m_threads.find(id);
            if (it == m_threads.end())
            {
                setV0(-1);
                return true;
            }
            if (it->second.state == IopThreadState::Sleep ||
                it->second.state == IopThreadState::Delay ||
                it->second.state == IopThreadState::Semaphore ||
                it->second.state == IopThreadState::EventFlag ||
                it->second.state == IopThreadState::Mailbox)
            {
                makeReady(it->second);
            }
            setV0(0);
            return true;
        }
        case 20:
            setV0(m_currentThread != nullptr ? m_currentThread->id : 0);
            return true;
        case 21:
            setV0(0x1000);
            return true;
        case 22:
        case 23:
            setV0(referThreadStatus(static_cast<int>(cpu.gpr[4]), cpu.gpr[5]) ? 0 : -1);
            return true;
        case 24: // SleepThread
            if (m_currentThread != nullptr)
            {
                if (m_currentThread->wakeupCount > 0)
                    --m_currentThread->wakeupCount;
                else
                    sleepCurrent(cpu);
            }
            setV0(0);
            return true;
        case 25:
        case 26:
        {
            const int id = static_cast<int>(cpu.gpr[4]);
            const auto it = m_threads.find(id);
            if (it == m_threads.end())
            {
                setV0(-1);
                return true;
            }
            if (it->second.state == IopThreadState::Sleep)
                makeReady(it->second);
            else
                ++it->second.wakeupCount;
            setV0(0);
            return true;
        }
        case 27:
        case 28:
        {
            const int id = static_cast<int>(cpu.gpr[4]);
            const auto it = m_threads.find(id);
            if (it == m_threads.end())
            {
                setV0(-1);
                return true;
            }
            const int old = it->second.wakeupCount;
            it->second.wakeupCount = 0;
            setV0(old);
            return true;
        }
        case 29:
        case 30: // SuspendThread / iSuspendThread
        {
            const int id = static_cast<int>(cpu.gpr[4]);
            const auto it = m_threads.find(id);
            if (it == m_threads.end())
            {
                setV0(-1);
                return true;
            }
            it->second.state = IopThreadState::Suspended;
            if (m_currentThread == &it->second)
                cpu.yielded = true;
            setV0(0);
            return true;
        }
        case 31:
        case 32: // ResumeThread / iResumeThread
        {
            const int id = static_cast<int>(cpu.gpr[4]);
            const auto it = m_threads.find(id);
            if (it == m_threads.end())
            {
                setV0(-1);
                return true;
            }
            if (it->second.state == IopThreadState::Suspended)
                makeReady(it->second);
            setV0(0);
            return true;
        }
        case 33: // DelayThread
            if (m_currentThread != nullptr)
            {
                const uint64_t delayCycles = (static_cast<uint64_t>(cpu.gpr[4]) * kIopClockHz + 999'999ull) / 1'000'000ull;
                delayCurrentUntil(currentCycle + std::max<uint64_t>(delayCycles, 1u), cpu);
            }
            setV0(0);
            return true;
        case 34: // GetSystemTime
            m_memory.write32(cpu.gpr[4], static_cast<uint32_t>(currentCycle));
            m_memory.write32(cpu.gpr[4] + 4u, static_cast<uint32_t>(currentCycle >> 32u));
            setV0(0);
            return true;
        case 35:
        case 36:
        case 37:
        case 38:
            setV0(0);
            return true;
        case 39: // USec2SysClock
        {
            const uint64_t cycles = (static_cast<uint64_t>(cpu.gpr[4]) * kIopClockHz) / 1'000'000ull;
            m_memory.write32(cpu.gpr[5], static_cast<uint32_t>(cycles));
            m_memory.write32(cpu.gpr[5] + 4u, static_cast<uint32_t>(cycles >> 32u));
            setV0(0);
            return true;
        }
        case 40:
        {
            const uint64_t cycles = static_cast<uint64_t>(m_memory.read32(cpu.gpr[4])) | (static_cast<uint64_t>(m_memory.read32(cpu.gpr[4] + 4u)) << 32u);
            const uint64_t usec = (cycles * 1'000'000ull) / kIopClockHz;
            if (cpu.gpr[5] != 0u)
                m_memory.write32(cpu.gpr[5], static_cast<uint32_t>(usec / 1'000'000ull));
            if (cpu.gpr[6] != 0u)
                m_memory.write32(cpu.gpr[6], static_cast<uint32_t>(usec % 1'000'000ull));
            setV0(0);
            return true;
        }
        case 41:
            setV0(0);
            return true;
        default:
            return false;
        }
    }

    bool IopKernel::referThreadStatus(int id, uint32_t outputAddress)
    {
        if (id == 0 && m_currentThread != nullptr)
            id = m_currentThread->id;
        const auto it = m_threads.find(id);
        if (it == m_threads.end() || outputAddress == 0u)
            return false;

        const IopThread &thread = it->second;
        uint32_t status = 0x10u;
        switch (thread.state)
        {
        case IopThreadState::Running:
            status = 0x01u;
            break;
        case IopThreadState::Ready:
            status = 0x02u;
            break;
        case IopThreadState::Sleep:
        case IopThreadState::Delay:
        case IopThreadState::Semaphore:
        case IopThreadState::EventFlag:
        case IopThreadState::Mailbox:
            status = 0x04u;
            break;
        case IopThreadState::Suspended:
            status = 0x08u;
            break;
        default:
            status = 0x10u;
            break;
        }

        m_memory.write32(outputAddress + 0u, thread.attr);
        m_memory.write32(outputAddress + 4u, thread.option);
        m_memory.write32(outputAddress + 8u, status);
        m_memory.write32(outputAddress + 12u, thread.entry);
        m_memory.write32(outputAddress + 16u, thread.stackBase);
        m_memory.write32(outputAddress + 20u, thread.stackSize);
        m_memory.write32(outputAddress + 24u, thread.cpu.gpr[28]);
        m_memory.write32(outputAddress + 28u, thread.initialPriority);
        m_memory.write32(outputAddress + 32u, thread.priority);
        m_memory.write32(outputAddress + 36u, thread.state == IopThreadState::Sleep ? 1u : thread.state == IopThreadState::Delay   ? 2u
                                                                                       : thread.state == IopThreadState::Semaphore ? 3u
                                                                                       : thread.state == IopThreadState::EventFlag ? 4u
                                                                                       : thread.state == IopThreadState::Mailbox ? 5u
                                                                                                                                   : 0u);
        m_memory.write32(outputAddress + 40u, static_cast<uint32_t>(thread.waitId));
        m_memory.write32(outputAddress + 44u, static_cast<uint32_t>(thread.wakeupCount));
        return true;
    }

    bool IopKernel::dispatchSemaphoreImport(uint16_t ordinal, IopCpuState &cpu)
    {
        const bool handled = dispatchSemaphoreImportImpl(ordinal, cpu);
        noteSyscallReadiedThreads();
        return handled;
    }

    bool IopKernel::dispatchSemaphoreImportImpl(uint16_t ordinal, IopCpuState &cpu)
    {
        invalidateIdleSchedule();
        const auto setV0 = [&](int32_t value)
        {
            cpu.gpr[2] = static_cast<uint32_t>(value);
        };

        switch (ordinal)
        {
        case 4:
        {
            const uint32_t descriptor = cpu.gpr[4];
            Semaphore semaphore;
            semaphore.id = static_cast<int>(m_nextSemaphoreId++);
            semaphore.attr = m_memory.read32(descriptor + 0u);
            semaphore.option = m_memory.read32(descriptor + 4u);
            semaphore.current = static_cast<int>(m_memory.read32(descriptor + 8u));
            semaphore.maximum = std::max(1, static_cast<int>(m_memory.read32(descriptor + 12u)));
            m_semaphores.emplace(semaphore.id, semaphore);
            setV0(semaphore.id);
            return true;
        }
        case 5:
            setV0(m_semaphores.erase(static_cast<int>(cpu.gpr[4])) != 0u ? 0 : -1);
            return true;
        case 6:
        case 7:
        {
            const int id = static_cast<int>(cpu.gpr[4]);
            const auto it = m_semaphores.find(id);
            if (it == m_semaphores.end())
            {
                setV0(-1);
                return true;
            }
            if (it->second.current < it->second.maximum)
                ++it->second.current;
            wakeOneSemaphore(id);
            setV0(0);
            return true;
        }
        case 8:
        case 9:
        {
            const int id = static_cast<int>(cpu.gpr[4]);
            const auto it = m_semaphores.find(id);
            if (it == m_semaphores.end())
            {
                setV0(-1);
                return true;
            }
            if (it->second.current > 0)
            {
                --it->second.current;
                setV0(0);
            }
            else if (ordinal == 9)
                setV0(-419);
            else if (m_currentThread != nullptr)
            {
                m_currentThread->state = IopThreadState::Semaphore;
                m_currentThread->waitId = id;
                cpu.yielded = true;
                setV0(0);
            }
            else
            {
                // No current thread (an RPC server or callback run outside a
                // thread) cannot block; the caller proceeds as if it held the
                // semaphore. god-of-war-recomp found this locks sound drivers
                // out, so make every occurrence visible.
                static uint64_t occurrences = 0;
                if (++occurrences <= 16u || (occurrences & (occurrences - 1u)) == 0u)
                    std::cerr << "[IOP WaitSema] outside a thread on empty semaphore id=" << id
                              << " ra=0x" << std::hex << cpu.gpr[31] << std::dec
                              << " occurrence=" << occurrences << '\n';
                setV0(0);
            }
            return true;
        }
        case 11:
        case 12:
        {
            const int id = static_cast<int>(cpu.gpr[4]);
            const auto it = m_semaphores.find(id);
            if (it == m_semaphores.end())
            {
                setV0(-1);
                return true;
            }
            const uint32_t outputAddress = cpu.gpr[5];
            if (outputAddress != 0u)
            {
                m_memory.write32(outputAddress + 0u, it->second.attr);
                m_memory.write32(outputAddress + 4u, it->second.option);
                m_memory.write32(outputAddress + 8u, 0u);
                m_memory.write32(outputAddress + 12u, static_cast<uint32_t>(it->second.maximum));
                m_memory.write32(outputAddress + 16u, static_cast<uint32_t>(it->second.current));
                uint32_t waiters = 0u;
                for (const auto &[threadId, thread] : m_threads)
                {
                    if (thread.state == IopThreadState::Semaphore && thread.waitId == id)
                        ++waiters;
                }
                m_memory.write32(outputAddress + 20u, waiters);
            }
            setV0(0);
            return true;
        }
        default:
            return false;
        }
    }

    void IopKernel::wakeOneSemaphore(int id)
    {
        IopThread *best = nullptr;
        for (auto &[threadId, thread] : m_threads)
        {
            if (thread.state != IopThreadState::Semaphore || thread.waitId != id)
                continue;
            if (best == nullptr || thread.priority < best->priority)
                best = &thread;
        }

        const auto semaphore = m_semaphores.find(id);
        if (best != nullptr && semaphore != m_semaphores.end() && semaphore->second.current > 0)
        {
            --semaphore->second.current;
            makeReady(*best);
            best->waitId = 0;
        }
    }

    bool IopKernel::eventSatisfied(const EventFlag &event, uint32_t bits, uint32_t mode)
    {
        if (bits == 0u)
            return false;
        return (mode & 1u) != 0u ? (event.bits & bits) != 0u : (event.bits & bits) == bits;
    }

    void IopKernel::wakeEventWaiters(EventFlag &event)
    {
        for (auto &[threadId, thread] : m_threads)
        {
            if (thread.state != IopThreadState::EventFlag || thread.waitId != event.id)
                continue;
            if (!eventSatisfied(event, thread.waitBits, thread.waitMode))
                continue;

            if (thread.waitResultAddress != 0u)
                m_memory.write32(thread.waitResultAddress, event.bits);
            thread.cpu.gpr[2] = 0u;
            if ((thread.waitMode & 0x10u) != 0u)
                event.bits = 0u;
            makeReady(thread);
            thread.waitId = 0;
            thread.waitBits = 0;
            thread.waitMode = 0;
            thread.waitResultAddress = 0;
            if (event.bits == 0u)
                break;
        }
    }

    int IopKernel::createInternalEventFlag(uint32_t attr, uint32_t option, uint32_t bits)
    {
        invalidateIdleSchedule();
        EventFlag event;
        event.id = static_cast<int>(m_nextEventFlagId++);
        event.attr = attr;
        event.option = option;
        event.bits = bits;
        const int id = event.id;
        m_eventFlags.emplace(id, event);
        return id;
    }

    bool IopKernel::setInternalEventFlag(int id, uint32_t bits)
    {
        invalidateIdleSchedule();
        const auto event = m_eventFlags.find(id);
        if (event == m_eventFlags.end())
            return false;
        event->second.bits |= bits;
        wakeEventWaiters(event->second);
        return true;
    }

    bool IopKernel::dispatchEventImport(uint16_t ordinal, IopCpuState &cpu)
    {
        const bool handled = dispatchEventImportImpl(ordinal, cpu);
        noteSyscallReadiedThreads();
        return handled;
    }

    bool IopKernel::dispatchEventImportImpl(uint16_t ordinal, IopCpuState &cpu)
    {
        invalidateIdleSchedule();
        const auto setV0 = [&](int32_t value)
        {
            cpu.gpr[2] = static_cast<uint32_t>(value);
        };

        switch (ordinal)
        {
        case 4:
        {
            const uint32_t descriptor = cpu.gpr[4];
            setV0(createInternalEventFlag(m_memory.read32(descriptor + 0u),
                                          m_memory.read32(descriptor + 4u),
                                          m_memory.read32(descriptor + 8u)));
            return true;
        }
        case 5:
        {
            const int id = static_cast<int>(cpu.gpr[4]);
            if (m_eventFlags.erase(id) == 0u)
            {
                setV0(-1);
                return true;
            }
            for (auto &[threadId, thread] : m_threads)
            {
                if (thread.state == IopThreadState::EventFlag && thread.waitId == id)
                {
                    makeReady(thread);
                    thread.waitId = 0;
                    thread.cpu.gpr[2] = static_cast<uint32_t>(-1);
                }
            }
            setV0(0);
            return true;
        }
        case 6:
        case 7:
        {
            if (!setInternalEventFlag(static_cast<int>(cpu.gpr[4]), cpu.gpr[5]))
            {
                setV0(-1);
                return true;
            }
            setV0(0);
            return true;
        }
        case 8:
        case 9:
        {
            const auto event = m_eventFlags.find(static_cast<int>(cpu.gpr[4]));
            if (event == m_eventFlags.end())
            {
                setV0(-1);
                return true;
            }
            // IOP ClearEventFlag applies a mask: callers pass ~bitsToClear.
            event->second.bits &= cpu.gpr[5];
            setV0(0);
            return true;
        }
        case 10: // WaitEventFlag
        case 11: // PollEventFlag
        {
            const auto event = m_eventFlags.find(static_cast<int>(cpu.gpr[4]));
            if (event == m_eventFlags.end())
            {
                setV0(-1);
                return true;
            }
            const uint32_t bits = cpu.gpr[5];
            const uint32_t mode = cpu.gpr[6];
            if (eventSatisfied(event->second, bits, mode))
            {
                if (cpu.gpr[7] != 0u)
                    m_memory.write32(cpu.gpr[7], event->second.bits);
                if ((mode & 0x10u) != 0u)
                    event->second.bits = 0u;
                setV0(0);
            }
            else if (ordinal == 11)
                setV0(-418);
            else if (m_currentThread != nullptr)
            {
                m_currentThread->state = IopThreadState::EventFlag;
                m_currentThread->waitId = event->second.id;
                m_currentThread->waitBits = bits;
                m_currentThread->waitMode = mode;
                m_currentThread->waitResultAddress = cpu.gpr[7];
                setV0(0);
                cpu.yielded = true;
            }
            else
                setV0(-418);
            return true;
        }
        case 13:
        case 14:
        {
            const auto event = m_eventFlags.find(static_cast<int>(cpu.gpr[4]));
            if (event == m_eventFlags.end())
            {
                setV0(-1);
                return true;
            }
            if (cpu.gpr[5] != 0u)
            {
                uint32_t waiters = 0u;
                for (const auto &[threadId, thread] : m_threads)
                {
                    if (thread.state == IopThreadState::EventFlag && thread.waitId == event->second.id)
                        ++waiters;
                }
                m_memory.write32(cpu.gpr[5] + 0u, event->second.attr);
                m_memory.write32(cpu.gpr[5] + 4u, event->second.option);
                m_memory.write32(cpu.gpr[5] + 8u, event->second.bits);
                m_memory.write32(cpu.gpr[5] + 12u, event->second.bits);
                m_memory.write32(cpu.gpr[5] + 16u, waiters);
            }
            setV0(0);
            return true;
        }
        default:
            return false;
        }
    }

    std::string IopKernel::describeThreads() const
    {
        std::ostringstream out;
        out << "[IOP threads]";
        for (const auto &[id, thread] : m_threads)
            out << " {id=" << id << " state=" << static_cast<unsigned>(thread.state)
                << " priority=" << thread.priority << " pc=0x" << std::hex << thread.cpu.pc
                << " ra=0x" << thread.cpu.gpr[31] << " sp=0x" << thread.cpu.gpr[29]
                << " a0=0x" << thread.cpu.gpr[4] << " a1=0x" << thread.cpu.gpr[5]
                << " v0=0x" << thread.cpu.gpr[2] << " v1=0x" << thread.cpu.gpr[3]
                << " cause=0x" << thread.cpu.cop0[13] << " epc=0x" << thread.cpu.cop0[14]
                << std::dec << " wait=" << thread.waitId << '}';
        return out.str();
    }

    void IopKernel::updateMailboxLinks(const Mailbox &mailbox)
    {
        for (size_t i = 0; i < mailbox.messages.size(); ++i)
            m_memory.write32(mailbox.messages[i], mailbox.messages[(i + 1u) % mailbox.messages.size()]);
    }

    bool IopKernel::dispatchMailboxImport(uint16_t ordinal, IopCpuState &cpu)
    {
        const bool handled = dispatchMailboxImportImpl(ordinal, cpu);
        noteSyscallReadiedThreads();
        return handled;
    }

    bool IopKernel::dispatchMailboxImportImpl(uint16_t ordinal, IopCpuState &cpu)
    {
        invalidateIdleSchedule();
        if (std::getenv("PS2X_CAPTURE_DIR") && m_mailboxTraceCount++ < 64u)
            std::cerr << "[IOP mailbox] ordinal=" << ordinal << " thread="
                      << (m_currentThread ? m_currentThread->id : 0) << " a0=0x"
                      << std::hex << cpu.gpr[4] << " a1=0x" << cpu.gpr[5] << std::dec << '\n';
        const auto result = [&](int32_t value) { cpu.gpr[2] = static_cast<uint32_t>(value); };
        if (ordinal == 4u)
        {
            if (std::getenv("PS2X_CAPTURE_DIR"))
                std::cerr << "[IOP mailbox create] attr=0x" << std::hex << m_memory.read32(cpu.gpr[4])
                          << " option=0x" << m_memory.read32(cpu.gpr[4] + 4u) << std::dec << '\n';
            if (!cpu.gpr[4] || !m_memory.ownsRamRange(cpu.gpr[4], 8u)) { result(-201); return true; }
            if (m_memory.read32(cpu.gpr[4]) & ~5u) { result(-401); return true; }
            const int id = static_cast<int>(m_nextMailboxId++);
            m_mailboxes.emplace(id, Mailbox{m_memory.read32(cpu.gpr[4]), m_memory.read32(cpu.gpr[4] + 4u), {}});
            result(id);
            return true;
        }
        if (ordinal != 5u && ordinal != 6u && ordinal != 7u && ordinal != 8u &&
            ordinal != 9u && ordinal != 11u && ordinal != 12u)
            return false;
        const int id = static_cast<int>(cpu.gpr[(ordinal == 8u || ordinal == 9u) ? 5 : 4]);
        const auto found = m_mailboxes.find(id);
        if (found == m_mailboxes.end()) { result(-410); return true; }
        Mailbox &mailbox = found->second;
        if (ordinal == 5u)
        {
            for (auto &[threadId, thread] : m_threads)
                if (thread.state == IopThreadState::Mailbox && thread.waitId == id)
                {
                    makeReady(thread);
                    thread.cpu.gpr[2] = static_cast<uint32_t>(-425);
                }
            m_mailboxes.erase(found);
        }
        else if (ordinal == 6u || ordinal == 7u)
        {
            const uint32_t message = cpu.gpr[5];
            if (message == 0u || !m_memory.ownsRamRange(message, 8u)) { result(-201); return true; }
            IopThread *waiter = nullptr;
            for (auto &[threadId, thread] : m_threads)
                if (thread.state == IopThreadState::Mailbox && thread.waitId == id &&
                    (!waiter || ((mailbox.attr & 1u) && thread.priority < waiter->priority) ||
                     ((! (mailbox.attr & 1u) || thread.priority == waiter->priority) &&
                      thread.waitSequence < waiter->waitSequence)))
                    waiter = &thread;
            if (waiter)
            {
                m_memory.write32(waiter->waitResultAddress, message);
                waiter->cpu.gpr[2] = 0u;
                makeReady(*waiter);
            }
            else
            {
                if (std::find(mailbox.messages.begin(), mailbox.messages.end(), message) != mailbox.messages.end())
                { result(-400); return true; }
                auto position = mailbox.messages.end();
                if (mailbox.attr & 4u)
                    position = std::find_if(mailbox.messages.begin(), mailbox.messages.end(), [&](uint32_t queued)
                    { return m_memory.read8(message + 4u) < m_memory.read8(queued + 4u); });
                mailbox.messages.insert(position, message);
                updateMailboxLinks(mailbox);
            }
        }
        else if (ordinal == 8u || ordinal == 9u)
        {
            const uint32_t output = cpu.gpr[4];
            if (!output || !m_memory.ownsRamRange(output, 4u)) { result(-201); return true; }
            if (!mailbox.messages.empty())
            {
                m_memory.write32(output, mailbox.messages.front());
                mailbox.messages.pop_front();
                updateMailboxLinks(mailbox);
            }
            else if (ordinal == 9u || !m_currentThread)
            { result(ordinal == 9u ? -424 : -417); return true; }
            else
            {
                m_currentThread->state = IopThreadState::Mailbox;
                m_currentThread->waitId = id;
                m_currentThread->waitResultAddress = output;
                m_currentThread->waitSequence = ++m_waitSequence;
                cpu.yielded = true;
            }
        }
        else
        {
            const uint32_t output = cpu.gpr[5];
            if (!output || !m_memory.ownsRamRange(output, 28u)) { result(-201); return true; }
            uint32_t waiters = 0;
            for (const auto &[threadId, thread] : m_threads)
                if (thread.state == IopThreadState::Mailbox && thread.waitId == id) ++waiters;
            const uint32_t status[] = {mailbox.attr, mailbox.option, waiters,
                static_cast<uint32_t>(mailbox.messages.size()), mailbox.messages.empty() ? 0u : mailbox.messages.front(), 0u, 0u};
            m_memory.writeRam(output, status, sizeof(status));
        }
        result(0);
        return true;
    }

    void IopKernel::parkRpcCurrent(IopCpuState &cpu)
    {
        if (m_currentThread) m_rpcWaiters.insert(m_currentThread->id);
        sleepCurrent(cpu);
    }

    bool IopKernel::canStartRpcCall(int threadId) const
    {
        const auto it = m_threads.find(threadId);
        return it != m_threads.end() && m_rpcWaiters.contains(threadId) &&
            !m_rpcFrames.contains(threadId) && it->second.state == IopThreadState::Sleep &&
            m_currentThread != &it->second;
    }

    bool IopKernel::hasRpcCall(uint64_t token) const
    {
        for (const auto &[id, frame] : m_rpcFrames) if (frame.token == token) return true;
        return false;
    }

    bool IopKernel::startRpcCall(int threadId, uint64_t token, uint32_t function,
        uint32_t number, uint32_t buffer, uint32_t bytes, uint32_t gp, uint32_t returnSentinel)
    {
        invalidateIdleSchedule();
        if (!token || !function || (function & 3u) || !canStartRpcCall(threadId)) return false;
        auto &thread = m_threads.at(threadId);
        const uint32_t sp = IopMemory::physicalAddress(thread.cpu.gpr[29]);
        if (!thread.stackBase || sp < thread.stackBase ||
            sp - thread.stackBase < 256u || sp > thread.stackBase + thread.stackSize) return false;
        m_rpcFrames.emplace(threadId, RpcFrame{token, thread.cpu, thread.interruptControl});
        thread.cpu.pc = function;
        thread.cpu.gpr[4] = number; thread.cpu.gpr[5] = buffer;
        thread.cpu.gpr[6] = bytes; thread.cpu.gpr[7] = 0u;
        thread.cpu.gpr[28] = gp;
        thread.cpu.gpr[29] -= 64u; // Preserve the suspended RpcLoop frame.
        thread.cpu.gpr[31] = returnSentinel;
        thread.cpu.branchPending = false; thread.cpu.pendingLoad = false;
        thread.cpu.yielded = false; thread.cpu.stopped = false; thread.cpu.exception = false;
        makeReady(thread);
        return true;
    }

    std::optional<IopKernel::RpcCompletion> IopKernel::finishRpcCall(IopThread &thread, uint32_t returnSentinel)
    {
        const auto it = m_rpcFrames.find(thread.id);
        if (it == m_rpcFrames.end() ||
            (thread.cpu.pc != returnSentinel && !thread.cpu.stopped && !thread.cpu.exception)) return std::nullopt;
        invalidateIdleSchedule();
        const RpcCompletion result{it->second.token, thread.cpu.gpr[2], thread.cpu.pc != returnSentinel};
        thread.cpu = it->second.cpu;
        thread.interruptControl = it->second.interruptControl;
        m_memory.setInterruptControl(thread.interruptControl);
        thread.state = IopThreadState::Sleep;
        thread.waitId = 0;
        m_rpcFrames.erase(it);
        return result;
    }

    void IopKernel::cancelRpcCall(uint64_t token)
    {
        invalidateIdleSchedule();
        for (auto it = m_rpcFrames.begin(); it != m_rpcFrames.end(); ++it)
        {
            if (it->second.token != token) continue;
            const auto thread = m_threads.find(it->first);
            if (thread != m_threads.end() && thread->second.state != IopThreadState::Dead &&
                m_currentThread != &thread->second)
            {
                thread->second.cpu = it->second.cpu;
                thread->second.interruptControl = it->second.interruptControl;
                thread->second.state = IopThreadState::Sleep;
                thread->second.waitId = 0;
            }
            m_rpcFrames.erase(it);
            return;
        }
    }

    void IopKernel::sleepCurrent(IopCpuState &cpu)
    {
        invalidateIdleSchedule();
        if (m_currentThread == nullptr)
            return;
        m_currentThread->state = IopThreadState::Sleep;
        cpu.yielded = true;
    }

    void IopKernel::delayCurrentUntil(uint64_t wakeCycle, IopCpuState &cpu)
    {
        invalidateIdleSchedule();
        if (m_currentThread == nullptr)
            return;
        m_currentThread->wakeCycle = wakeCycle;
        m_currentThread->state = IopThreadState::Delay;
        cpu.yielded = true;
    }

    void IopKernel::noteSyscallReadiedThreads() noexcept
    {
        if (m_currentThread == nullptr)
            return;
        for (const auto &[id, thread] : m_threads)
        {
            if (thread.state == IopThreadState::Ready && thread.priority < m_currentThread->priority)
            {
                m_syscallReadiedHigher = true;
                return;
            }
        }
    }

    void IopKernel::makeReady(IopThread &thread, bool front) noexcept
    {
        invalidateIdleSchedule();
        thread.state = IopThreadState::Ready;
        thread.readyOrder = front ? --m_readyFront : ++m_readyBack;
    }

    IopThread *IopKernel::beginNextReady(uint64_t currentCycle)
    {
        // A thread that suspended interrupts (CpuSuspendIntr) runs on until it
        // blocks, resumes interrupts, or readies a higher-priority thread
        // itself. Ending a host slice is not a dispatch point: the CRI ADX
        // driver guards its SJ chunk lists this way, and switching here lost
        // audio chunks between its DTX and mixer threads.
        if (m_sliceThreadId != 0 && !m_syscallReadiedHigher)
        {
            const auto outgoing = m_threads.find(m_sliceThreadId);
            if (outgoing != m_threads.end() && outgoing->second.state == IopThreadState::Ready &&
                !outgoing->second.cpu.yielded &&
                outgoing->second.interruptControl == 0u)
            {
                IopThread &thread = outgoing->second;
                m_currentThread = &thread;
                m_memory.setInterruptControl(0u);
                thread.state = IopThreadState::Running;
                thread.cpu.stopped = false;
                thread.cpu.yielded = false;
                return &thread;
            }
        }
        m_syscallReadiedHigher = false;
        if (m_idleScheduleValid && currentCycle < m_idleWakeCycle)
        {
            m_memory.setInterruptControl(1u);
            return nullptr;
        }
        IopThread *next = nullptr;
        uint64_t nextWake = UINT64_MAX;
        for (auto &[id, thread] : m_threads)
        {
            if (thread.state == IopThreadState::Delay && thread.wakeCycle <= currentCycle)
                makeReady(thread);
            if (thread.state == IopThreadState::Delay)
                nextWake = std::min(nextWake, thread.wakeCycle);
            // Select in the same pass that matures delays. Every thread is
            // still examined; priority and ID ordering remain unchanged.
            if (thread.state != IopThreadState::Ready)
                continue;
            if (next == nullptr || thread.priority < next->priority ||
                (thread.priority == next->priority && thread.readyOrder < next->readyOrder))
                next = &thread;
        }
        if (next == nullptr)
        {
            m_idleWakeCycle = nextWake;
            m_idleScheduleValid = true;
            // The real kernel's idle context has interrupts enabled, even
            // when the outgoing thread blocked with its own control disabled.
            m_memory.setInterruptControl(1u);
            return nullptr;
        }

        invalidateIdleSchedule();
        m_currentThread = next;
        m_memory.setInterruptControl(next->interruptControl);
        next->state = IopThreadState::Running;
        next->cpu.stopped = false;
        next->cpu.yielded = false;
        return next;
    }

    uint64_t IopKernel::nextWakeCycle(uint64_t fallback) const
    {
        if (m_idleScheduleValid)
            return std::min(fallback, m_idleWakeCycle);
        uint64_t nextWake = fallback;
        for (const auto &[id, thread] : m_threads)
        {
            if (thread.state == IopThreadState::Delay)
                nextWake = std::min(nextWake, thread.wakeCycle);
        }
        return nextWake;
    }

    void IopKernel::endTimeslice(IopThread &thread, uint32_t returnSentinel)
    {
        invalidateIdleSchedule();
        // I_CTRL is part of the saved IOP thread context. A host execution
        // slice must not leak one guest thread's critical section to another.
        thread.interruptControl = m_memory.interruptControl();
        m_sliceThreadId = thread.id;
        if (thread.cpu.pc == returnSentinel || thread.cpu.stopped)
            thread.state = IopThreadState::Dormant;
        else if (thread.state == IopThreadState::Running)
            // PS2SDK puts a preempted thread at the front, and a voluntarily
            // rotated thread at the back. Host slice expiry is not rotation.
            makeReady(thread, !thread.cpu.yielded);
        m_currentThread = nullptr;
        cleanupDeadThreads();
    }

    void IopKernel::cleanupDeadThreads()
    {
        invalidateIdleSchedule();
        for (auto thread = m_threads.begin(); thread != m_threads.end();)
        {
            if (thread->second.state != IopThreadState::Dead)
            {
                ++thread;
                continue;
            }
            if (thread->second.stackBase != 0u)
                (void)m_memory.freeAllocation(thread->second.stackBase);
            m_rpcFrames.erase(thread->first);
            m_rpcWaiters.erase(thread->first);
            thread = m_threads.erase(thread);
        }
    }

    void IopKernel::terminateThreadsInRange(uint32_t base, uint32_t size)
    {
        invalidateIdleSchedule();
        for (auto &[id, thread] : m_threads)
        {
            const uint32_t pc = IopMemory::physicalAddress(thread.cpu.pc);
            if (pc >= base && pc < base + size)
                thread.state = IopThreadState::Dead;
        }
    }
}
