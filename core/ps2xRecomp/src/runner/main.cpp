#include "ps2recomp/ps2_recompiler.h"
#include "ps2recomp/lodestone_prune.h"
#include <filesystem>
#include <iostream>
#include <string>

using namespace ps2recomp;

void printUsage()
{
    std::cout << "PS2Recomp - A static recompiler for PlayStation 2 ELF files\n";
    std::cout << "Usage: ps2recomp <config.toml> [--prune-stale] [--prune-dry-run]\n";
    std::cout << "  config.toml: Configuration file for the recompiler\n";
    std::cout << "\n";
    std::cout << "  --prune-stale    delete generated .cpp files that the registration\n";
    std::cout << "                   file no longer references (Lodestone patch 3).\n";
    std::cout << "                   Off by default: deleting files is not something a\n";
    std::cout << "                   code generator should do behind your back.\n";
    std::cout << "  --prune-dry-run  report what would be deleted, delete nothing.\n";
}

int main(int argc, char *argv[])
{
    if (argc < 2)
    {
        printUsage();
        return 1;
    }

    std::string configPath;
    bool pruneStale = false;
    bool pruneDryRun = false;

    for (int i = 1; i < argc; ++i)
    {
        const std::string arg = argv[i];
        if (arg == "--prune-stale")
        {
            pruneStale = true;
        }
        else if (arg == "--prune-dry-run")
        {
            pruneDryRun = true;
        }
        else if (!arg.empty() && arg[0] != '-')
        {
            configPath = arg;
        }
    }

    if (configPath.empty())
    {
        printUsage();
        return 1;
    }

    try
    {
        PS2Recompiler recompiler(configPath);

        if (!recompiler.initialize())
        {
            std::cerr << "Failed to initialize recompiler\n";
            recompiler.printReport();
            return 1;
        }

        if (!recompiler.recompile())
        {
            std::cerr << "Recompilation failed\n";
            recompiler.printReport();
            return 1;
        }

        recompiler.generateOutput();
        recompiler.printReport();

        // LODESTONE PATCH 3: the recompiler only writes, never deletes, so a
        // rename leaves two translation units claiming the same guest address.
        // Opt-in because it removes files. See dead_ends.jsonl#0045.
        if (pruneStale || pruneDryRun)
        {
            const std::filesystem::path generatedDir(recompiler.config().outputPath);
            const std::filesystem::path manifest =
                generatedDir / "register_functions.cpp";
            bool pruningSucceeded = false;
            lodestone::PruneStaleGeneratedFiles(
                generatedDir, manifest, /*dryRun=*/pruneDryRun, std::cout, &pruningSucceeded);
            if (!pruningSucceeded)
            {
                std::cerr << "Generated output written, but requested pruning did not complete\n";
                return 1;
            }
        }

        std::cout << "Recompilation completed successfully\n";
        return 0;
    }
    catch (const std::exception &e)
    {
        std::cerr << "Error: " << e.what() << std::endl;
        return 1;
    }
}
