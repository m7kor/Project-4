#include "MiniTest.h"
#include "ps2_stubs.h"
#include "ps2_syscalls.h"
#include "Stubs/Pad.h"
#include "../../ps2xRuntime/src/lib/ps2_pad_replay.h"
#include "../../ps2xRuntime/src/lib/ps2_pad_live.inl"
#include <chrono>
#include "../../ps2xIOP/src/emulator/core/iop_pad.h"
#include <array>
#include <sstream>
#include "runtime/ps2_pad.h"
#include <limits>

#include <vector>
#include <cstdint>
#include <string>


namespace
{
    constexpr uint32_t kPadDataAddr = 0x1000;

    constexpr uint16_t kPadBtnSelect = 1u << 0;
    constexpr uint16_t kPadBtnL3 = 1u << 1;
    constexpr uint16_t kPadBtnR3 = 1u << 2;
    constexpr uint16_t kPadBtnStart = 1u << 3;
    constexpr uint16_t kPadBtnUp = 1u << 4;
    constexpr uint16_t kPadBtnRight = 1u << 5;
    constexpr uint16_t kPadBtnDown = 1u << 6;
    constexpr uint16_t kPadBtnLeft = 1u << 7;
    constexpr uint16_t kPadBtnL2 = 1u << 8;
    constexpr uint16_t kPadBtnR2 = 1u << 9;
    constexpr uint16_t kPadBtnL1 = 1u << 10;
    constexpr uint16_t kPadBtnR1 = 1u << 11;
    constexpr uint16_t kPadBtnTriangle = 1u << 12;
    constexpr uint16_t kPadBtnCircle = 1u << 13;
    constexpr uint16_t kPadBtnCross = 1u << 14;
    constexpr uint16_t kPadBtnSquare = 1u << 15;

    void setRegU32(R5900Context &ctx, int reg, uint32_t value)
    {
        ctx.r[reg] = _mm_set_epi64x(0, static_cast<int64_t>(value));
    }

    void openPadPort(R5900Context &ctx, std::vector<uint8_t> &rdram, uint32_t port = 0, uint32_t slot = 0)
    {
        setRegU32(ctx, 4, port);
        setRegU32(ctx, 5, slot);
        setRegU32(ctx, 6, kPadDataAddr + 0x200u);
        ps2_stubs::scePadPortOpen(rdram.data(), &ctx, nullptr);
    }

    void closePadPort(R5900Context &ctx, std::vector<uint8_t> &rdram, uint32_t port = 0, uint32_t slot = 0)
    {
        setRegU32(ctx, 4, port);
        setRegU32(ctx, 5, slot);
        ps2_stubs::scePadPortClose(rdram.data(), &ctx, nullptr);
    }

    void runPadRead(R5900Context &ctx, std::vector<uint8_t> &rdram)
    {
        setRegU32(ctx, 4, 0u);
        setRegU32(ctx, 5, 0u);
        setRegU32(ctx, 6, kPadDataAddr); // a2
        ps2_stubs::scePadRead(rdram.data(), &ctx, nullptr);
    }

    uint16_t readButtons(const std::vector<uint8_t> &rdram)
    {
        const uint8_t *data = rdram.data() + kPadDataAddr;
        return static_cast<uint16_t>(data[2] | (data[3] << 8));
    }
}

void register_pad_input_tests()
{
    MiniTest::Case("PadInput", [](TestCase &tc)
                   {
        tc.Run("Live pad bounded command and wire interval boundaries", [](TestCase &t)
        {
            ps2x::diagnostic::LivePadReplay live({}, 100);
            t.IsTrue(live.update("sequence,begin,end,buttons,lx,ly,rx,ry\n1,110,120,49151,255,0,12,34\n", 100, 1000), "accept one future command");
            t.Equals(live.inputAt(109, 1001).buttons, uint16_t(65535), "neutral before begin");
            const auto input = live.inputAt(110, 1001);
            t.Equals(input.lx, uint8_t(255), "inclusive begin");
            t.Equals(input.ry, uint8_t(34), "camera axis retained");
            t.Equals(live.inputAt(120, 1001).lx, uint8_t(128), "exclusive end releases stick");
            t.Equals(live.inputAt(120, 1001).buttons, uint16_t(65535), "exclusive end releases button");
            ps2x::iop::detail::IopPad device;
            std::array<uint8_t, 9> configure{1,0x43,0,1,0,0,0,0,0};
            device.exchange(configure, {});
            configure = {1,0x44,0,1,3,0,0,0,0}; device.exchange(configure, {});
            configure = {1,0x43,0,0,0,0,0,0,0}; device.exchange(configure, {});
            const std::array<uint8_t, 9> poll{1,0x42,0,0,0,0,0,0,0};
            const auto reply = device.exchange(poll, input);
            t.Equals(reply.size(), size_t(9), "analog response");
            if (reply.size() != 9) return;
            const std::array<uint8_t, 6> expected{255,191,12,34,255,0};
            for (size_t i = 0; i < expected.size(); ++i)
                t.Equals(reply[i + 3], expected[i], "live buttons/RX/RY/LX/LY retain serial order");
        });
        tc.Run("Live pad rejects invalid commands and cancels held input", [](TestCase &t)
        {
            const std::string header = "sequence,begin,end,buttons,lx,ly,rx,ry\n";
            const std::vector<std::string> invalid{
                "1,112,120,65535,0,0,0,0\n", // duplicate sequence
                "0,112,120,65535,0,0,0,0\n", "2,100,120,65535,0,0,0,0\n",
                "2,111,120,65535,0,0,0,0\n", "2,231,240,65535,0,0,0,0\n",
                "2,112,112,65535,0,0,0,0\n", "2,112,293,65535,0,0,0,0\n",
                "2,112,120,65536,0,0,0,0\n", "2,112,120,65535,256,0,0,0\n",
                "2,112,120,65535,0,0,0,-1\n", "2,112,120,65535,0,0,0,0,0\n",
                "2,112,120,65535,0,0,0,0\nextra\n",
                "18446744073709551616,112,120,65535,0,0,0,0\n"};
            for (const auto &row : invalid)
            {
                ps2x::diagnostic::LivePadReplay live({}, 100);
                t.IsTrue(live.update(header + "1,102,125,65535,255,128,128,128\n", 100, 0), "initial active input");
                t.Equals(live.inputAt(110, 1).lx, uint8_t(255), "held before invalid update");
                t.Equals(live.update(header + row, 110, 2), false, "reject bad field or interval");
                t.Equals(live.inputAt(115, 3).lx, uint8_t(128), "rejected update cancels old stick");
                t.Equals(live.sequence(), uint64_t(1), "rejection retains sequence high water");
            }
            ps2x::diagnostic::LivePadReplay live({}, 100);
            t.Equals(live.update(std::string(1025, 'x'), 100, 0), false, "bounded bytes");
            t.Equals(live.update(header + "1,18446744073709551614,18446744073709551615,65535,0,0,0,0\n", 100, 0), false, "huge begin cannot overflow lead checks");
        });
        tc.Run("Live pad host lease, replacement and instance isolation", [](TestCase &t)
        {
            const std::string header = "sequence,begin,end,buttons,lx,ly,rx,ry\n";
            ps2x::diagnostic::LivePadReplay live({}, 100), other({}, 100);
            t.IsTrue(live.update(header + "1,110,290,65535,255,128,128,128\n", 100, 1000), "maximum duration accepted");
            t.Equals(live.inputAt(112, 30999).lx, uint8_t(255), "lease valid before timeout");
            t.Equals(live.inputAt(112, 31000).lx, uint8_t(128), "host timeout releases even if EE stalls");
            t.Equals(live.inputAt(112, 999).lx, uint8_t(128), "backward clock is neutral");
            t.Equals(other.inputAt(112, 1001).lx, uint8_t(128), "independent instance remains neutral");
            t.IsTrue(live.update(header + "2,116,125,65535,128,0,128,128\n", 112, 1002), "newer command replaces held command");
            t.Equals(live.inputAt(113, 1003).lx, uint8_t(128), "replacement releases while awaiting next begin");
            t.Equals(live.inputAt(116, 1003).ly, uint8_t(0), "replacement applies at its begin");
            t.Equals(live.update(header + "3,117,125,65535,128,0,128,128\n", 99, 1004), false, "cannot accept before activation");
        });
        tc.Run("Live pad filesystem polling sees content updates and removal", [](TestCase &t)
        {
            const auto serial = std::chrono::steady_clock::now().time_since_epoch().count();
            const auto path = std::filesystem::temp_directory_path() / ("ps2-live-pad-" + std::to_string(serial) + ".csv");
            struct Cleanup { std::filesystem::path path; ~Cleanup() { std::error_code ec; std::filesystem::remove(path, ec); } } cleanup{path};
            const std::string header = "sequence,begin,end,buttons,lx,ly,rx,ry\n";
            auto write = [&](const std::string &row) { std::ofstream file(path, std::ios::binary | std::ios::trunc); file << header << row; return bool(file); };
            ps2x::diagnostic::LivePadReplay live(path, 100);
            ps2x::diagnostic::LivePadReplay::Input input;
            t.Equals(live.poll(99, 999, input), false, "startup replay keeps ownership");
            t.IsTrue(write("1,110,150,65535,255,128,128,128\n"), "write command");
            t.IsTrue(live.poll(100, 1000, input), "diagnostic activates");
            live.poll(110, 1001, input); t.Equals(input.lx, uint8_t(255), "accepted command sampled without repeated file IO");
            const auto stamp = std::filesystem::last_write_time(path);
            t.IsTrue(write("2,120,150,65535,128,255,128,128\n"), "same-size replacement");
            std::filesystem::last_write_time(path, stamp);
            live.poll(112, 1050, input); t.Equals(input.lx, uint8_t(128), "mtime-independent update cancels previous interval");
            live.poll(120, 1051, input); t.Equals(input.ly, uint8_t(255), "updated command sampled");
            live.poll(120, 31050, input); t.Equals(input.ly, uint8_t(128), "unchanged file does not renew host lease");
            std::filesystem::remove(path);
            live.poll(121, 31100, input); t.Equals(input.ly, uint8_t(128), "file removal releases input");
            t.IsTrue(write("2,130,150,65535,255,128,128,128\n"), "old sequence reappears");
            live.poll(122, 31150, input); live.poll(130, 31151, input);
            t.Equals(input.lx, uint8_t(128), "removed command cannot replay with same sequence");
            t.IsTrue(write("3,140,150,65535,255,128,128,128\n"), "fresh sequence");
            live.poll(132, 31200, input); live.poll(140, 31201, input);
            t.Equals(input.lx, uint8_t(255), "fresh command accepted");
            live.poll(139, 31202, input); t.Equals(input.lx, uint8_t(128), "EE rewind cancels active command");
        });
        tc.Run("Automatic controller ownership and hotplug release", [](TestCase &t)
        {
            PSPadBackend pad; PSHostPadFrame frame; uint8_t data[32]{};
            frame.gamepads[2].connected = true;
            frame.gamepads[2].buttons = 0xbfffu;
            pad.publishHostFrame(frame); pad.readState(0, 0, data, sizeof(data));
            t.Equals(pad.activeGamepad(), 2, "controller need not occupy host index zero");
            t.Equals(data[3], uint8_t(0xbf), "south face button retains PS2 Cross wire bit");
            frame.gamepads[0].connected = true; pad.publishHostFrame(frame);
            t.Equals(pad.activeGamepad(), 2, "new controller does not steal active ownership");
            frame.gamepads[2].connected = false; pad.publishHostFrame(frame);
            t.Equals(pad.activeGamepad(), 0, "disconnection selects remaining controller");
            pad.readState(0, 0, data, sizeof(data));
            t.Equals(data[3], uint8_t(255), "old controller held button released on switch");
            frame.gamepads[0].connected = false; frame.keyboardButtons = 0xfff7u;
            pad.publishHostFrame(frame); pad.readState(0, 0, data, sizeof(data));
            t.Equals(pad.activeGamepad(), -1, "keyboard fallback after final disconnect");
            t.Equals(data[2], uint8_t(0xf7), "keyboard Start remains available");
            frame.focused = false; pad.publishHostFrame(frame); pad.readState(0, 0, data, sizeof(data));
            t.Equals(data[2], uint8_t(255), "focus loss releases held buttons");
            t.Equals(pad.readState(1, 0, data, sizeof(data)), false, "single controller is not duplicated on second PS2 port");
            frame.focused = true; frame.gamepads[3].connected = true; pad.publishHostFrame(frame);
            t.Equals(pad.activeGamepad(), 3, "reconnection automatically binds a new host index");
        });
        tc.Run("Modern controller sticks and analog trigger fidelity", [](TestCase &t)
        {
            PSPadBackend pad; PSHostPadFrame frame; uint8_t data[32]{};
            auto &host = frame.gamepads[1]; host.connected = true;
            host.axes = {0.03f, -0.02f, -1.f, 1.f, -1.f, -1.f};
            pad.publishHostFrame(frame); pad.readState(0, 0, data, sizeof(data));
            t.Equals(data[6], uint8_t(128), "small left stick drift is centered");
            t.Equals(data[7], uint8_t(128), "radial deadzone centers both axes");
            t.Equals(data[4], uint8_t(0), "right stick full left reaches zero");
            t.Equals(data[5], uint8_t(255), "right stick full down reaches 255 without inversion");
            t.Equals(data[18], uint8_t(0), "released left trigger pressure is zero");
            host.axes = {1.f, -1.f, 0.f, 0.f, 0.f, 1.f};
            pad.publishHostFrame(frame); pad.readState(0, 0, data, sizeof(data));
            t.Equals(data[6], uint8_t(255), "left stick full right reaches 255");
            t.Equals(data[7], uint8_t(0), "left stick full up reaches zero");
            t.IsTrue(data[18] > 0 && data[18] < 255, "half left trigger retains proportional pressure");
            t.Equals(data[19], uint8_t(255), "full right trigger reaches full pressure");
            t.Equals(uint16_t(data[2] | (data[3] << 8)) & uint16_t(0x300), uint16_t(0), "both trigger digital PS2 bits active");
            host.axes = {std::numeric_limits<float>::quiet_NaN(), 0.f, 0.f, 0.f, -1.f, -1.f};
            pad.publishHostFrame(frame); pad.readState(0, 0, data, sizeof(data));
            t.Equals(data[6], uint8_t(128), "invalid axis cannot produce a stuck stick");
            t.Equals(data[18], uint8_t(0), "trigger release clears previous pressure");
        });
        tc.Run("Native replay boundaries and invalid fixtures", [](TestCase &t)
        {
            PS2PadReplay replay;
            std::istringstream valid("begin,end,buttons,lx,ly,rx,ry\r\n10,20,49151,0,255,12,34\r\n20,30,65519,128,128,128,128\r\n");
            t.Equals(replay.load(valid), true, "valid adjacent CRLF events");
            t.Equals(replay.sample(9).buttons, uint16_t(65535), "released before event");
            t.Equals(replay.sample(10).buttons, uint16_t(49151), "inclusive begin");
            t.Equals(replay.sample(19).ly, uint8_t(255), "axis range retained");
            t.Equals(replay.sample(19).rx, uint8_t(12), "axis ordering retained");
            t.Equals(replay.sample(20).buttons, uint16_t(65519), "adjacent event boundary");
            t.Equals(replay.sample(30).buttons, uint16_t(65535), "exclusive end releases buttons");
            t.Equals(replay.sample(30).lx, uint8_t(128), "neutral sticks after event");
            const std::vector<std::string> invalid = {
                "", "bad header\n", "begin,end,buttons,lx,ly,rx,ry\n",
                "begin,end,buttons,lx,ly,rx,ry\n10,10,0,0,0,0,0\n",
                "begin,end,buttons,lx,ly,rx,ry\n-1,10,0,0,0,0,0\n",
                "begin,end,buttons,lx,ly,rx,ry\n0,10,65536,0,0,0,0\n",
                "begin,end,buttons,lx,ly,rx,ry\n0,10,0,256,0,0,0\n",
                "begin,end,buttons,lx,ly,rx,ry\n0,10,0,0,0,0\n",
                "begin,end,buttons,lx,ly,rx,ry\n0,10,0,0,0,0,0,0\n",
                "begin,end,buttons,lx,ly,rx,ry\n0,10,0,0,0,0,0x\n",
                "begin,end,buttons,lx,ly,rx,ry\n0,18446744073709551616,0,0,0,0,0\n",
                "begin,end,buttons,lx,ly,rx,ry\n0,10,0,0,0,0,0\n9,20,0,0,0,0,0\n"
            };
            for (const auto &fixture : invalid) {
                std::istringstream stream(fixture);
                t.Equals(replay.load(stream), false, "reject malformed or overlapping fixture");
                t.Equals(replay.sample(10).buttons, uint16_t(49151), "failed load preserves valid fixture");
            }
            std::ostringstream excessive;
            excessive << "begin,end,buttons,lx,ly,rx,ry\n";
            for (unsigned i=0;i<1025;++i) excessive << i << ',' << i+1 << ",65535,128,128,128,128\n";
            std::istringstream tooMany(excessive.str());
            t.Equals(replay.load(tooMany), false, "bounded event count");
        });
        tc.Run("Replay axes reach native analog poll bytes at interval boundaries", [](TestCase &t)
        {
            PS2PadReplay replay;
            std::istringstream fixture("begin,end,buttons,lx,ly,rx,ry\n"
                "10,20,65535,255,128,128,128\n"
                "20,30,65535,128,0,128,128\n"
                "30,40,49151,128,128,0,255\n");
            t.IsTrue(replay.load(fixture), "valid movement and camera fixture");
            ps2x::iop::detail::IopPad device;
            std::array<uint8_t, 9> configure{1, 0x43, 0, 1};
            device.exchange(configure, replay.sample(0));
            configure = {1, 0x44, 0, 1, 3};
            device.exchange(configure, replay.sample(0));
            configure = {1, 0x43, 0, 0};
            device.exchange(configure, replay.sample(0));
            const std::array<uint8_t, 9> poll{1, 0x42};
            const std::array<uint64_t, 9> ticks{9, 10, 19, 20, 29, 30, 39, 40, 41};
            const std::array<std::array<uint8_t, 6>, 9> expected{{
                {255,255,128,128,128,128}, {255,255,128,128,255,128},
                {255,255,128,128,255,128}, {255,255,128,128,128,0},
                {255,255,128,128,128,0}, {255,191,0,255,128,128},
                {255,191,0,255,128,128}, {255,255,128,128,128,128},
                {255,255,128,128,128,128}}};
            for (size_t i = 0; i < ticks.size(); ++i)
            {
                const auto reply = device.exchange(poll, replay.sample(ticks[i]));
                t.Equals(reply.size(), size_t(9), "full analog poll length");
                if (reply.size() != 9) return;
                t.Equals(reply[0], uint8_t(255), "serial prefix");
                t.Equals(reply[1], uint8_t(0x73), "negotiated analog mode");
                t.Equals(reply[2], uint8_t(0x5a), "serial acknowledgement");
                for (size_t b = 0; b < 6; ++b)
                    t.Equals(reply[b + 3], expected[i][b], "buttons/RX/RY/LX/LY retain wire order");
            }
            const auto shortReply = device.exchange(std::span<const uint8_t>(poll.data(), 5), replay.sample(10));
            t.Equals(shortReply.size(), size_t(5), "short poll cannot report analog bytes");
        });
        tc.Run("scePadRead uses override state", [](TestCase &t)
               {
            std::vector<uint8_t> rdram(PS2_RAM_SIZE, 0);
            R5900Context ctx;

            ps2_stubs::scePadInit(rdram.data(), &ctx, nullptr);
            openPadPort(ctx, rdram);

            const uint16_t buttons = static_cast<uint16_t>(0xFFFFu & ~kPadBtnCross & ~kPadBtnStart);
            ps2_stubs::setPadOverrideState(buttons, 0x00, 0xFF, 0x10, 0xEE);

            runPadRead(ctx, rdram);

            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(1), "scePadRead should return 1");
            t.Equals(readButtons(rdram), buttons, "button bitmask should match override state");
            const uint8_t *data = rdram.data() + kPadDataAddr;
            t.Equals(data[4], static_cast<uint8_t>(0x10), "rx should match override");
            t.Equals(data[5], static_cast<uint8_t>(0xEE), "ry should match override");
            t.Equals(data[6], static_cast<uint8_t>(0x00), "lx should match override");
            t.Equals(data[7], static_cast<uint8_t>(0xFF), "ly should match override");

            ps2_stubs::clearPadOverrideState();
            closePadPort(ctx, rdram);
        });

        tc.Run("scePadRead button bits are active-low", [](TestCase &t)
               {
            std::vector<uint8_t> rdram(PS2_RAM_SIZE, 0);
            R5900Context ctx;

            ps2_stubs::scePadInit(rdram.data(), &ctx, nullptr);
            openPadPort(ctx, rdram);

            struct ButtonCase
            {
                uint16_t mask;
                const char *name;
            };

            const ButtonCase cases[] = {
                {kPadBtnSelect, "select"},
                {kPadBtnL3, "l3"},
                {kPadBtnR3, "r3"},
                {kPadBtnStart, "start"},
                {kPadBtnUp, "up"},
                {kPadBtnRight, "right"},
                {kPadBtnDown, "down"},
                {kPadBtnLeft, "left"},
                {kPadBtnL2, "l2"},
                {kPadBtnR2, "r2"},
                {kPadBtnL1, "l1"},
                {kPadBtnR1, "r1"},
                {kPadBtnTriangle, "triangle"},
                {kPadBtnCircle, "circle"},
                {kPadBtnCross, "cross"},
                {kPadBtnSquare, "square"}};

            for (const auto &entry : cases)
            {
                const uint16_t buttons = static_cast<uint16_t>(0xFFFFu & ~entry.mask);
                ps2_stubs::setPadOverrideState(buttons, 0x80, 0x80, 0x80, 0x80);
                runPadRead(ctx, rdram);

                t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(1), "scePadRead should succeed for opened ports");
                const uint16_t mask = readButtons(rdram);
                t.IsTrue((mask & entry.mask) == 0, std::string("button should be active-low: ").append(entry.name));
            }

            ps2_stubs::clearPadOverrideState();
            closePadPort(ctx, rdram);
        });

        tc.Run("scePadGetButtonMask returns all buttons", [](TestCase &t)
               {
            R5900Context ctx;
            ps2_stubs::scePadGetButtonMask(nullptr, &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(0xFFFF), "button mask should be 0xFFFF");
        });

        tc.Run("basic pad init/port/state functions return expected values", [](TestCase &t)
               {
            std::vector<uint8_t> rdram(PS2_RAM_SIZE, 0);
            R5900Context ctx;

            ps2_stubs::scePadInit(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(1), "scePadInit should succeed");

            ps2_stubs::scePadInit2(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(1), "scePadInit2 should succeed");

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            ps2_stubs::scePadGetState(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(0), "closed port should report DISCONNECTED");

            openPadPort(ctx, rdram);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(1), "scePadPortOpen should succeed");

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            ps2_stubs::scePadGetState(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(6), "scePadGetState should return STABLE");

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            ps2_stubs::scePadGetReqState(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(0), "scePadGetReqState should return completed");

            ps2_stubs::scePadGetPortMax(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(2), "scePadGetPortMax should be 2");

            setRegU32(ctx, 4, 0u);
            ps2_stubs::scePadGetSlotMax(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(1), "scePadGetSlotMax should be 1");

            ps2_stubs::scePadGetModVersion(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(0x0200), "scePadGetModVersion should be 0x0200");

            closePadPort(ctx, rdram);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(1), "scePadPortClose should succeed");

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            ps2_stubs::scePadGetState(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(0), "closed port should return DISCONNECTED after close");
        });

        tc.Run("pad command state reports EXECCMD once before returning STABLE", [](TestCase &t)
               {
            std::vector<uint8_t> rdram(PS2_RAM_SIZE, 0);
            R5900Context ctx;

            ps2_stubs::scePadInit(rdram.data(), &ctx, nullptr);
            openPadPort(ctx, rdram);

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            setRegU32(ctx, 6, 1u);
            setRegU32(ctx, 7, 3u);
            ps2_stubs::scePadSetMainMode(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(1), "scePadSetMainMode should succeed");

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            ps2_stubs::scePadGetState(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(5), "first state after mode command should be EXECCMD");

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            ps2_stubs::scePadGetState(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(6), "second state after mode command should return STABLE");

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            ps2_stubs::scePadEnterPressMode(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(1), "scePadEnterPressMode should succeed");

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            ps2_stubs::scePadGetState(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(5), "first state after press-mode command should be EXECCMD");

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            ps2_stubs::scePadGetState(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(6), "second state after press-mode command should return STABLE");

            closePadPort(ctx, rdram);
        });

        tc.Run("pad info and mode helpers return consistent values", [](TestCase &t)
               {
            std::vector<uint8_t> rdram(PS2_RAM_SIZE, 0);
            R5900Context ctx;

            ps2_stubs::scePadInit(rdram.data(), &ctx, nullptr);
            openPadPort(ctx, rdram);

            setRegU32(ctx, 6, static_cast<uint32_t>(-1));
            ps2_stubs::scePadInfoAct(rdram.data(), &ctx, nullptr);
            t.IsTrue(static_cast<uint32_t>(getRegU32(&ctx, 2)) >= 1u, "scePadInfoAct should report at least one actuator descriptor");

            ps2_stubs::scePadInfoComb(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(0), "scePadInfoComb should return 0");

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            setRegU32(ctx, 6, 1);
            setRegU32(ctx, 7, 0);
            ps2_stubs::scePadInfoMode(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(4), "scePadInfoMode CURID should return digital at open");

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            setRegU32(ctx, 6, 4);
            setRegU32(ctx, 7, static_cast<uint32_t>(-1));
            ps2_stubs::scePadInfoMode(rdram.data(), &ctx, nullptr);
            t.IsTrue(static_cast<uint32_t>(getRegU32(&ctx, 2)) >= 1u, "scePadInfoMode table count should be non-zero");

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            ps2_stubs::scePadInfoPressMode(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(1), "scePadInfoPressMode should report pressure support");

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            setRegU32(ctx, 6, 0u);
            setRegU32(ctx, 7, 3u);
            ps2_stubs::scePadSetMainMode(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(1), "scePadSetMainMode should accept digital mode");

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            setRegU32(ctx, 6, 1u);
            setRegU32(ctx, 7, 0u);
            ps2_stubs::scePadInfoMode(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(4), "CURID should switch to digital mode");

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            setRegU32(ctx, 6, 1u);
            setRegU32(ctx, 7, 3u);
            ps2_stubs::scePadSetMainMode(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(1), "scePadSetMainMode should accept analog mode");

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            setRegU32(ctx, 6, 4);
            setRegU32(ctx, 7, 0u);
            ps2_stubs::scePadInfoMode(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(7), "mode table entry should return DualShock in analog mode");

            closePadPort(ctx, rdram);
        });

        tc.Run("pads open in digital mode and switch to analog on scePadSetMainMode", [](TestCase &t)
               {
            std::vector<uint8_t> rdram(PS2_RAM_SIZE, 0);
            R5900Context ctx;

            ps2_stubs::scePadInit(rdram.data(), &ctx, nullptr);
            openPadPort(ctx, rdram);

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            ps2_stubs::scePadGetState(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(6), "freshly opened port should report STABLE");

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            setRegU32(ctx, 6, 1);
            setRegU32(ctx, 7, 0);
            ps2_stubs::scePadInfoMode(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(4), "scePadInfoMode CURID should return digital at open");

            runPadRead(ctx, rdram);
            const uint8_t *data = rdram.data() + kPadDataAddr;
            t.Equals(data[1], static_cast<uint8_t>(0x41), "mode byte should be 0x41 (digital) at open");

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            setRegU32(ctx, 6, 1);
            setRegU32(ctx, 7, 3);
            ps2_stubs::scePadSetMainMode(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(1), "scePadSetMainMode should succeed switching to analog");

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            setRegU32(ctx, 6, 1);
            setRegU32(ctx, 7, 0);
            ps2_stubs::scePadInfoMode(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(7), "scePadInfoMode CURID should return analog after SetMainMode");

            // scePadSetMainMode queues a one-shot EXECCMD transient state; pump scePadGetState
            // once so the port settles back to STABLE before reading, mirroring the existing
            // "pad command state reports EXECCMD once before returning STABLE" test.
            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            ps2_stubs::scePadGetState(rdram.data(), &ctx, nullptr);

            runPadRead(ctx, rdram);
            t.Equals(data[1], static_cast<uint8_t>(0x73), "mode byte should be 0x73 (analog) after SetMainMode");

            closePadPort(ctx, rdram);
        });

        tc.Run("pad setters return success", [](TestCase &t)
               {
            std::vector<uint8_t> rdram(PS2_RAM_SIZE, 0);
            R5900Context ctx;

            ps2_stubs::scePadInit(rdram.data(), &ctx, nullptr);
            openPadPort(ctx, rdram);

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            ps2_stubs::scePadSetActAlign(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(1), "scePadSetActAlign should succeed");

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            ps2_stubs::scePadSetActDirect(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(1), "scePadSetActDirect should succeed");

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            setRegU32(ctx, 6, 0xFFFFu);
            ps2_stubs::scePadSetButtonInfo(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(1), "scePadSetButtonInfo should succeed");

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            setRegU32(ctx, 6, 1u);
            setRegU32(ctx, 7, 3u);
            ps2_stubs::scePadSetMainMode(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(1), "scePadSetMainMode should succeed");

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            ps2_stubs::scePadSetReqState(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(1), "scePadSetReqState should succeed");

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            ps2_stubs::scePadSetVrefParam(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(1), "scePadSetVrefParam should succeed");

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            ps2_stubs::scePadSetWarningLevel(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(0), "scePadSetWarningLevel should return 0");

            ps2_stubs::scePadEnd(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(1), "scePadEnd should succeed");

            openPadPort(ctx, rdram);
            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            ps2_stubs::scePadEnterPressMode(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(1), "scePadEnterPressMode should succeed");

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            ps2_stubs::scePadExitPressMode(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(1), "scePadExitPressMode should succeed");

            closePadPort(ctx, rdram);
        });

        tc.Run("scePadRead fills pressure bytes and honors button info mask", [](TestCase &t)
               {
            std::vector<uint8_t> rdram(PS2_RAM_SIZE, 0);
            R5900Context ctx;

            ps2_stubs::scePadInit(rdram.data(), &ctx, nullptr);
            openPadPort(ctx, rdram);

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            setRegU32(ctx, 6, 0xFFFFu);
            ps2_stubs::scePadSetButtonInfo(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(1), "scePadSetButtonInfo should accept all buttons");

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            ps2_stubs::scePadEnterPressMode(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(1), "scePadEnterPressMode should enable pressure data");

            const uint16_t pressedButtons = static_cast<uint16_t>(0xFFFFu &
                                                                   ~kPadBtnLeft &
                                                                   ~kPadBtnUp &
                                                                   ~kPadBtnTriangle &
                                                                   ~kPadBtnCross &
                                                                   ~kPadBtnL1 &
                                                                   ~kPadBtnR2);
            ps2_stubs::setPadOverrideState(pressedButtons, 0x80, 0x80, 0x80, 0x80);
            runPadRead(ctx, rdram);

            const uint8_t *data = rdram.data() + kPadDataAddr;
            t.Equals(data[8], static_cast<uint8_t>(0x00), "right pressure should be clear when not pressed");
            t.Equals(data[9], static_cast<uint8_t>(0xFF), "left pressure should be populated when pressed");
            t.Equals(data[10], static_cast<uint8_t>(0xFF), "up pressure should be populated when pressed");
            t.Equals(data[11], static_cast<uint8_t>(0x00), "down pressure should be clear when not pressed");
            t.Equals(data[12], static_cast<uint8_t>(0xFF), "triangle pressure should be populated when pressed");
            t.Equals(data[13], static_cast<uint8_t>(0x00), "circle pressure should be clear when not pressed");
            t.Equals(data[14], static_cast<uint8_t>(0xFF), "cross pressure should be populated when pressed");
            t.Equals(data[15], static_cast<uint8_t>(0x00), "square pressure should be clear when not pressed");
            t.Equals(data[16], static_cast<uint8_t>(0xFF), "L1 pressure should be populated when pressed");
            t.Equals(data[17], static_cast<uint8_t>(0x00), "R1 pressure should be clear when not pressed");
            t.Equals(data[18], static_cast<uint8_t>(0x00), "L2 pressure should be clear when not pressed");
            t.Equals(data[19], static_cast<uint8_t>(0xFF), "R2 pressure should be populated when pressed");

            ps2_stubs::setPadOverrideState(uint16_t(0xffffu & ~kPadBtnR1), 128, 128, 128, 128);
            runPadRead(ctx, rdram);
            t.Equals(data[17], uint8_t(255), "R1 occupies the original DS2 pressure byte 17");
            t.Equals(data[18], uint8_t(0), "R1 must not be mistaken for L2");
            ps2_stubs::setPadOverrideState(uint16_t(0xffffu & ~kPadBtnL2), 128, 128, 128, 128);
            runPadRead(ctx, rdram);
            t.Equals(data[17], uint8_t(0), "L2 must not be mistaken for R1");
            t.Equals(data[18], uint8_t(255), "L2 occupies the original DS2 pressure byte 18");
            ps2_stubs::setPadOverrideState(pressedButtons, 128, 128, 128, 128);

            setRegU32(ctx, 4, 0u);
            setRegU32(ctx, 5, 0u);
            setRegU32(ctx, 6, static_cast<uint32_t>(kPadBtnL1 | kPadBtnR2));
            ps2_stubs::scePadSetButtonInfo(rdram.data(), &ctx, nullptr);
            t.Equals(static_cast<uint32_t>(getRegU32(&ctx, 2)), static_cast<uint32_t>(1), "scePadSetButtonInfo should narrow the enabled pressure mask");

            runPadRead(ctx, rdram);

            t.Equals(data[9], static_cast<uint8_t>(0x00), "masked-out direction pressure should clear");
            t.Equals(data[10], static_cast<uint8_t>(0x00), "masked-out direction pressure should clear");
            t.Equals(data[12], static_cast<uint8_t>(0x00), "masked-out face-button pressure should clear");
            t.Equals(data[14], static_cast<uint8_t>(0x00), "masked-out face-button pressure should clear");
            t.Equals(data[16], static_cast<uint8_t>(0xFF), "enabled L1 pressure should remain populated");
            t.Equals(data[19], static_cast<uint8_t>(0xFF), "enabled R2 pressure should remain populated");

            ps2_stubs::clearPadOverrideState();
            closePadPort(ctx, rdram);
        });

        tc.Run("pad string helpers map state codes", [](TestCase &t)
               {
            std::vector<uint8_t> rdram(PS2_RAM_SIZE, 0);
            R5900Context ctx;

            setRegU32(ctx, 4, 1);
            setRegU32(ctx, 5, kPadDataAddr);
            ps2_stubs::scePadStateIntToStr(rdram.data(), &ctx, nullptr);
            t.IsTrue(std::string(reinterpret_cast<const char *>(rdram.data() + kPadDataAddr)).find("FINDPAD") != std::string::npos,
                     "state 1 should map to FINDPAD");

            setRegU32(ctx, 4, 0);
            setRegU32(ctx, 5, kPadDataAddr + 64);
            ps2_stubs::scePadStateIntToStr(rdram.data(), &ctx, nullptr);
            t.IsTrue(std::string(reinterpret_cast<const char *>(rdram.data() + kPadDataAddr + 64)).find("DISCONNECTED") != std::string::npos,
                     "state 0 should map to DISCONNECTED");

            setRegU32(ctx, 4, 1);
            setRegU32(ctx, 5, kPadDataAddr + 128);
            ps2_stubs::scePadReqIntToStr(rdram.data(), &ctx, nullptr);
            t.IsTrue(std::string(reinterpret_cast<const char *>(rdram.data() + kPadDataAddr + 128)).find("BUSY") != std::string::npos,
                     "req state 1 should map to BUSY");
        });
        tc.Run("scePadGetFrameCount increments", [](TestCase &t)
               {
            R5900Context ctx;
            ps2_stubs::scePadGetFrameCount(nullptr, &ctx, nullptr);
            const uint32_t first = getRegU32(&ctx, 2);
            ps2_stubs::scePadGetFrameCount(nullptr, &ctx, nullptr);
            const uint32_t second = getRegU32(&ctx, 2);
            t.Equals(second, first + 1, "frame count should increment");
        });

        tc.Run("scePadStateIntToStr and scePadReqIntToStr write strings", [](TestCase &t)
               {
            std::vector<uint8_t> rdram(PS2_RAM_SIZE, 0);
            R5900Context ctx;

            setRegU32(ctx, 4, 6);
            setRegU32(ctx, 5, kPadDataAddr);
            ps2_stubs::scePadStateIntToStr(rdram.data(), &ctx, nullptr);
            const char *stateStr = reinterpret_cast<const char *>(rdram.data() + kPadDataAddr);
            t.IsTrue(std::string(stateStr).find("STABLE") != std::string::npos, "state string should include STABLE");

            setRegU32(ctx, 4, 0);
            setRegU32(ctx, 5, kPadDataAddr + 64);
            ps2_stubs::scePadReqIntToStr(rdram.data(), &ctx, nullptr);
            const char *reqStr = reinterpret_cast<const char *>(rdram.data() + kPadDataAddr + 64);
            t.IsTrue(std::string(reqStr).find("COMPLETE") != std::string::npos, "req string should include COMPLETE");
        });
    });
}
