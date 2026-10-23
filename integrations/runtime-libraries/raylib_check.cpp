#include <raylib.h>
#include <cstdio>
bool check_raylib() {
    Image image = GenImageColor(8, 8, Color{12, 34, 56, 255});
    if (!image.data) return false;
    Color pixel = GetImageColor(image, 3, 4);
    const bool okay = image.width == 8 && image.height == 8 && pixel.r == 12 && pixel.g == 34 && pixel.b == 56;
    UnloadImage(image);
    std::printf("raylib=%s image=%s\n", RAYLIB_VERSION, okay ? "ok" : "failed");
    return okay;
}
