#include "ps2_pad_replay.h"
#include <array>
#include <charconv>
#include <fstream>
#include <string>
#include <string_view>

bool PS2PadReplay::load(const std::filesystem::path &path)
{
    std::error_code ec;
    const auto size = std::filesystem::file_size(path,ec);
    if (ec || size > 128 * 1024) return false;
    std::ifstream stream(path); return stream && load(stream);
}
bool PS2PadReplay::load(std::istream &stream)
{
    std::string line;
    if (!std::getline(stream,line)) return false;
    if (!line.empty() && line.back()=='\r') line.pop_back();
    if (line != "begin,end,buttons,lx,ly,rx,ry") return false;
    std::vector<Event> events;
    size_t bytes = line.size();
    while (std::getline(stream,line))
    {
        bytes += line.size()+1;
        if (bytes > 128*1024 || events.size() >= 1024) return false;
        if (!line.empty() && line.back()=='\r') line.pop_back();
        if (line.empty()) continue;
        std::array<uint64_t,7> fields{};
        std::string_view remaining=line;
        for (size_t i=0;i<fields.size();++i)
        {
            const auto comma=remaining.find(',');
            if ((i<6 && comma==std::string_view::npos) || (i==6 && comma!=std::string_view::npos)) return false;
            const auto field=remaining.substr(0,comma);
            const auto parsed=std::from_chars(field.data(),field.data()+field.size(),fields[i]);
            if (field.empty() || parsed.ec!=std::errc{} || parsed.ptr!=field.data()+field.size()) return false;
            if (i<6) remaining.remove_prefix(comma+1);
        }
        if (fields[0]>=fields[1] || fields[2]>65535 || (!events.empty() && fields[0]<events.back().end)) return false;
        for (size_t i=3;i<7;++i) if (fields[i]>255) return false;
        ps2x::iop::IopHost::PadInput input;
        input.buttons=static_cast<uint16_t>(fields[2]);
        input.lx=static_cast<uint8_t>(fields[3]);input.ly=static_cast<uint8_t>(fields[4]);
        input.rx=static_cast<uint8_t>(fields[5]);input.ry=static_cast<uint8_t>(fields[6]);
        events.push_back({fields[0],fields[1],input});
    }
    if (stream.bad() || events.empty()) return false;
    m_events=std::move(events); return true;
}
ps2x::iop::IopHost::PadInput PS2PadReplay::sample(uint64_t tick) const
{
    for (const auto &event:m_events)
    {
        if (tick<event.begin) break;
        if (tick<event.end) return event.input;
    }
    return {}; // released buttons and centered sticks outside fixture intervals
}
