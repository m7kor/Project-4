#include "emulator/core/iop_memory.h"
#include <array>
#include <iostream>
#include <stdexcept>
#include <algorithm>
#include <cstdlib>
#include "emulator/iop_emulator.h"
#include "iop_compat_test_support.h"

int main()
{
    using ps2x::iop::detail::IopMemory;
    unsigned failures = 0;
    auto check = [&](bool value, const char *message) {
        if (!value) { ++failures; std::cerr << "FAIL " << message << '\n'; }
    };
    {
    IopMemory memory;
    check(memory.enableNativeSpu2(), "native hardware backend enabled");
    memory.write32(0xBF900000u, 0x24681357u);
    check(memory.read16(0x1F900000u) == 0x1357u && memory.read16(0x1F900002u) == 0x2468u, "32-bit mirrored writes route both native register lanes");
    memory.write8(0xBF900001u, 0x12u);
    check(memory.read16(0x1F900000u) == 0x1257u && memory.read16(0x1F900002u) == 0x2468u, "byte write preserves both neighboring lanes");
    uint64_t cycle = 0;
    auto finish = [&](uint32_t dma) {
        const uint64_t deadline = cycle + 100000u;
        while ((memory.read32(dma + 8u) & 0x01000000u) && cycle < deadline)
        {
            cycle = std::max(cycle + 1u, std::min(deadline, memory.nextSpu2Event()));
            memory.advanceSpu2(cycle);
        }
        check(!(memory.read32(dma + 8u) & 0x01000000u), "DMA completes within bounded event progression");
    };
    for (unsigned core = 0; core < 2; ++core)
    {
        const uint32_t regs = 0x1F900000u + core * 0x400u;
        const uint32_t dma = core ? 0x1F801500u : 0x1F8010C0u;
        const uint32_t source = 0x4000u + core * 0x1000u, destination = source + 0x400u;
        std::array<uint16_t, 128> payload{}, copy{};
        for (unsigned i = 0; i < payload.size(); ++i) payload[i] = static_cast<uint16_t>(i * 317u + core * 31u);
        check(memory.writeRam(source, payload.data(), sizeof(payload)), "guest DMA source populated");
        memory.write16(regs + 0x19Au, 0xC020u); // enable, DMA write
        memory.write16(regs + 0x1A8u, 0u);
        memory.write16(regs + 0x1AAu, 0x5000u + core * 0x1000u);
        memory.write32(dma, source);
        check(memory.read32(dma) == source, "MADR before DMA reflects programmed source");
        memory.write32(dma + 4u, 0x00010040u);
        memory.write32(dma + 8u, 0x01000201u);
        check((memory.read32(dma + 8u) & 0x01000000u) != 0u, "CHCR stays busy after start");
        check(!memory.takeDmaStart().has_value(), "native DMA does not queue a placeholder completion");
        finish(dma);
        check((memory.takeSpu2Events() & (2u << core)) != 0u, "write produces real core completion");
        check(!(memory.read32(dma + 8u) & 0x01000000u), "completion clears CHCR");
        check(memory.read32(dma) == source + sizeof(payload), "write advances MADR by bytes transferred");
        memory.write8(destination - 1u, 0xA5u);
        memory.write8(destination + sizeof(payload), 0xA5u);
        memory.write16(regs + 0x19Au, 0xC030u); // DMA read
        memory.write16(regs + 0x1A8u, 0u);
        memory.write16(regs + 0x1AAu, 0x5000u + core * 0x1000u);
        memory.write32(dma, destination);
        memory.write32(dma + 4u, 0x00010040u);
        memory.write32(dma + 8u, 0x01000200u);
        finish(dma);
        check((memory.takeSpu2Events() & (2u << core)) != 0u, "read produces real completion");
        check(memory.readRam(destination, copy.data(), sizeof(copy)) && copy == payload, "both-core SPU RAM roundtrip matches every word");
        check(memory.ownsRamRange(destination, sizeof(copy)), "native read marks guest destination as populated");
        check(memory.read8(destination - 1u) == 0xA5u && memory.read8(destination + sizeof(copy)) == 0xA5u, "DMA preserves both destination guards");
    }
    std::array<int16_t, 64> audio{};
    check(memory.readAudio(audio.data(), 32u) > 0u, "native PCM reaches the host drain API");
    memory.reset();
    check(memory.readAudio(audio.data(), 32u) == 0u, "reset discards queued audio");
    check(memory.takeSpu2Events() == 0u, "reset clears pending native events");
    memory.write32(0x1F8010C0u, IopMemory::RamSize - 8u);
    memory.write32(0x1F8010C4u, 0x00010040u);
    bool rejected = false;
    try { memory.write32(0x1F8010C8u, 0x01000201u); }
    catch (const std::runtime_error &) { rejected = true; }
    check(rejected, "reject DMA beyond actual IOP RAM");
    }
    {
        // An IOP reboot (RE4 sends rom0:UDNL with its IOPRP image at boot)
        // restarts the IOP clock at zero; the SPU2 must keep mixing and
        // completing DMA in the new clock instead of waiting for the old one.
        IopMemory memory;
        check(memory.enableNativeSpu2(), "native backend enabled for reset clock test");
        std::array<int16_t, 2048> drain{};
        auto drained = [&] {
            uint64_t frames = 0;
            for (uint32_t got; (got = memory.readAudio(drain.data(), 1024u)) != 0u;) frames += got;
            return frames;
        };
        constexpr uint64_t kSample = 768u, kSecond = 48000u * kSample;
        uint64_t beforeReset = 0; // the output ring holds 16384 frames: drain every 0.1 s
        for (uint64_t step = 1u; step <= 10u; ++step)
        {
            memory.advanceSpu2(step * kSecond / 10u);
            beforeReset += drained();
        }
        check(beforeReset >= 47900u && beforeReset <= 48000u, "one IOP second before the reboot mixes 48 kHz PCM");
        memory.reset();
        memory.advanceSpu2(kSecond / 10u);
        const uint64_t afterReset = drained();
        check(afterReset >= 4700u && afterReset <= 4900u, "first 0.1 s after the reboot mixes 4800 frames, not silence");
        uint64_t cycle = kSecond / 10u;
        const uint32_t source = 0x4000u;
        std::array<uint16_t, 128> payload{};
        payload.fill(0x1234u);
        check(memory.writeRam(source, payload.data(), sizeof(payload)), "post-reboot DMA source populated");
        memory.write16(0x1F90019Au, 0xC020u);
        memory.write16(0x1F9001A8u, 0u);
        memory.write16(0x1F9001AAu, 0x5000u);
        memory.write32(0x1F8010C0u, source);
        memory.write32(0x1F8010C4u, 0x00010040u);
        memory.write32(0x1F8010C8u, 0x01000201u);
        const uint64_t deadline = cycle + 100000u;
        while ((memory.read32(0x1F8010C8u) & 0x01000000u) && cycle < deadline)
        {
            cycle = std::max(cycle + 1u, std::min(deadline, memory.nextSpu2Event()));
            memory.advanceSpu2(cycle);
        }
        check(!(memory.read32(0x1F8010C8u) & 0x01000000u), "DMA after the reboot completes within bounded progression");
        check((memory.takeSpu2Events() & 2u) != 0u, "post-reboot DMA raises its completion event");
        memory.reset();
        memory.advanceSpu2(kSecond / 100u);
        check(drained() >= 470u, "a second reboot keeps the clock running as well");
    }
    {
        iop_test::Host host;
        iop_test::Irx image(0x10000u, 0x1000u);
        // The guest, not the test host, registers and masks the real DMA IRQ.
        image.words(0u, {
            0x27BDFFE0u, 0xAFBF001Cu,
            0x24040024u, 0x24050001u, 0x3C060001u, 0x34C60180u,
            0x3C070001u, 0x34E70400u, 0x0C004085u, 0u,
            0x24040024u, 0x0C004087u, 0u, 0x0C004089u, 0u,
            0x3C091F90u, 0x3529019Au, 0x340AC020u, 0xA52A0000u,
            0x3C091F80u, 0x352910C0u,
            0x3C0A0001u, 0x354A0480u, 0xAD2A0000u,
            0x3C0A0001u, 0x354A0040u, 0xAD2A0004u,
            0x3C0A0100u, 0x354A0201u, 0xAD2A0008u,
            0x340A1000u, 0x254AFFFFu, 0x1540FFFEu, 0u,
            0x3C080001u, 0x35080400u, 0x8D0A0000u, 0u, 0xAD0A0004u,
            0x0C00408Bu, 0u,
            0x340A1000u, 0x254AFFFFu, 0x1540FFFEu, 0u,
            0x8D0A0000u, 0u, 0xAD0A0008u,
            0x8FBF001Cu, 0x27BD0020u, 0x03E00008u, 0x00001021u});
        image.words(0x180u, {0x8C820000u, 0u, 0x24420001u, 0xAC820000u, 0x03E00008u, 0x24020001u});
        image.words(0x200u, {0x41E00000u, 0u, 0x102u, 0x72746E69u, 0x006E616Du,
                            0x03E00008u, 0x24000004u, 0x03E00008u, 0x24000006u,
                            0x03E00008u, 0x24000008u, 0x03E00008u, 0x24000009u, 0u, 0u});
        image.install(host);
        _putenv_s("PS2X_IOP_SPU2_NATIVE", "1");
        ps2x::iop::detail::IopEmulator emulator(host);
        _putenv_s("PS2X_IOP_SPU2_NATIVE", "");
        const auto loaded = emulator.loadModuleBuffer(0x1000u, nullptr, 0u);
        check(loaded.moduleId > 0, "native DMA IRX executes");
        uint32_t counts[3]{};
        check(emulator.readMemory(0x10400u, counts, sizeof(counts)), "read guest-observed native IRQ counts");
        check(counts[1] == 0u, "native completion respects guest CPU interrupt mask");
        check(counts[2] == 1u && counts[0] == 1u, "native completion reaches guest exactly once after re-enable");
    }
    std::cout << (failures ? "FAIL" : "PASS") << " bridge failures=" << failures << '\n';
    return failures ? 1 : 0;
}
