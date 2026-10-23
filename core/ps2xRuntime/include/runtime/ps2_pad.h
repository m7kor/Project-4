#ifndef PS2_PAD_H
#define PS2_PAD_H

#include <cstddef>
#include <cstdint>
#include <array>
#include <mutex>

// Normalized host state, independent of brand and of game UI artwork.
struct PSHostGamepadState
{
    bool connected = false;
    uint16_t buttons = 0xffffu;
    std::array<float, 6> axes{0, 0, 0, 0, -1, -1}; // LX, LY, RX, RY, LT, RT
};

struct PSHostPadFrame
{
    std::array<PSHostGamepadState, 4> gamepads{};
    uint16_t keyboardButtons = 0xffffu;
    bool focused = true;
};

class PSPadBackend
{
public:
    PSPadBackend() = default;
    ~PSPadBackend() = default;

    bool readState(int port, int slot, uint8_t *data, size_t size);
    void initializeHostMappings(); // window thread, after InitWindow
    void pollHostInput(); // window thread; guest reads only the published snapshot
    void publishHostFrame(const PSHostPadFrame &frame);
    int activeGamepad() const;

private:
    mutable std::mutex m_mutex;
    std::array<uint8_t, 32> m_data{1, 0x73, 0xff, 0xff, 128, 128, 128, 128};
    int m_activeGamepad = -1;
};

#endif
