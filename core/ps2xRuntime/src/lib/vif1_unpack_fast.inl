// V4-32/V4-16 dispatch once per UNPACK, following the donor's format-loop idea.
// Only complete, unmasked MODE0 source cycles enter; ROW/COL/fill stay generic.
namespace
{
    thread_local int g_vifUnpackOverride = -1;
    thread_local uint64_t g_vifUnpackFastCalls = 0;

    bool vifUnpackFastEnabled()
    {
        static const bool enabled = [] {
            const char *value = std::getenv("PS2X_VIF1_FAST_UNPACK");
            return value && *value == '1';
        }();
        return g_vifUnpackOverride < 0 ? enabled : g_vifUnpackOverride != 0;
    }

    bool vifUnpackSourceIsSeparate(const uint8_t *source, const uint8_t *destination, uint32_t bytes)
    {
        const uintptr_t src = reinterpret_cast<uintptr_t>(source);
        const uintptr_t dst = reinterpret_cast<uintptr_t>(destination);
        return src >= dst ? src - dst >= PS2_VU1_DATA_SIZE : dst - src >= bytes;
    }

    template <bool ZeroExtend>
    void unpackV4Short(uint8_t *destination, const uint8_t *source)
    {
        uint16_t packed[4];
        uint32_t expanded[4];
        std::memcpy(packed, source, sizeof(packed));
        for (uint32_t lane = 0; lane < 4; ++lane)
            expanded[lane] = ZeroExtend ? static_cast<uint32_t>(packed[lane])
                                       : static_cast<uint32_t>(static_cast<int32_t>(static_cast<int16_t>(packed[lane])));
        std::memcpy(destination, expanded, sizeof(expanded));
    }

    template <typename Store>
    void unpackV4Vectors(uint8_t *destination, const uint8_t *source, uint32_t count,
                         uint32_t address, uint32_t cl, uint32_t wl, uint32_t stride, Store store)
    {
        if (cl == wl)
        {
            for (uint32_t index = 0; index < count; ++index)
                store(destination + ((address + index) & 0x3FFu) * 16u, source + index * stride);
            return;
        }
        for (uint32_t index = 0; index < count; ++index)
        {
            const uint32_t vector = (address + (index / wl) * cl + index % wl) & 0x3FFu;
            store(destination + vector * 16u, source + index * stride);
        }
    }

    void unpackV4Fast(uint8_t *destination, const uint8_t *source, uint32_t count,
                      uint32_t address, uint32_t cl, uint32_t wl, uint32_t vl, bool zeroExtend)
    {
        ++g_vifUnpackFastCalls;
        // Optional one-time diagnostic: prove a live game reached this path.
        // Exclusive creation avoids overwriting an unrelated report.
        static const bool witnessAttempted = [] {
            const char *path = std::getenv("PS2X_VIF1_FAST_WITNESS");
            if (path && *path)
                if (std::FILE *file = std::fopen(path, "wbx"))
                {
                    std::fputs("{\"entered\":true,\"scope\":\"V4 MODE0 unmasked format path\"}\n", file);
                    std::fclose(file);
                }
            return true;
        }();
        (void)witnessAttempted;
        if (vl == 0u && cl == wl)
        {
            // NUM is at most 256, so at most one 16-KiB wrap is possible.
            // The caller proves that the source cannot alias VU data memory.
            const uint32_t first = std::min(count, 1024u - address);
            std::memcpy(destination + address * 16u, source, first * 16u);
            if (first < count)
                std::memcpy(destination, source + first * 16u, (count - first) * 16u);
            return;
        }
        if (vl == 0u)
            unpackV4Vectors(destination, source, count, address, cl, wl, 16u,
                            [](uint8_t *dst, const uint8_t *src) { std::memcpy(dst, src, 16u); });
        else if (zeroExtend)
            unpackV4Vectors(destination, source, count, address, cl, wl, 8u, unpackV4Short<true>);
        else
            unpackV4Vectors(destination, source, count, address, cl, wl, 8u, unpackV4Short<false>);
    }
}

// Private diagnostic controls are thread-local so a test cannot change another
// memory executor's selection. -1 restores the process setting.
void ps2xVif1SetUnpackFastOverride(int selection) { g_vifUnpackOverride = selection; }
uint64_t ps2xVif1UnpackFastCalls() { return g_vifUnpackFastCalls; }
