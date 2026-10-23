// Private to ps2_vu1_execution.cpp. No generated-runner header dependency.
// Wire layout: 16 little-endian uint64 values, before state, code, before
// data, after state, after data. State padding is stored but never compared.
namespace
{
    class Vu1CommandTrace
    {
    public:
        static constexpr uint64_t magic = 0x3151455355315650ull;
        struct Entry {
            explicit Entry(std::unique_lock<std::mutex> held) : lock(std::move(held)) {}
            std::unique_lock<std::mutex> lock;
            std::array<uint64_t, 16> header{};
            VU1State before;
            std::array<uint8_t, PS2_VU1_CODE_SIZE> code;
            std::array<uint8_t, PS2_VU1_DATA_SIZE> data;
        };
        Vu1CommandTrace()
            : directory(std::getenv("PS2X_VU1_COMMANDS_DIR")),
              fromEe(setting("PS2X_VU1_COMMANDS_FROM", 0, UINT64_MAX)),
              maxSequences(setting("PS2X_VU1_COMMANDS_SEQUENCES", 32, 256)),
              maxCommands(setting("PS2X_VU1_COMMANDS_LIMIT", 1024, 4096))
        {
            static_assert(std::endian::native == std::endian::little);
            if (!maxSequences || !maxCommands) throw std::invalid_argument("VU1 trace limits must be positive");
            if (!std::filesystem::create_directory(directory))
                throw std::runtime_error("VU1 commands require a fresh output directory");
            manifest.exceptions(std::ios::badbit | std::ios::failbit);
            manifest.open(directory / "manifest.jsonl", std::ios::out | std::ios::binary);
            manifest.imbue(std::locale::classic());
            manifest << "{\"kind\":\"meta\",\"schema\":1,\"state_bytes\":" << sizeof(VU1State)
                     << ",\"from_ee\":" << fromEe << ",\"max_sequences\":" << maxSequences
                     << ",\"max_commands\":" << maxCommands << "}\n";
            manifest.flush();
        }
        std::unique_ptr<Entry> begin(const VU1Interpreter &vu1, PS2Memory &memory,
                                    PS2Vu1Command command, PS2Vu1RunControl control,
                                    uint32_t startPc, uint32_t top, uint32_t itop, uint32_t budget)
        {
            if (stopped.load(std::memory_order_relaxed) || control.eeVsync < fromEe) return {};
            std::unique_lock lock(mutex);
            if (stopped.load(std::memory_order_relaxed)) return {};
            if (command == PS2Vu1Command::Start)
            {
                if (sequences == maxSequences) { complete("sequence-limit"); return {}; }
                owner = &vu1;
                ownerMemory = &memory;
                ++sequences;
                commandInSequence = 0;
            }
            else if (owner != &vu1 || ownerMemory != &memory) return {};
            auto entry = std::make_unique<Entry>(std::move(lock));
            entry->header = {magic, 1, sequences - 1, commandInSequence++,
                             static_cast<uint64_t>(command), startPc, top, itop, budget,
                             control.fbrst, control.eeVsync, sizeof(VU1State), 0, 0,
                             PS2_VU1_CODE_SIZE, PS2_VU1_DATA_SIZE};
            entry->before = vu1.state();
            std::memcpy(entry->code.data(), memory.getVU1Code(), entry->code.size());
            std::memcpy(entry->data.data(), memory.getVU1Data(), entry->data.size());
            return entry;
        }
        void finish(Entry &entry, const VU1Interpreter &vu1, PS2Memory &memory)
        {
            // The entry holds the stream lock through execution: a diagnostic
            // capture owns one ordered stream; it is never a worker benchmark.
            entry.header[12] = g_vu1CommandGifHash;
            entry.header[13] = g_vu1CommandGifPackets;
            char name[48];
            std::snprintf(name, sizeof(name), "command-%08llu.bin", static_cast<unsigned long long>(commands));
            std::ofstream output;
            output.exceptions(std::ios::badbit | std::ios::failbit);
            output.open(directory / name, std::ios::out | std::ios::binary);
            const auto write = [&](const void *data, size_t bytes) {
                output.write(static_cast<const char *>(data), static_cast<std::streamsize>(bytes));
            };
            write(entry.header.data(), sizeof(entry.header));
            write(&entry.before, sizeof(entry.before));
            write(entry.code.data(), entry.code.size());
            write(entry.data.data(), entry.data.size());
            write(&vu1.state(), sizeof(VU1State));
            write(memory.getVU1Data(), PS2_VU1_DATA_SIZE);
            output.close();
            // Publish only fully closed files. An interrupted unlisted file
            // must not be mistaken for a completed command by the replayer.
            manifest << "{\"kind\":\"command\",\"file\":\"" << name << "\",\"index\":" << commands
                     << ",\"sequence\":" << entry.header[2] << ",\"command\":" << entry.header[3] << "}\n";
            ++commands;
            manifest.flush();
            if (commands == maxCommands) complete("command-prefix-limit");
        }
    private:
        static uint64_t setting(const char *name, uint64_t fallback, uint64_t maximum)
        {
            const char *text = std::getenv(name);
            if (!text) return fallback;
            uint64_t value = 0;
            const auto end = text + std::strlen(text);
            const auto result = std::from_chars(text, end, value);
            if (text == end || result.ec != std::errc{} || result.ptr != end || value > maximum)
                throw std::invalid_argument("invalid VU1 command trace setting");
            return value;
        }
        void complete(const char *reason)
        {
            manifest << "{\"kind\":\"complete\",\"commands\":" << commands << ",\"sequences\":" << sequences
                     << ",\"reason\":\"" << reason << "\"}\n";
            manifest.flush();
            stopped.store(true, std::memory_order_relaxed);
        }
        std::mutex mutex;
        std::filesystem::path directory;
        std::ofstream manifest;
        const uint64_t fromEe, maxSequences, maxCommands;
        std::atomic<bool> stopped{false};
        const VU1Interpreter *owner = nullptr;
        const PS2Memory *ownerMemory = nullptr;
        uint64_t sequences = 0, commands = 0, commandInSequence = 0;
    };
    struct Vu1PacketCaptureScope {
        const bool previous = g_vu1CommandGifCollect;
        explicit Vu1PacketCaptureScope(bool collect)
        {
            if (collect) {
                g_vu1CommandGifCollect = true;
                g_vu1CommandGifHash = 0xCBF29CE484222325ull;
                g_vu1CommandGifPackets = 0;
            }
        }
        ~Vu1PacketCaptureScope() { g_vu1CommandGifCollect = previous; }
    };
}
