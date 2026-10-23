#include <imgui.h>
#include <cstdio>
bool check_imgui() {
    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    unsigned char* pixels = nullptr;
    int width = 0, height = 0;
    ImGui::GetIO().IniFilename = nullptr;
    ImGui::GetIO().Fonts->GetTexDataAsRGBA32(&pixels, &width, &height);
    const bool okay = pixels && width > 0 && height > 0;
    std::printf("imgui=%s font_atlas=%dx%d\n", ImGui::GetVersion(), width, height);
    ImGui::DestroyContext();
    return okay;
}
