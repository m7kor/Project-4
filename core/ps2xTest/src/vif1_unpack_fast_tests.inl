// Included inside the memory test registration function; no public header edits.
        tc.Run("VIF V4 format loops match generic memory across skips, wrap and NUM0", [](TestCase &t)
        {
            struct Restore { ~Restore() { ps2xVif1SetUnpackFastOverride(-1); } } restore;
            PS2Memory generic, fast;
            t.IsTrue(generic.initialize() && fast.initialize(), "memory initializes");
            const uint64_t entered = ps2xVif1UnpackFastCalls();
            uint32_t seed = 0x872134ABu;
            for (const uint32_t width : {0u, 1u})
                for (const uint32_t usn : {0u, 1u})
                    for (const uint32_t cycle : {0x0101u, 0x0103u, 0x0304u})
                        for (const uint32_t count : {1u, 3u, 255u, 256u})
                            for (const uint32_t address : {0u, 1018u, 1023u})
                            {
                                for (uint32_t byte = 0; byte < PS2_VU1_DATA_SIZE; ++byte)
                                    generic.getVU1Data()[byte] = fast.getVU1Data()[byte] = static_cast<uint8_t>(byte * 17u + count);
                                generic.vif1_regs.tops = fast.vif1_regs.tops = 1021u;
                                for (uint32_t lane = 0; lane < 4; ++lane)
                                {
                                    generic.vif1_regs.row[lane] = fast.vif1_regs.row[lane] = 0x12340000u + lane;
                                    generic.vif1_regs.col[lane] = fast.vif1_regs.col[lane] = 0x76540000u + lane;
                                }
                                std::vector<uint8_t> packet;
                                appendU32(packet, makeVifCmd(0x01u, 0u, static_cast<uint16_t>(cycle)));
                                appendU32(packet, makeVifCmd(0x05u, 0u, 0u));
                                appendU32(packet, makeVifCmd(static_cast<uint8_t>(0x6Cu | width),
                                            static_cast<uint8_t>(count), static_cast<uint16_t>(0x8000u | address | (usn << 14u))));
                                const uint32_t bytes = count * (width ? 8u : 16u);
                                for (uint32_t byte = 0; byte < bytes; ++byte)
                                {
                                    seed ^= seed << 13u; seed ^= seed >> 17u; seed ^= seed << 5u;
                                    packet.push_back(static_cast<uint8_t>(seed));
                                }
                                // The following command must still be decoded after the exact payload.
                                appendU32(packet, makeVifCmd(0x05u, 0u, 3u));
                                ps2xVif1SetUnpackFastOverride(0);
                                const uint64_t before = ps2xVif1UnpackFastCalls();
                                generic.processVIF1Data(packet.data(), static_cast<uint32_t>(packet.size()));
                                t.Equals(ps2xVif1UnpackFastCalls(), before, "generic is an actual reference");
                                ps2xVif1SetUnpackFastOverride(1);
                                fast.processVIF1Data(packet.data(), static_cast<uint32_t>(packet.size()));
                                t.Equals(ps2xVif1UnpackFastCalls(), before + 1u, "eligible command actually entered the format loop");
                                t.IsTrue(std::memcmp(generic.getVU1Data(), fast.getVU1Data(), PS2_VU1_DATA_SIZE) == 0,
                                         "all VU bytes, including skipped vectors and wrapped destinations, match");
                                t.Equals(fast.vif1_regs.mode, generic.vif1_regs.mode, "trailing command alignment matches");
                                t.Equals(fast.vif1_regs.mode, 3u, "trailing STMOD executes");
                                for (uint32_t lane = 0; lane < 4; ++lane)
                                {
                                    t.Equals(fast.vif1_regs.row[lane], generic.vif1_regs.row[lane], "ROW unchanged");
                                    t.Equals(fast.vif1_regs.col[lane], generic.vif1_regs.col[lane], "COL unchanged");
                                }
                            }
            t.IsTrue(ps2xVif1UnpackFastCalls() > entered, "fast format path was exercised");
        });

        tc.Run("VIF format loops preserve overlapping source and destination semantics", [](TestCase &t)
        {
            struct Restore { ~Restore() { ps2xVif1SetUnpackFastOverride(-1); } } restore;
            PS2Memory generic, fast;
            t.IsTrue(generic.initialize() && fast.initialize(), "memory initializes");
            std::vector<uint8_t> packet;
            appendU32(packet, makeVifCmd(0x6Cu, 3u, 257u));
            for (uint32_t word = 0; word < 12u; ++word)
                appendU32(packet, 0x81726354u + word);
            for (PS2Memory *mem : {&generic, &fast})
            {
                std::memset(mem->getVU1Data(), 0xCC, PS2_VU1_DATA_SIZE);
                mem->vif1_regs.mode = 0;
                mem->vif1_regs.cycle = 0x0101u;
                std::memcpy(mem->getVU1Data() + 0x1000u, packet.data(), packet.size());
            }
            const uint64_t before = ps2xVif1UnpackFastCalls();
            ps2xVif1SetUnpackFastOverride(0);
            generic.processVIF1Data(generic.getVU1Data() + 0x1000u, static_cast<uint32_t>(packet.size()));
            ps2xVif1SetUnpackFastOverride(1);
            fast.processVIF1Data(fast.getVU1Data() + 0x1000u, static_cast<uint32_t>(packet.size()));
            t.Equals(ps2xVif1UnpackFastCalls(), before, "aliasing source stays on ordered reference path");
            t.IsTrue(std::memcmp(generic.getVU1Data(), fast.getVU1Data(), PS2_VU1_DATA_SIZE) == 0,
                     "overlapping source observes the same preceding vector writes");
        });

        tc.Run("VIF fast selection preserves masks, ROW modes, fill and short payloads", [](TestCase &t)
        {
            struct Restore { ~Restore() { ps2xVif1SetUnpackFastOverride(-1); } } restore;
            PS2Memory generic, fast;
            t.IsTrue(generic.initialize() && fast.initialize(), "memory initializes");
            for (uint32_t mode = 0; mode < 4; ++mode)
                for (const bool masked : {false, true})
                    for (uint32_t format = 0; format < 16; ++format)
                        for (const uint32_t cycle : {0x0101u, 0x0403u})
                        {
                            for (PS2Memory *mem : {&generic, &fast})
                            {
                                std::memset(mem->getVU1Data(), 0xA6, PS2_VU1_DATA_SIZE);
                                for (uint32_t lane = 0; lane < 4; ++lane)
                                {
                                    mem->vif1_regs.row[lane] = 0xFFFFFFFCu + lane;
                                    mem->vif1_regs.col[lane] = 0x80u + lane;
                                }
                            }
                            const uint32_t vn = format >> 2u, vl = format & 3u;
                            const uint32_t cl = cycle & 0xFFu, wl = cycle >> 8u, count = 17u;
                            const uint32_t sourceCount = cl >= wl ? count : count / wl * cl + std::min(count % wl, cl);
                            const uint32_t stride = vl == 3u && vn == 3u ? 2u : (vn + 1u) * (vl == 0u ? 4u : vl == 2u ? 1u : 2u);
                            const uint32_t bytes = (sourceCount * stride + 3u) & ~3u;
                            std::vector<uint8_t> packet;
                            appendU32(packet, makeVifCmd(0x01u, 0u, static_cast<uint16_t>(cycle)));
                            appendU32(packet, makeVifCmd(0x05u, 0u, static_cast<uint16_t>(mode)));
                            appendU32(packet, makeVifCmd(0x20u, 0u, 0u));
                            appendU32(packet, 0x1BE4B14Eu);
                            appendU32(packet, makeVifCmd(static_cast<uint8_t>((masked ? 0x70u : 0x60u) | format), 17u, 1020u));
                            for (uint32_t byte = 0; byte < bytes; ++byte)
                                packet.push_back(static_cast<uint8_t>(byte * 193u + 137u));
                            const uint64_t before = ps2xVif1UnpackFastCalls();
                            ps2xVif1SetUnpackFastOverride(0);
                            generic.processVIF1Data(packet.data(), static_cast<uint32_t>(packet.size()));
                            ps2xVif1SetUnpackFastOverride(1);
                            fast.processVIF1Data(packet.data(), static_cast<uint32_t>(packet.size()));
                            const bool eligible = !masked && mode == 0 && cl >= wl && vn == 3 && vl < 2;
                            t.Equals(ps2xVif1UnpackFastCalls(), before + (eligible ? 1u : 0u), "fallback selection is exact");
                            t.IsTrue(std::memcmp(generic.getVU1Data(), fast.getVU1Data(), PS2_VU1_DATA_SIZE) == 0,
                                     "masked, fill and unsupported formats match reference");
                            for (uint32_t lane = 0; lane < 4; ++lane)
                                t.Equals(fast.vif1_regs.row[lane], generic.vif1_regs.row[lane], "ROW replacement/addition stays equivalent");
                        }
            std::memset(fast.getVU1Data(), 0x3D, PS2_VU1_DATA_SIZE);
            fast.vif1_regs.mode = 0;
            fast.vif1_regs.cycle = 0x0101u;
            std::vector<uint8_t> shortPacket;
            appendU32(shortPacket, makeVifCmd(0x6Cu, 2u, 0u));
            shortPacket.resize(4u + 31u, 0x99u);
            const uint64_t before = ps2xVif1UnpackFastCalls();
            fast.processVIF1Data(shortPacket.data(), static_cast<uint32_t>(shortPacket.size()));
            t.Equals(ps2xVif1UnpackFastCalls(), before, "incomplete payload never enters fast loop");
            t.IsTrue(std::all_of(fast.getVU1Data(), fast.getVU1Data() + PS2_VU1_DATA_SIZE,
                                [](uint8_t value) { return value == 0x3Du; }), "incomplete payload never reads or writes partial vectors");
        });
