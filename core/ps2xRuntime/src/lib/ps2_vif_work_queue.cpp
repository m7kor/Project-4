// SPDX-License-Identifier: GPL-3.0-or-later
#include "runtime/ps2_vif_work_queue.h"
#include <stdexcept>
#include <utility>

namespace { thread_local const PS2VifWorkQueue *s_activeVifQueue = nullptr; }

PS2VifWorkQueue::PS2VifWorkQueue(Consumer consumer, size_t maxBytes, size_t maxItems)
    : m_consumer(std::move(consumer)), m_maxBytes(maxBytes), m_maxItems(maxItems),
      m_owner(std::this_thread::get_id())
{
    if (!m_consumer || !maxBytes || !maxItems)
        throw std::invalid_argument("VIF work queue needs a consumer and positive limits");
    m_thread = std::thread([this] { run(); });
}

PS2VifWorkQueue::~PS2VifWorkQueue() { stop(); }

void PS2VifWorkQueue::requireOwner() const
{
    if (std::this_thread::get_id() != m_owner)
        throw std::logic_error("VIF publication must run on its EE owner");
}

bool PS2VifWorkQueue::onWorker() const { return s_activeVifQueue == this; }

uint64_t PS2VifWorkQueue::enqueue(Kind kind, const uint8_t *data, size_t bytes, Control control,
                                 uint32_t pathId, bool drainImmediately, bool directHl)
{
    requireOwner();
    if (bytes > m_maxBytes || (bytes && !data))
        throw std::invalid_argument("invalid or oversized VIF/GIF payload");
    if (kind == Kind::Gif && (pathId < 1 || pathId > 3))
        throw std::invalid_argument("GIF path must be 1, 2 or 3");
    Item item{kind, pathId, drainImmediately, directHl, control, 0, {}};
    if (bytes)
        item.bytes.assign(data, data + bytes); // Own data before producer can reuse DMA RAM.
    std::unique_lock lock(m_mutex);
    m_progress.wait(lock, [&] {
        return m_failure || m_closing ||
               (m_pendingItems < m_maxItems && bytes <= m_maxBytes - m_pendingBytes);
    });
    if (m_failure) std::rethrow_exception(m_failure);
    if (m_closing) throw std::logic_error("VIF queue is closed");
    item.sequence = m_published + 1;
    m_items.push_back(std::move(item)); // Allocation failure must not advance sequence/accounting.
    ++m_published;
    ++m_pendingItems;
    m_pendingBytes += bytes;
    m_work.notify_one();
    return m_published;
}

void PS2VifWorkQueue::drain()
{
    if (onWorker()) return;
    std::unique_lock lock(m_mutex);
    const uint64_t target = m_published;
    m_progress.wait(lock, [&] { return m_failure || m_completed >= target; });
    if (m_failure) std::rethrow_exception(m_failure);
}

void PS2VifWorkQueue::stop()
{
    if (onWorker()) throw std::logic_error("VIF worker cannot join itself");
    std::lock_guard stopping(m_stopMutex);
    {
        std::lock_guard lock(m_mutex);
        m_closing = true;
    }
    m_work.notify_all();
    m_progress.notify_all();
    if (m_thread.joinable()) m_thread.join();
}

void PS2VifWorkQueue::run()
{
    s_activeVifQueue = this;
    for (;;)
    {
        Item item;
        {
            std::unique_lock lock(m_mutex);
            m_work.wait(lock, [&] { return m_closing || !m_items.empty(); });
            if (m_items.empty()) break;
            item = std::move(m_items.front());
            m_items.pop_front();
        }
        try { m_consumer(item); }
        catch (...)
        {
            std::lock_guard lock(m_mutex);
            m_failure = std::current_exception();
            m_items.clear();
            m_pendingBytes = m_pendingItems = 0;
            m_progress.notify_all();
            break; // Failed hardware work cannot be followed by apparently successful work.
        }
        {
            std::lock_guard lock(m_mutex);
            m_completed = item.sequence;
            m_pendingBytes -= item.bytes.size();
            --m_pendingItems;
        }
        m_progress.notify_all();
    }
    s_activeVifQueue = nullptr;
}
