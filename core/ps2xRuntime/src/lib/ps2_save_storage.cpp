#include "runtime/ps2_save_storage.h"
#include <fstream>
#include <iterator>
#include <stdexcept>
#include <string>

namespace ps2_saves
{
    std::filesystem::path fileCardRoot(const std::filesystem::path &gameDirectory)
    {
        return gameDirectory / "saves" / "mc0";
    }

    std::filesystem::path nativeCardRoot(const std::filesystem::path &fileRoot)
    {
        return fileRoot.parent_path() / "cards";
    }

    void migrateLegacyStorage(const std::filesystem::path &gameDirectory)
    {
        if (gameDirectory.empty()) throw std::runtime_error("save storage requires a game directory");
        const auto saves = gameDirectory / "saves";
        const auto marker = saves / ".legacy-migration-complete";
        constexpr char version[] = "PS2Recomp save storage v1\n";
        if (std::filesystem::is_symlink(saves) || std::filesystem::is_symlink(marker))
            throw std::runtime_error("refusing linked save storage or migration marker");
        if (std::filesystem::exists(marker))
        {
            std::ifstream file(marker, std::ios::binary);
            const std::string contents((std::istreambuf_iterator<char>(file)), {});
            if (contents != version) throw std::runtime_error("invalid save migration marker: " + marker.string());
            return;
        }
        std::filesystem::create_directories(saves);
        for (int port = 0; port < 2; ++port)
        {
            const auto name = "mc" + std::to_string(port);
            const auto legacy = gameDirectory / name;
            if (!std::filesystem::exists(legacy)) continue;
            if (std::filesystem::is_symlink(legacy))
                throw std::runtime_error("refusing linked legacy save directory: " + legacy.string());
            for (const auto &entry : std::filesystem::recursive_directory_iterator(legacy))
            {
                if (entry.is_symlink()) throw std::runtime_error("refusing linked legacy save entry: " + entry.path().string());
                const auto relative = entry.path().lexically_relative(legacy);
                const bool rawCard = entry.is_regular_file() && relative.has_filename() &&
                    relative.parent_path().empty() && relative.filename() == "native-card-" + std::to_string(port) + ".ps2";
                const auto destination = rawCard ? saves / "cards" / relative : saves / name / relative;
                for (auto path = destination; path != saves && !path.empty(); path = path.parent_path())
                    if (std::filesystem::is_symlink(path))
                        throw std::runtime_error("refusing linked save destination: " + path.string());
                if (entry.is_directory()) std::filesystem::create_directories(destination);
                else if (entry.is_regular_file() && !std::filesystem::exists(destination))
                {
                    std::filesystem::create_directories(destination.parent_path());
                    // copy_options::none rejects an existing destination, including
                    // a concurrent creator. Never replace current save data.
                    std::filesystem::copy_file(entry.path(), destination, std::filesystem::copy_options::none);
                }
            }
        }
        // The marker prevents deleted/formatted saves being resurrected from
        // the retained legacy backup on subsequent starts.
        std::ofstream file(marker, std::ios::binary);
        file << version;
        file.flush();
        if (!file) throw std::runtime_error("could not record completed save migration: " + marker.string());
    }
}
