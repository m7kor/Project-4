#ifndef PS2RECOMP_ELF_PARSER_H
#define PS2RECOMP_ELF_PARSER_H

#include <cstdint>
#include <elfio/elfio.hpp>
#include <string>
#include <vector>
#include <memory>
#include <unordered_set>

#include "ps2recomp/types.h"

namespace ps2recomp
{
        struct Relocation;
        struct Section;
        struct Function;
        struct Symbol;
        class RecompilerReporter;

        class ElfParser
        {
        public:
                explicit ElfParser(const std::string &filePath);
                ~ElfParser();

                bool parse();

                bool loadGhidraFunctionMap(const std::string &mapPath);

                // LODESTONE PATCH 18: register a block of file-resident bytes as
                // executable at a different address than where the file keeps
                // them. See RuntimeCodeRegion for why this is a synthetic Section
                // rather than a special case in the emitter.
                // Returns the number of regions actually installed.
                std::size_t addRuntimeCodeRegions(const std::vector<RuntimeCodeRegion> &regions);

                std::vector<Function> extractFunctions() const;
                std::vector<Function> extractExtraFunctions() const;
                std::vector<Symbol> extractSymbols();
                std::vector<Section> getSections();
                std::vector<Relocation> getRelocations();

                // Helper methods
                bool isValidAddress(uint32_t address) const;
                uint32_t readWord(uint32_t address) const;
                uint8_t *getSectionData(const std::string &sectionName) const;
                uint32_t getSectionAddress(const std::string &sectionName) const;
                uint32_t getSectionSize(const std::string &sectionName) const;
                uint32_t getEntryPoint() const;
                void setReporter(RecompilerReporter *reporter);
                void debugAddress(uint32_t address) const;

        private:
                std::string m_filePath;
                std::unique_ptr<ELFIO::elfio> m_elf;

                std::vector<Section> m_sections;
                std::vector<Symbol> m_symbols;
                std::vector<Relocation> m_relocations;
                std::vector<Function> m_extraFunctions;
                // Owns the bytes of every .runtime_code.* section, because
                // Section::data must stay valid for the life of the parser.
                std::vector<std::vector<uint8_t>> m_runtimeCodeStorage;
                bool m_hasLoadedGhidraMap = false;
                RecompilerReporter *m_reporter = nullptr;
                std::unordered_set<uint32_t> m_ghidraMapStarts;

                void loadSections();
                void loadSymbols();
                void loadRelocations();
                void loadDebugFunctions();
                bool isExecutableSection(const ELFIO::section *section) const;
                bool isDataSection(const ELFIO::section *section) const;
        };

} // namespace ps2recomp

#endif // PS2RECOMP_ELF_PARSER_H
