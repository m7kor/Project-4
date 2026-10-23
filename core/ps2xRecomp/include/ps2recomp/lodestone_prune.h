// LODESTONE PATCH 3 — generated-file pruning.
//
// Measured problem: renaming one function in the Ghidra CSV and regenerating
// produced
//     CHANGED files : 1   (register_functions.cpp)
//     NEW files     : 1   (NewName_0xADDR.cpp)
//     GONE files    : 0   (OldName_0xADDR.cpp still on disk)
//
// The recompiler only ever writes; it never deletes. After a rename the output
// directory holds two translation units that both claim the same guest address,
// and only one is referenced by the function table. The other is dead code that
// still compiles, still links and still obscures the real state of the build.
//
// This is worse than it looks, because `lodestone profile` and the triage
// engine read the directory to decide what exists. A stale file is a false
// positive: it makes a removed function look present.
//
// Fix: a prune step, driven by the manifest the recompiler already writes
// (register_functions.cpp names every live function), that deletes any
// NAME_0xADDR.cpp not referenced by it.
//
// Recorded as dead_ends.jsonl#0045.

#ifndef LODESTONE_PRUNE_H
#define LODESTONE_PRUNE_H

#include <cctype>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <set>
#include <string>
#include <vector>

namespace lodestone
{
    // Collect every function name that the generated registration file actually
    // references. That file is the authority: the recompiler writes it from the
    // same map it used to emit the bodies.
    //
    // Format emitted by FunctionTableEmitter:
    //     g_ps2RecompiledFunctionTable[73] = lodestone_probe_entry_0x100008; // 0x10012c
    //
    // Parsed by hand rather than with std::regex: std::regex over a 5904-entry
    // manifest costs ~40ms and its ECMAScript \s handling is not worth
    // debugging. A plain scan for '=' then the following identifier is exact.
    // Names as they appear in the manifest, which is what the FILENAMES are too.
    //
    // FunctionTableEmitter writes:
    //     g_ps2RecompiledFunctionTable[0] = FUN_00100008_0x100008; // 0x100008
    // and ps2_recompiler.cpp writes the file as
    //     <that exact name>.cpp
    // So the manifest name and the filename stem are IDENTICAL, including the
    // "_0xADDR" part. Do not strip the suffix — an earlier version of this code
    // stripped it and consequently matched nothing, then reported every file as
    // stale. See the guard in PruneStaleGeneratedFiles.
    inline std::set<std::string> ReadLiveFunctionNames(const std::filesystem::path &registerFile)
    {
        static const std::string kTable = "g_ps2RecompiledFunctionTable[";

        std::set<std::string> names;
        std::ifstream in(registerFile);
        if (!in)
        {
            return names;
        }

        std::string line;
        bool sparseInitializer = false;
        while (std::getline(in, line))
        {
            const auto sparseAt = line.find("g_ps2RecompiledFunctionSparseTarget[");
            std::size_t sparseStart = 0;
            if (sparseAt != std::string::npos)
            {
                const auto brace = line.find('{', sparseAt);
                if (brace != std::string::npos)
                {
                    sparseInitializer = true;
                    sparseStart = brace + 1;
                }
            }
            if (sparseInitializer)
            {
                const auto end = line.find('}', sparseStart);
                const auto limit = end == std::string::npos ? line.size() : end;
                for (std::size_t i = sparseStart; i < limit;)
                {
                    if (!std::isalpha(static_cast<unsigned char>(line[i])) && line[i] != '_')
                    {
                        ++i;
                        continue;
                    }
                    const auto start = i++;
                    while (i < limit && (std::isalnum(static_cast<unsigned char>(line[i])) || line[i] == '_'))
                        ++i;
                    const auto name = line.substr(start, i - start);
                    if (name != "nullptr")
                        names.insert(name);
                }
                if (end != std::string::npos)
                    sparseInitializer = false;
                continue;
            }
            const std::size_t tableAt = line.find(kTable);
            if (tableAt == std::string::npos)
            {
                continue;
            }
            const std::size_t assignAt = line.find('=', tableAt + kTable.size());
            if (assignAt == std::string::npos)
            {
                continue;
            }

            std::size_t i = assignAt + 1;
            while (i < line.size() && (line[i] == ' ' || line[i] == '\t'))
            {
                ++i;
            }
            const std::size_t nameStart = i;
            while (i < line.size() &&
                   (std::isalnum(static_cast<unsigned char>(line[i])) || line[i] == '_'))
            {
                ++i;
            }
            if (i > nameStart)
            {
                names.insert(line.substr(nameStart, i - nameStart));
            }
        }
        return names;
    }

    inline bool IsGeneratedFunctionSource(const std::filesystem::path &path)
    {
        if (path.extension() != ".cpp") return false;
        const auto stem = path.stem().string();
        const auto suffix = stem.rfind("_0x");
        if (suffix == std::string::npos || suffix == 0 || suffix + 3 == stem.size()) return false;
        for (std::size_t i = 0; i < suffix; ++i)
            if (!std::isalnum(static_cast<unsigned char>(stem[i])) && stem[i] != '_') return false;
        for (std::size_t i = suffix + 3; i < stem.size(); ++i)
            if (!std::isxdigit(static_cast<unsigned char>(stem[i]))) return false;
        return true;
    }

    // Delete generated files that the live manifest does not reference.
    // dryRun=true reports without touching the filesystem.
    //
    // Only files matching the recompiler's own naming convention are considered,
    // so hand-written files in the same directory are never at risk.
    inline std::size_t PruneStaleGeneratedFiles(const std::filesystem::path &generatedDir,
                                                 const std::filesystem::path &registerFile,
                                                 bool dryRun,
                                                 std::ostream &log,
                                                 bool *succeeded = nullptr)
    {
        namespace fs = std::filesystem;
        if (succeeded) *succeeded = false;

        if (!fs::exists(generatedDir) || !fs::exists(registerFile))
        {
            log << "prune: generated dir or register file missing; nothing to do\n";
            return 0;
        }

        const auto live = ReadLiveFunctionNames(registerFile);
        if (live.empty())
        {
            // Refuse to guess. An empty manifest means the recompiler failed, not
            // that every file is stale.
            log << "prune: manifest listed 0 functions; refusing to touch the tree\n";
            return 0;
        }

        std::size_t removed = 0;
        std::size_t kept = 0;
        std::vector<fs::path> victims;

        // SAFETY GATE — the single most important thing in this file.
        //
        // The first implementation of this pruner compared the filename WITHOUT
        // its "_0xADDR" suffix against manifest names that INCLUDE the suffix.
        // Nothing matched, so every one of 5,904 files was classified stale and
        // deleted, taking the whole port with it. Regenerating restored it in
        // 11 seconds, but only because output is deterministic.
        //
        // Rule: if the number of files the manifest claims is not within ±2% of
        // the number of files present, the manifest and the directory disagree,
        // and we delete NOTHING. A wrong pruner that deletes nothing is a
        // nuisance; one that deletes everything is a lost port.
        std::size_t present = 0;
        for (const auto &entry : fs::directory_iterator(generatedDir))
        {
            if (entry.is_regular_file() &&
                IsGeneratedFunctionSource(entry.path()))
            {
                ++present;
            }
        }

        const std::size_t claimed = live.size();
        const std::size_t slack = claimed / 50 + 1; // 2%, minimum 1
        const bool plausible =
            claimed > 0 &&
            present >= (claimed > slack ? claimed - slack : 0) &&
            present <= claimed + slack;

        if (!plausible)
        {
            log << "prune: REFUSING. manifest claims " << claimed
                << " functions, directory holds " << present
                << " generated .cpp files (tolerance " << slack << "). "
                << "They disagree, so staleness cannot be trusted.\n";
            return 0;
        }
        if (succeeded) *succeeded = true;

        for (const auto &entry : fs::directory_iterator(generatedDir))
        {
            if (!entry.is_regular_file())
            {
                continue;
            }

            const fs::path &path = entry.path();
            if (!IsGeneratedFunctionSource(path))
            {
                continue; // headers
            }

            const std::string filename = path.filename().string();
            if (filename == "register_functions.cpp")
            {
                continue; // the manifest itself
            }

            // The stem IS the manifest name, suffix included.
            const std::string stem = filename.substr(0, filename.size() - 4);
            if (live.count(stem) != 0)
            {
                ++kept;
                continue;
            }

            victims.push_back(path);
        }

        for (const auto &victim : victims)
        {
            log << "prune: stale " << victim.filename().string() << "\n";
            if (!dryRun)
            {
                std::error_code ec;
                fs::remove(victim, ec);
                if (ec)
                {
                    if (succeeded) *succeeded = false;
                    log << "prune: FAILED to remove " << victim.filename().string()
                        << ": " << ec.message() << "\n";
                    continue;
                }
            }
            ++removed;
        }

        log << "prune: " << removed << " stale, " << kept << " live, "
            << claimed << " in manifest"
            << (dryRun ? "  [dry run]" : "") << "\n";
        return removed;
    }
}

#endif // LODESTONE_PRUNE_H
