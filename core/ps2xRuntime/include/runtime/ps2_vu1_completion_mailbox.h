// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "runtime/ps2_vu1_execution.h"
#include <chrono>
#include <condition_variable>
#include <deque>
#include <exception>
#include <limits>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <thread>

// Bounded return path for the future runtime VIF worker. It owns no CPU,
// scheduler or VU memory. Reserve on EE before queuing work; when full, retire
// ready results and wait for progress, never wait while holding a queue lock.
// Invalidation protects metadata only: the caller must synchronize actual
// VU/VIF/GIF work before resetting hardware or destroying its storage.
class PS2Vu1CompletionMailbox
{
public:
    struct Ticket { uint64_t sequence, generation; };
    struct Result {
        PS2Vu1Completion completion{};
        uint64_t executedCycles = 0, eeVsync = 0;
    };
    explicit PS2Vu1CompletionMailbox(size_t capacity = 1024)
        : m_capacity(capacity), m_owner(std::this_thread::get_id())
    {
        if (!capacity) throw std::invalid_argument("VU completion capacity must be positive");
    }
    std::optional<Ticket> reserve()
    {
        requireOwner();
        std::lock_guard lock(m_mutex);
        checkFailure();
        if (m_entries.size() == m_capacity) return std::nullopt;
        if (m_sequence == std::numeric_limits<uint64_t>::max())
            throw std::overflow_error("VU completion sequence exhausted");
        Ticket ticket{m_sequence + 1, m_generation};
        m_entries.push_back({ticket, {}, false});
        ++m_sequence;
        return ticket;
    }
    // Roll back only the last reservation if submitting its work failed.
    bool cancel(Ticket ticket)
    {
        requireOwner();
        std::lock_guard lock(m_mutex);
        if (m_entries.empty() || !same(m_entries.back().ticket, ticket) || m_entries.back().ready) return false;
        m_entries.pop_back();
        return true;
    }
    bool publish(Ticket ticket, Result result)
    {
        if (std::this_thread::get_id() == m_owner)
            throw std::logic_error("VU result publication belongs to the worker");
        std::lock_guard lock(m_mutex);
        if (ticket.generation != m_generation) return false;
        checkFailure();
        for (auto &entry : m_entries) {
            if (!same(entry.ticket, ticket)) continue;
            if (entry.ready) throw std::logic_error("duplicate VU completion");
            entry.result = result;
            entry.ready = true;
            m_progress.notify_one();
            return true;
        }
        return false; // Cancelled or already retired: never emit another IRQ.
    }
    // Run retirement on EE, in reservation order, outside the mailbox lock.
    // Keep the front slot until retirement succeeds. A failed callback poisons
    // the generation instead of silently losing an event and continuing.
    template <typename Retire> size_t retireReady(Retire &&retire)
    {
        requireOwner();
        m_retiring = true;
        size_t count = 0;
        try {
            for (;;) {
                std::optional<Entry> next;
                {
                    std::lock_guard lock(m_mutex);
                    checkFailure();
                    if (m_entries.empty() || !m_entries.front().ready) break;
                    next = m_entries.front();
                }
                retire(next->ticket, next->result);
                {
                    std::lock_guard lock(m_mutex);
                    m_entries.pop_front();
                }
                ++count;
            }
        } catch (...) {
            std::lock_guard lock(m_mutex);
            m_failure = std::current_exception();
            m_retiring = false;
            m_progress.notify_all();
            throw;
        }
        m_retiring = false;
        return count;
    }
    bool waitForProgress(std::chrono::milliseconds timeout)
    {
        requireOwner();
        std::unique_lock lock(m_mutex);
        const bool ready = m_progress.wait_for(lock, timeout, [&] {
            return m_failure || (!m_entries.empty() && m_entries.front().ready);
        });
        checkFailure();
        return ready;
    }
    bool fail(Ticket ticket, std::exception_ptr error)
    {
        if (!error) throw std::invalid_argument("VU failure needs an exception");
        std::lock_guard lock(m_mutex);
        if (ticket.generation != m_generation) return false;
        bool found = false;
        for (const auto &entry : m_entries) found |= same(entry.ticket, ticket);
        if (!found) return false;
        if (!m_failure) m_failure = error;
        m_progress.notify_all();
        return true;
    }
    uint64_t invalidate()
    {
        requireOwner();
        std::lock_guard lock(m_mutex);
        if (m_generation == std::numeric_limits<uint64_t>::max())
            throw std::overflow_error("VU completion generation exhausted");
        ++m_generation;
        m_entries.clear();
        m_failure = {};
        return m_generation;
    }
private:
    struct Entry { Ticket ticket; Result result; bool ready; };
    static bool same(Ticket a, Ticket b) { return a.sequence == b.sequence && a.generation == b.generation; }
    void requireOwner() const
    {
        if (std::this_thread::get_id() != m_owner || m_retiring)
            throw std::logic_error("VU reservations and retirement belong to non-reentrant EE execution");
    }
    void checkFailure() const { if (m_failure) std::rethrow_exception(m_failure); }
    const size_t m_capacity;
    const std::thread::id m_owner;
    uint64_t m_sequence = 0, m_generation = 1;
    bool m_retiring = false;
    std::mutex m_mutex;
    std::condition_variable m_progress;
    std::deque<Entry> m_entries;
    std::exception_ptr m_failure;
};
