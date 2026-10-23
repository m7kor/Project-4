#pragma once
#include "ps2x/iop/iop_host.h"
#include <filesystem>
#include <istream>
#include <vector>

// Optional deterministic input fixture for native integration runs. Events
// are game VSync ticks, not wall time or OS keyboard/window injection.
class PS2PadReplay
{
public:
    bool load(std::istream &stream);
    bool load(const std::filesystem::path &path);
    ps2x::iop::IopHost::PadInput sample(uint64_t tick) const;
    uint64_t lastTick() const { return m_events.empty() ? 0 : m_events.back().end; }
private:
    struct Event { uint64_t begin, end; ps2x::iop::IopHost::PadInput input; };
    std::vector<Event> m_events;
};
