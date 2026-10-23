#include <cstdio>
bool check_raylib();
bool check_imgui();
bool check_ffmpeg();
bool check_directx();
int main() {
    const bool ray = check_raylib(), gui = check_imgui(), media = check_ffmpeg(), dx = check_directx();
    std::printf("{\"raylib\":%s,\"imgui\":%s,\"ffmpeg\":%s,\"directx_headers\":%s}\n",
        ray ? "true" : "false", gui ? "true" : "false", media ? "true" : "false", dx ? "true" : "false");
    return ray && gui && media && dx ? 0 : 1;
}
