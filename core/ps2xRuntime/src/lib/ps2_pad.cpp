#include "runtime/ps2_pad.h"
#include "ps2_host_backend.h"
#include "ps2_gamepad_mappings.h"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <iostream>
#include <string>
#include <string_view>
#include <unordered_map>
#include <cstdlib>
#include <chrono>
#include <cstdio>
#if defined(PS2X_HOST_GLFW)
#define GLFW_INCLUDE_NONE
#include <GLFW/glfw3.h>
#endif

// Opt-in observation of both publications and native guest consumption.
// Keep the shared writer here so neither thread interleaves diagnostic lines.
static bool ps2PadTracingEnabled()
{
    static const bool enabled = [] {
        const char *value = std::getenv("PS2X_TRACE_PAD");
        return value && *value == '1';
    }();
    return enabled;
}
static void tracePadInput(const char *stage, int focused, int selected, const uint8_t *data, uint64_t eeTick)
{
    if (!ps2PadTracingEnabled()) return;
    static std::mutex mutex;
    static std::array<uint8_t, 8> last[4]{};
    static int lastFocus[4]{-1, -1, -1, -1}, lastSelected[4]{-2, -2, -2, -2};
    static bool first[4]{true, true, true, true};
    static const auto start = std::chrono::steady_clock::now();
    const int source = stage[0] == 'h' ? 0 : stage[0] == 'r' ? 2 : stage[0] == 'l' ? 3 : 1;
    std::lock_guard<std::mutex> lock(mutex);
    if (!first[source] && lastFocus[source] == focused && lastSelected[source] == selected &&
        std::memcmp(last[source].data(), data, 8) == 0) return;
    first[source] = false;
    lastFocus[source] = focused;
    lastSelected[source] = selected;
    std::memcpy(last[source].data(), data, 8);
    const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - start).count();
    const auto hostMs = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
    std::fprintf(stderr, "[pad trace] stage=%s ms=%lld focused=%d host=%d buttons=%u lx=%u ly=%u rx=%u ry=%u host_ms=%lld ee_tick=%llu\n",
        stage, static_cast<long long>(ms), focused, selected,
        unsigned(uint16_t(data[2]) | uint16_t(data[3]) << 8),
        unsigned(data[6]), unsigned(data[7]), unsigned(data[4]), unsigned(data[5]),
        static_cast<long long>(hostMs), static_cast<unsigned long long>(eeTick));
}
void ps2TracePadInput(const char *stage, int focused, int selected, const uint8_t *data)
{
    tracePadInput(stage, focused, selected, data, 0u);
}
void ps2TraceReplayPadInput(uint64_t tick, int port, const uint8_t *data)
{
    tracePadInput("replay", -1, port, data, tick);
}
void ps2TraceLivePadInput(uint64_t tick, int port, const uint8_t *data)
{
    tracePadInput("live", -1, port, data, tick);
}
namespace {
constexpr uint16_t masks[]{0x10,0x40,0x80,0x20,0x4000,0x2000,0x8000,0x1000,0x400,0x800,0x100,0x200,0x8,0x1,0x2,0x4};
constexpr int hostButtons[]{GAMEPAD_BUTTON_LEFT_FACE_UP,GAMEPAD_BUTTON_LEFT_FACE_DOWN,GAMEPAD_BUTTON_LEFT_FACE_LEFT,GAMEPAD_BUTTON_LEFT_FACE_RIGHT,GAMEPAD_BUTTON_RIGHT_FACE_DOWN,GAMEPAD_BUTTON_RIGHT_FACE_RIGHT,GAMEPAD_BUTTON_RIGHT_FACE_LEFT,GAMEPAD_BUTTON_RIGHT_FACE_UP,GAMEPAD_BUTTON_LEFT_TRIGGER_1,GAMEPAD_BUTTON_RIGHT_TRIGGER_1,GAMEPAD_BUTTON_LEFT_TRIGGER_2,GAMEPAD_BUTTON_RIGHT_TRIGGER_2,GAMEPAD_BUTTON_MIDDLE_RIGHT,GAMEPAD_BUTTON_MIDDLE_LEFT,GAMEPAD_BUTTON_LEFT_THUMB,GAMEPAD_BUTTON_RIGHT_THUMB};
constexpr uint16_t pressureMasks[]{0x20,0x80,0x10,0x40,0x1000,0x2000,0x4000,0x8000,0x400,0x800,0x100,0x200};
float finiteAxis(float v) { return std::isfinite(v) ? std::clamp(v,-1.f,1.f) : 0.f; }
uint8_t axisByte(float v) { return static_cast<uint8_t>(std::lround((finiteAxis(v)+1.f)*127.5f)); }
void stick(float x,float y,uint8_t &ox,uint8_t &oy) {
    x=finiteAxis(x); y=finiteAxis(y); const float length=std::hypot(x,y); constexpr float deadzone=0.08f;
    if(length<=deadzone) { ox=oy=128; return; }
    const float scale=(length-deadzone)/((1.f-deadzone)*length); ox=axisByte(x*scale); oy=axisByte(y*scale);
}
uint8_t trigger(float v) {
    if(!std::isfinite(v)) return 0;
    const float pull=(std::clamp(v,-1.f,1.f)+1.f)*0.5f;
    return static_cast<uint8_t>(std::lround(std::clamp((pull-0.05f)/0.95f,0.f,1.f)*255.f));
}
#if defined(PS2X_HOST_GLFW)
const bool useFreshGlfwPad = [] {
    const char *value = std::getenv("PS2X_PAD_FRESH_GLFW");
    return value && *value == '1';
}();
unsigned missingTriggerMask(int id)
{
    // GLFW leaves unmapped axes at zero, which would otherwise look like a
    // half-pressed trigger on older controllers with no trigger mapping.
    static const auto masks = [] {
        std::unordered_map<std::string, unsigned> result;
#if defined(_WIN32)
        constexpr std::string_view platform = ",platform:Windows,";
#elif defined(__APPLE__)
        constexpr std::string_view platform = ",platform:Mac OS X,";
#else
        constexpr std::string_view platform = ",platform:Linux,";
#endif
        for (const char *line : kHostGamepadMappings)
        {
            const std::string_view text(line);
            if (text.size() < 33 || text.find(platform) == text.npos) continue;
            result[std::string(text.substr(0, 32))] =
                (text.find(",lefttrigger:") == text.npos ? 1u : 0u) |
                (text.find(",righttrigger:") == text.npos ? 2u : 0u);
        }
        return result;
    }();
    const char *guid = glfwGetJoystickGUID(id);
    if (!guid) return 0;
    const auto found = masks.find(guid);
    return found == masks.end() ? 0 : found->second;
}
#endif
}
void PSPadBackend::initializeHostMappings() {
    if(!IsWindowReady()) return;
#if defined(PS2X_HOST_GLFW)
    std::cerr << "[controller] input_backend=" << (useFreshGlfwPad ? "glfw-fresh" : "raylib") << '\n';
#endif
    for(const char *mapping:kHostGamepadMappings)
    {
#if defined(PS2X_HOST_GLFW)
        // SDL's special XInput alias is not a GUID accepted by GLFW. Its
        // XInput devices already have standard built-in GLFW mappings.
        if (std::strncmp(mapping, "xinput,", 7) == 0) continue;
#endif
        SetGamepadMappings(mapping);
    }
    pollHostInput();
}
void PSPadBackend::pollHostInput() {
    PSHostPadFrame frame; const bool ready=IsWindowReady(); frame.focused=ready && IsWindowFocused();
    for(int id=0;id<static_cast<int>(frame.gamepads.size());++id) {
        auto &pad=frame.gamepads[id];
#if defined(PS2X_HOST_GLFW)
        // The original raylib input route is the default. Keep fresh GLFW
        // sampling opt-in so physical regressions can be compared directly.
        if (useFreshGlfwPad) {
        GLFWgamepadstate state{};
        pad.connected=ready && glfwGetGamepadState(id,&state);
        if(!pad.connected || !frame.focused) continue;
        constexpr int buttons[]{GLFW_GAMEPAD_BUTTON_DPAD_UP,GLFW_GAMEPAD_BUTTON_DPAD_DOWN,
            GLFW_GAMEPAD_BUTTON_DPAD_LEFT,GLFW_GAMEPAD_BUTTON_DPAD_RIGHT,
            GLFW_GAMEPAD_BUTTON_A,GLFW_GAMEPAD_BUTTON_B,GLFW_GAMEPAD_BUTTON_X,GLFW_GAMEPAD_BUTTON_Y,
            GLFW_GAMEPAD_BUTTON_LEFT_BUMPER,GLFW_GAMEPAD_BUTTON_RIGHT_BUMPER,-1,-1,
            GLFW_GAMEPAD_BUTTON_START,GLFW_GAMEPAD_BUTTON_BACK,
            GLFW_GAMEPAD_BUTTON_LEFT_THUMB,GLFW_GAMEPAD_BUTTON_RIGHT_THUMB};
        for(size_t i=0;i<std::size(masks);++i)
            if(buttons[i]>=0 && state.buttons[buttons[i]]==GLFW_PRESS) pad.buttons &= ~masks[i];
        for(size_t axis=0;axis<pad.axes.size();++axis) pad.axes[axis]=state.axes[axis];
        const auto missing = missingTriggerMask(id);
        if (missing & 1) pad.axes[4] = -1.f;
        if (missing & 2) pad.axes[5] = -1.f;
        } else
#endif
        {
        pad.connected=ready && IsGamepadAvailable(id);
        if(!pad.connected || !frame.focused) continue;
        for(size_t i=0;i<std::size(masks);++i)
            if(IsGamepadButtonDown(id,hostButtons[i])) pad.buttons &= ~masks[i];
        for(size_t axis=0;axis<pad.axes.size();++axis) pad.axes[axis]=GetGamepadAxisMovement(id,static_cast<int>(axis));
#if defined(PS2X_HOST_GLFW)
        const auto missing = missingTriggerMask(id);
        if (missing & 1) pad.axes[4] = -1.f;
        if (missing & 2) pad.axes[5] = -1.f;
#endif
        }
    }
    if(frame.focused) {
        auto key=[&](uint16_t mask,bool down) { if(down) frame.keyboardButtons &= ~mask; };
        key(0x10,IsKeyDown(KEY_UP)||IsKeyDown(KEY_W)); key(0x40,IsKeyDown(KEY_DOWN)||IsKeyDown(KEY_S));
        key(0x80,IsKeyDown(KEY_LEFT)||IsKeyDown(KEY_A)); key(0x20,IsKeyDown(KEY_RIGHT)||IsKeyDown(KEY_D));
        key(0x4000,IsKeyDown(KEY_X)||IsKeyDown(KEY_SPACE)); key(0x2000,IsKeyDown(KEY_C)||IsKeyDown(KEY_ESCAPE));
        key(0x8000,IsKeyDown(KEY_Z)||IsKeyDown(KEY_KP_0)); key(0x1000,IsKeyDown(KEY_V)||IsKeyDown(KEY_KP_1));
        key(0x400,IsKeyDown(KEY_Q)); key(0x800,IsKeyDown(KEY_E));
        key(0x100,IsKeyDown(KEY_LEFT_SHIFT)); key(0x200,IsKeyDown(KEY_RIGHT_SHIFT));
        key(0x8,IsKeyDown(KEY_ENTER)); key(0x1,IsKeyDown(KEY_TAB));
        key(0x2,IsKeyDown(KEY_LEFT_CONTROL)); key(0x4,IsKeyDown(KEY_RIGHT_CONTROL));
    }
    const int previous=activeGamepad(); publishHostFrame(frame); const int selected=activeGamepad();
    if (ps2PadTracingEnabled()) {
        uint8_t published[32]{};
        if (readState(0, 0, published, sizeof(published)))
            ps2TracePadInput("host", frame.focused ? 1 : 0, selected, published);
    }
    if(previous!=selected) {
#if defined(PS2X_HOST_GLFW)
        const char *name=selected<0 ? "keyboard" : glfwGetGamepadName(selected);
#else
        const char *name=selected<0 ? "keyboard" : GetGamepadName(selected);
#endif
        std::cerr << "[controller] " << (name ? name : "gamepad") << " host=" << selected << " PS2-port=0\n";
    }
}
void PSPadBackend::publishHostFrame(const PSHostPadFrame &frame) {
    std::lock_guard<std::mutex> lock(m_mutex);
    if(m_activeGamepad<0 || !frame.gamepads[m_activeGamepad].connected) {
        m_activeGamepad=-1;
        for(size_t i=0;i<frame.gamepads.size();++i) if(frame.gamepads[i].connected) { m_activeGamepad=static_cast<int>(i); break; }
    }
    m_data={1,0x73,0xff,0xff,128,128,128,128};
    if(!frame.focused) return;
    uint16_t buttons=frame.keyboardButtons; uint8_t lt=0,rt=0;
    if(m_activeGamepad>=0) {
        const auto &pad=frame.gamepads[m_activeGamepad]; buttons=pad.buttons;
        stick(pad.axes[0],pad.axes[1],m_data[6],m_data[7]); stick(pad.axes[2],pad.axes[3],m_data[4],m_data[5]);
        lt=trigger(pad.axes[4]); rt=trigger(pad.axes[5]);
        // Trigger activation near the start of travel; retain analog pressure.
        if(lt>=16) buttons &= ~0x100u;
        if(rt>=16) buttons &= ~0x200u;
    }
    m_data[2]=static_cast<uint8_t>(buttons); m_data[3]=static_cast<uint8_t>(buttons>>8);
    for(size_t i=0;i<std::size(pressureMasks);++i) m_data[8+i]=(buttons & pressureMasks[i]) ? 0 : 255;
    if(m_activeGamepad>=0) {
        m_data[18]=lt ? lt : ((buttons & 0x100) ? 0 : 255);
        m_data[19]=rt ? rt : ((buttons & 0x200) ? 0 : 255);
    }
}
int PSPadBackend::activeGamepad() const { std::lock_guard<std::mutex> lock(m_mutex); return m_activeGamepad; }
bool PSPadBackend::readState(int port,int slot,uint8_t *data,size_t size) {
    if(port!=0 || slot!=0 || !data || size<m_data.size()) return false;
    std::lock_guard<std::mutex> lock(m_mutex); std::memcpy(data,m_data.data(),m_data.size()); return true;
}
