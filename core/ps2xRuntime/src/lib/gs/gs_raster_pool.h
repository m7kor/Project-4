#pragma once

// Fork-join worker pool for the CPU GS rasterizer.
//
// run(count, job) calls job(index, worker) for every index in [0, count) and
// returns only when all of them have finished, so a primitive split into
// scanline bands completes before the next primitive starts and GS draw order
// is unchanged. The calling thread takes bands too (worker 0); pool threads
// are workers 1..threads. Bands are claimed from an atomic counter, so uneven
// bands balance themselves.
//
// PS2X_GS_THREADS sets the number of pool threads (0 disables the pool and
// every primitive is drawn on the calling thread). The default is the host's
// hardware concurrency minus two, capped at 8.

#include <algorithm>
#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <cstdlib>
#include <functional>
#include <mutex>
#include <thread>
#include <vector>

class GSRasterPool
{
public:
    using Job = std::function<void(uint32_t index, uint32_t worker)>;

    GSRasterPool()
    {
        uint32_t threads = defaultThreads();
        if (const char *value = std::getenv("PS2X_GS_THREADS"))
            threads = static_cast<uint32_t>(std::min<unsigned long>(std::strtoul(value, nullptr, 10), 31ul));
        for (uint32_t i = 0; i < threads; ++i)
            m_threads.emplace_back([this, i]() { workerLoop(i + 1u); });
    }

    ~GSRasterPool()
    {
        {
            std::lock_guard<std::mutex> lock(m_mutex);
            m_stop = true;
        }
        m_wake.notify_all();
        for (std::thread &thread : m_threads)
            thread.join();
    }

    GSRasterPool(const GSRasterPool &) = delete;
    GSRasterPool &operator=(const GSRasterPool &) = delete;

    // Worker slots including the calling thread.
    uint32_t workers() const { return static_cast<uint32_t>(m_threads.size()) + 1u; }

    void run(uint32_t count, const Job &job)
    {
        if (count == 0u)
            return;
        if (m_threads.empty() || count == 1u)
        {
            for (uint32_t i = 0; i < count; ++i)
                job(i, 0u);
            return;
        }
        uint64_t generation;
        {
            std::lock_guard<std::mutex> lock(m_mutex);
            m_job = &job;
            m_count = count;
            m_remaining.store(count, std::memory_order_relaxed);
            generation = ++m_generation;
            m_ticket.store(generation << 32, std::memory_order_release);
        }
        m_wake.notify_all();
        drain(0u, generation, &job, count);
        // The caller finished its share; wait for bands still in flight.
        std::unique_lock<std::mutex> lock(m_mutex);
        m_done.wait(lock, [this]() { return m_remaining.load(std::memory_order_acquire) == 0u; });
        m_job = nullptr;
    }

private:
    static uint32_t defaultThreads()
    {
        const unsigned hardware = std::thread::hardware_concurrency();
        if (hardware <= 2u)
            return 0u;
        return std::min(8u, hardware - 2u);
    }

    // Claims bands of one generation only: a worker that wakes late cannot
    // take a band of the next primitive with the previous job.
    void drain(uint32_t worker, uint64_t generation, const Job *job, uint32_t count)
    {
        for (;;)
        {
            uint64_t ticket = m_ticket.load(std::memory_order_acquire);
            if ((ticket >> 32) != generation)
                return;
            const uint32_t index = static_cast<uint32_t>(ticket);
            if (index >= count)
                return;
            if (!m_ticket.compare_exchange_weak(ticket, ticket + 1u, std::memory_order_acq_rel))
                continue;
            (*job)(index, worker);
            if (m_remaining.fetch_sub(1u, std::memory_order_acq_rel) == 1u)
            {
                std::lock_guard<std::mutex> lock(m_mutex);
                m_done.notify_all();
            }
        }
    }

    void workerLoop(uint32_t worker)
    {
        uint64_t seen = 0u;
        for (;;)
        {
            const Job *job;
            uint32_t count;
            {
                std::unique_lock<std::mutex> lock(m_mutex);
                m_wake.wait(lock, [&]() { return m_stop || m_generation != seen; });
                if (m_stop)
                    return;
                seen = m_generation;
                job = m_job;
                count = m_count;
            }
            if (job)
                drain(worker, seen, job, count);
        }
    }

    std::vector<std::thread> m_threads;
    std::mutex m_mutex;
    std::condition_variable m_wake;
    std::condition_variable m_done;
    const Job *m_job = nullptr;
    uint32_t m_count = 0u;
    std::atomic<uint64_t> m_ticket{0u};
    std::atomic<uint32_t> m_remaining{0u};
    uint64_t m_generation = 0u;
    bool m_stop = false;
};
