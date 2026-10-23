#pragma once
#include <filesystem>

namespace ps2_saves
{
    std::filesystem::path fileCardRoot(const std::filesystem::path &gameDirectory);
    std::filesystem::path nativeCardRoot(const std::filesystem::path &fileCardRoot);
    // Copy legacy game-local storage once, without overwriting or deleting it.
    void migrateLegacyStorage(const std::filesystem::path &gameDirectory);
}
