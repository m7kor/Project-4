#include "runtime/gs/ps2_gif_arbiter.h"
#include <array>
#include <cstring>

GifArbiter::GifArbiter(ProcessPacketFn processFn)
    : m_processFn(std::move(processFn))
{
}

bool GifArbiter::isImagePacket(const uint8_t *data, uint32_t sizeBytes)
{
    if (!data || sizeBytes < 16u)
        return false;

    uint64_t tagLo = 0;
    std::memcpy(&tagLo, data, sizeof(tagLo));
    const uint8_t flg = static_cast<uint8_t>((tagLo >> 58) & 0x3u);
    return flg == 2u;
}

void GifArbiter::submit(GifPathId pathId, const uint8_t *data, uint32_t sizeBytes, bool path2DirectHl)
{
    if (!data || sizeBytes < 16 || (!m_processFn && !m_processPathFn) ||
        pathPriority(pathId) < 1u || pathPriority(pathId) > 3u)
        return;

    GifArbiterPacket pkt;
    pkt.pathId = pathId;
    pkt.path2DirectHl = (pathId == GifPathId::Path2) && path2DirectHl;
    pkt.path3Image = (pathId == GifPathId::Path3) && isImagePacket(data, sizeBytes);
    pkt.data.resize(sizeBytes);
    std::memcpy(pkt.data.data(), data, sizeBytes);
    m_queue.push_back(std::move(pkt));
}

void GifArbiter::drain()
{
    if (!m_processFn && !m_processPathFn)
        return;

    // Arbitration is a decision between the heads of three FIFOs, not a
    // sortable relation between arbitrary packets. The former comparator was
    // non-transitive (DIRECT < IMAGE < DIRECTHL) and could reverse PATH2.
    // Keep byte order within every source path, including IMAGE fragments.
    while (!m_queue.empty())
    {
        const size_t packetCount = m_queue.size();
        std::array<size_t, 3> heads{packetCount, packetCount, packetCount};
        for (size_t path = 0; path < heads.size(); ++path)
            for (size_t i = 0; i < packetCount; ++i)
                if (pathPriority(m_queue[i].pathId) == path + 1u)
                {
                    heads[path] = i;
                    break;
                }

        for (;;)
        {
            size_t selected = 0;
            if (heads[0] == packetCount)
            {
                if (heads[1] != packetCount)
                {
                    selected = 1;
                    // Preserve DIRECTHL's existing IMAGE barrier, applied only
                    // to queue heads so it cannot overtake an earlier DIRECT.
                    if (m_queue[heads[1]].path2DirectHl && heads[2] != packetCount &&
                        m_queue[heads[2]].path3Image)
                        selected = 2;
                }
                else if (heads[2] != packetCount)
                    selected = 2;
                else
                    break;
            }
            const size_t index = heads[selected];
            size_t next = index + 1;
            while (next < packetCount && pathPriority(m_queue[next].pathId) != selected + 1u)
                ++next;
            heads[selected] = next;
            auto &pkt = m_queue[index];
            if (!pkt.data.empty())
            {
                if (m_processPathFn)
                    m_processPathFn(pkt.pathId, pkt.data.data(), static_cast<uint32_t>(pkt.data.size()));
                else
                    m_processFn(pkt.data.data(), static_cast<uint32_t>(pkt.data.size()));
            }
        }
        // A callback may enqueue work; consume that new batch after this one.
        // Erasing the consumed prefix retains capacity for the usual one-packet
        // hot path, with no temporary packet buffers or sorting allocation.
        m_queue.erase(m_queue.begin(), m_queue.begin() + packetCount);
    }
}

uint8_t GifArbiter::pathPriority(GifPathId id)
{
    return static_cast<uint8_t>(id);
}
