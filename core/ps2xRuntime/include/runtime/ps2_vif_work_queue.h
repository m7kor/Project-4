// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "runtime/ps2_vu1_execution.h"

#include <condition_variable>
#include <cstdint>
#include <deque>
#include <exception>
#include <functional>
#include <mutex>
#include <thread>
#include <vector>

// Transport for the future VIF1/VU1 worker. Not enabled by PS2X_MTVU yet:
// memory, CPU-context and interrupt barriers must be connected first.
class PS2VifWorkQueue
{
public:
    enum class Kind { Vif1, Gif, ArbiterDrain };
    using Control = PS2Vu1RunControl;
    struct Item
    {
        Kind kind;
        uint32_t pathId;
        bool drainImmediately, directHl;
        Control control;
        uint64_t sequence;
        std::vector<uint8_t> bytes;
    };
    using Consumer = std::function<void(const Item &)>;

    explicit PS2VifWorkQueue(Consumer consumer, size_t maxBytes = 1024 * 1024, size_t maxItems = 1024);
    ~PS2VifWorkQueue();
    PS2VifWorkQueue(const PS2VifWorkQueue &) = delete;
    PS2VifWorkQueue &operator=(const PS2VifWorkQueue &) = delete;

    uint64_t enqueue(Kind kind, const uint8_t *data, size_t bytes, Control control,
                     uint32_t pathId = 0, bool drainImmediately = true, bool directHl = false);
    // Wait for all work published before this call; worker recursion is a no-op.
    void drain();
    // Any external teardown thread closes publication, finishes work and joins.
    // Consumer errors are reported by drain/enqueue; teardown still joins.
    void stop();
    bool onWorker() const;

private:
    void run();
    void requireOwner() const;
    Consumer m_consumer;
    const size_t m_maxBytes, m_maxItems;
    const std::thread::id m_owner;
    std::thread m_thread;
    mutable std::mutex m_mutex;
    std::mutex m_stopMutex;
    std::condition_variable m_work, m_progress;
    std::deque<Item> m_items;
    size_t m_pendingBytes = 0, m_pendingItems = 0;
    uint64_t m_published = 0, m_completed = 0;
    bool m_closing = false;
    std::exception_ptr m_failure;
};
