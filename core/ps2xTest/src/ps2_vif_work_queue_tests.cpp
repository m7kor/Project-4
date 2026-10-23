#include "MiniTest.h"
#include "runtime/ps2_vif_work_queue.h"
#include "runtime/ps2_vu1_completion_mailbox.h"
#include "runtime/ps2_memory.h"
#include "runtime/ps2_vu1.h"
#include "runtime/gs/gs_frontend.h"
#include <cstring>
#include <array>
#include <chrono>
#include <thread>
#include <vector>
#include <atomic>
#include <future>
#include <stdexcept>

void register_ps2_vif_work_queue_tests()
{
    using Queue = PS2VifWorkQueue;
    using Mailbox = PS2Vu1CompletionMailbox;
    MiniTest::Case("VU completion return path", [](TestCase &tc) {
        tc.Run("real queued VIF and VU execution returns bounded ordered completions without worker EE access", [](TestCase &t) {
            PS2Memory memory;
            t.IsTrue(memory.initialize(), "initialize real VIF and VU memories");
            GS gs;
            gs.init(memory.getGSVRAM(), PS2_GS_VRAM_SIZE, &memory.gs());
            VU1Interpreter vu1;
            const uint32_t code[] = {0, 0x180002FFu, 0, 0x400002FFu};
            std::memcpy(memory.getVU1Code(), code, sizeof(code));
            Mailbox mailbox(2); // Force admission to consume results under pressure.
            Mailbox::Ticket activeTicket{};
            PS2Vu1RunControl activeControl{};
            std::vector<uint32_t> unpacked;
            const auto owner = std::this_thread::get_id();
            bool workerOnly = true;
            memory.setVu1MscalCallback([&](uint32_t pc, uint32_t top, uint32_t itop) {
                workerOnly &= std::this_thread::get_id() != owner;
                uint32_t word = 0;
                std::memcpy(&word, memory.getVU1Data() + 16, sizeof(word));
                unpacked.push_back(word);
                const auto before = vu1.state().cycles;
                const auto completion = executePS2Vu1Command(vu1, memory, gs, PS2Vu1Command::Start,
                    activeControl, pc, top, itop, 32);
                mailbox.publish(activeTicket, {completion, vu1.state().cycles - before, activeControl.eeVsync});
            });
            Queue queue([&](const auto &item) {
                std::memcpy(&activeTicket, item.bytes.data(), sizeof(activeTicket));
                activeControl = item.control;
                try {
                    memory.processVIF1Data(item.bytes.data() + sizeof(activeTicket),
                        static_cast<uint32_t>(item.bytes.size() - sizeof(activeTicket)));
                } catch (...) { mailbox.fail(activeTicket, std::current_exception()); throw; }
            }, 128, 2);
            uint64_t retired = 0, requestedIrqs = 0;
            uint32_t sharedStatus = 0x900000ABu;
            auto retire = [&](auto ticket, auto result) {
                t.IsTrue(std::this_thread::get_id() == owner, "only EE retires hardware effects");
                t.Equals(ticket.sequence, retired + 1, "completion order matches original commands");
                t.Equals(result.eeVsync, 1000 + retired, "captured field reaches matching result");
                const uint32_t expected = uint32_t(retired % 4) << 9;
                t.Equals(result.completion.statusBits, expected, "D/T match captured FBRST");
                t.Equals(result.executedCycles, uint64_t{expected ? 1u : 3u}, "real execution cycle delta is transported");
                sharedStatus = result.completion.mergeStatus(sharedStatus);
                t.Equals(sharedStatus, 0x900000ABu | expected, "current VU0 bits survive every ordered retirement");
                requestedIrqs += result.completion.requestsInterrupt();
                ++retired;
            };
            for (uint64_t command = 0; command < 60; ++command) {
                auto ticket = mailbox.reserve();
                while (!ticket) {
                    mailbox.retireReady(retire);
                    ticket = mailbox.reserve();
                    if (!ticket && !mailbox.waitForProgress(std::chrono::seconds(2)))
                        throw std::runtime_error("real VIF completion did not make progress");
                }
                const uint32_t packet[] = {0x6C010001u, uint32_t(command + 1), 0, 0, 0, 0x14000000u};
                std::array<uint8_t, sizeof(Mailbox::Ticket) + sizeof(packet)> bytes{};
                std::memcpy(bytes.data(), &*ticket, sizeof(*ticket));
                std::memcpy(bytes.data() + sizeof(*ticket), packet, sizeof(packet));
                try { queue.enqueue(Queue::Kind::Vif1, bytes.data(), bytes.size(),
                                    {uint32_t(command % 4) << 10, 1000 + command}); }
                catch (...) { mailbox.cancel(*ticket); throw; }
                bytes.fill(0xFF); // DMA source reuse must not affect owned VIF commands.
            }
            queue.drain();
            mailbox.retireReady(retire);
            t.Equals(retired, uint64_t{60}, "all real completions retire under bounded pressure");
            t.Equals(requestedIrqs, uint64_t{45}, "only enabled D/T stops request IRQ retirement");
            t.IsTrue(workerOnly, "VIF and VU execute only on the worker");
            t.Equals(unpacked.size(), size_t{60}, "all real UNPACK payloads were observed");
            for (size_t i = 0; i < unpacked.size(); ++i)
                t.Equals(unpacked[i], uint32_t(i + 1), "reused source bytes preserve each command's VU data");
        });
        tc.Run("bounded reservations retire on EE in order despite out-of-order publication", [](TestCase &t) {
            Mailbox mailbox(2);
            const auto first = *mailbox.reserve(), second = *mailbox.reserve();
            t.IsFalse(mailbox.reserve().has_value(), "pending work reserves every result slot");
            std::thread([&] { mailbox.publish(second, {{0x400u}, 22, 700}); }).join();
            size_t calls = 0;
            t.Equals(mailbox.retireReady([&](auto, auto) { ++calls; }), size_t{0}, "later results cannot overtake the first");
            std::thread([&] { mailbox.publish(first, {{0x200u}, 11, 699}); }).join();
            uint32_t status = 0x90ABu;
            const auto owner = std::this_thread::get_id();
            t.Equals(mailbox.retireReady([&](auto ticket, auto result) {
                t.IsTrue(std::this_thread::get_id() == owner, "retirement executes on EE");
                t.Equals(ticket.sequence, first.sequence + calls, "reservation order determines retirement");
                t.Equals(result.executedCycles, uint64_t{calls ? 22u : 11u}, "cycles travel with the matching result");
                status = result.completion.mergeStatus(status);
                t.Equals(status, calls ? 0x94ABu : 0x92ABu, "retirement preserves unrelated shared status bits");
                ++calls;
            }), size_t{2}, "both results retire once");
            t.IsTrue(mailbox.reserve().has_value(), "retirement releases bounded capacity");
            t.Equals(calls, size_t{2}, "no duplicate retirement");
        });
        tc.Run("reset rejects stale success and stale worker failure", [](TestCase &t) {
            Mailbox mailbox(1);
            const auto old = *mailbox.reserve();
            mailbox.invalidate();
            const auto fresh = *mailbox.reserve();
            bool rejected = false, failureRejected = false;
            std::thread([&] {
                rejected = !mailbox.publish(old, {{0x600u}, 10, 10});
                failureRejected = !mailbox.fail(old, std::make_exception_ptr(std::runtime_error("old generation")));
                mailbox.publish(fresh, {{0x400u}, 20, 20});
            }).join();
            t.IsTrue(rejected && failureRejected, "an old command cannot affect the new generation");
            t.Equals(mailbox.retireReady([&](auto ticket, auto result) {
                t.Equals(ticket.generation, fresh.generation, "only fresh result retires");
                t.Equals(result.executedCycles, uint64_t{20}, "fresh payload is preserved");
            }), size_t{1}, "one fresh retirement");
        });
        tc.Run("submission rollback and duplicate completion cannot issue extra events", [](TestCase &t) {
            Mailbox mailbox(2);
            const auto first = *mailbox.reserve(), cancelled = *mailbox.reserve();
            t.IsFalse(mailbox.cancel(first), "rollback cannot remove an older command");
            t.IsTrue(mailbox.cancel(cancelled), "failed last submission releases its reservation");
            bool cancelledRejected = false, duplicateRejected = false;
            std::thread([&] {
                cancelledRejected = !mailbox.publish(cancelled, {});
                mailbox.publish(first, {});
                try { mailbox.publish(first, {}); }
                catch (const std::logic_error &) { duplicateRejected = true; }
            }).join();
            t.IsTrue(cancelledRejected && duplicateRejected, "cancelled and duplicate results are rejected");
            size_t calls = 0;
            mailbox.retireReady([&](auto, auto) { ++calls; });
            bool retiredRejected = false;
            std::thread([&] { retiredRejected = !mailbox.publish(first, {}); }).join();
            t.IsTrue(retiredRejected, "already retired command cannot publish again");
            t.Equals(calls, size_t{1}, "single retirement event");
        });
        tc.Run("worker error wakes progress waits and is not treated as success", [](TestCase &t) {
            Mailbox mailbox(1);
            const auto ticket = *mailbox.reserve();
            std::thread([&] { mailbox.fail(ticket, std::make_exception_ptr(std::runtime_error("worker error"))); }).join();
            bool waitFailed = false, reserveFailed = false;
            try { mailbox.waitForProgress(std::chrono::milliseconds(10)); }
            catch (const std::runtime_error &) { waitFailed = true; }
            try { mailbox.reserve(); }
            catch (const std::runtime_error &) { reserveFailed = true; }
            t.IsTrue(waitFailed && reserveFailed, "failure propagates through both wait and publication admission");
        });
        tc.Run("failed retirement poisons its generation until explicit reset", [](TestCase &t) {
            Mailbox mailbox(1);
            const auto ticket = *mailbox.reserve();
            std::thread([&] { mailbox.publish(ticket, {}); }).join();
            bool retirementFailed = false, nextFailed = false;
            try { mailbox.retireReady([](auto, auto) { throw std::runtime_error("EE retirement error"); }); }
            catch (const std::runtime_error &) { retirementFailed = true; }
            try { mailbox.reserve(); }
            catch (const std::runtime_error &) { nextFailed = true; }
            t.IsTrue(retirementFailed && nextFailed, "failed event cannot be discarded and followed by successful work");
            mailbox.invalidate();
            t.IsTrue(mailbox.reserve().has_value(), "explicit new generation clears failed metadata");
        });
        tc.Run("owner roles and finite progress waits reject misuse", [](TestCase &t) {
            Mailbox mailbox(1);
            bool foreignRejected = false, eePublishRejected = false;
            std::thread([&] {
                try { mailbox.reserve(); }
                catch (const std::logic_error &) { foreignRejected = true; }
            }).join();
            const auto ticket = *mailbox.reserve();
            try { mailbox.publish(ticket, {}); }
            catch (const std::logic_error &) { eePublishRejected = true; }
            t.IsTrue(foreignRejected && eePublishRejected, "EE reserves and worker publishes");
            t.IsFalse(mailbox.waitForProgress(std::chrono::milliseconds(0)), "pending command is not completed by a timeout");
            std::thread([&] { mailbox.publish(ticket, {}); }).join();
            bool recursiveRejected = false;
            mailbox.retireReady([&](auto, auto) {
                try { mailbox.invalidate(); }
                catch (const std::logic_error &) { recursiveRejected = true; }
            });
            t.IsTrue(recursiveRejected, "retirement cannot invalidate its own live slot");
        });
    });
    MiniTest::Case("VIF worker transport", [](TestCase &tc) {
        tc.Run("worker execution uses captured FBRST without an EE context", [](TestCase &t) {
            PS2Memory memory;
            t.IsTrue(memory.initialize(), "memory should initialize");
            GS gs;
            gs.init(memory.getGSVRAM(), static_cast<uint32_t>(PS2_GS_VRAM_SIZE), &memory.gs());
            VU1Interpreter vu1;
            const uint32_t code[] = {0, 0x180002FFu, 0, 0x400002FFu, 0, 0x000002FFu};
            std::memcpy(memory.getVU1Code(), code, sizeof(code));
            std::vector<PS2Vu1Completion> results;
            std::vector<uint64_t> stamps, cycles;
            bool flagsMatch = true;
            std::promise<void> release;
            auto gate = release.get_future().share();
            Queue queue([&](const auto &item) {
                gate.wait();
                const auto before = vu1.state().cycles;
                results.push_back(executePS2Vu1Command(vu1, memory, gs, PS2Vu1Command::Start,
                    item.control, 0, 0, 0, 32,
                    [&](const VU1State &state, const PS2Vu1RunControl &control) {
                        stamps.push_back(control.eeVsync);
                        flagsMatch &= state.dBitEnabled == ((control.fbrst & 0x400u) != 0) &&
                                      state.tBitEnabled == ((control.fbrst & 0x800u) != 0);
                    }));
                cycles.push_back(vu1.state().cycles - before);
            });
            for (unsigned mask = 0; mask < 4; ++mask) {
                Queue::Control control{mask << 10, 700u + mask};
                queue.enqueue(Queue::Kind::Vif1, nullptr, 0, control);
                control = {}; // Later EE changes must not reach the published command.
            }
            release.set_value();
            queue.drain();
            t.Equals(results.size(), size_t{4}, "four distinct captured controls must execute");
            if (results.size() != 4) return;
            for (unsigned mask = 0; mask < 4; ++mask) {
                t.Equals(results[mask].statusBits, mask << 9, "D/T completion must follow captured enable bits");
                t.Equals(stamps[mask], uint64_t{700u + mask}, "snapshot timestamp must be captured with control");
                t.Equals(cycles[mask], uint64_t{mask ? 1u : 3u}, "enabled D/T must stop at the marked instruction");
            }
            t.IsTrue(flagsMatch, "snapshot observer must see captured VU1 enables");
        });
        tc.Run("queued start and resume retire D then T then clear their stop bits", [](TestCase &t) {
            PS2Memory memory;
            t.IsTrue(memory.initialize(), "memory should initialize");
            GS gs;
            gs.init(memory.getGSVRAM(), static_cast<uint32_t>(PS2_GS_VRAM_SIZE), &memory.gs());
            VU1Interpreter vu1;
            const uint32_t code[] = {0, 0x100002FFu, 0, 0x080002FFu, 0, 0x400002FFu, 0, 0x000002FFu};
            std::memcpy(memory.getVU1Code(), code, sizeof(code));
            std::vector<PS2Vu1Completion> results;
            std::vector<uint32_t> pcs;
            unsigned startsObserved = 0;
            Queue queue([&](const auto &item) {
                const auto command = item.sequence == 1 ? PS2Vu1Command::Start : PS2Vu1Command::Continue;
                results.push_back(executePS2Vu1Command(vu1, memory, gs, command, item.control, 0, 12, 34, 32,
                    [&](const auto &, const auto &) { ++startsObserved; }));
                pcs.push_back(vu1.state().pc);
            });
            queue.enqueue(Queue::Kind::Vif1, nullptr, 0, {0x400u, 1});
            queue.enqueue(Queue::Kind::Vif1, nullptr, 0, {0x800u, 2});
            queue.enqueue(Queue::Kind::Vif1, nullptr, 0, {0, 3});
            queue.drain();
            t.Equals(results.size(), size_t{3}, "all execution completions must retire");
            if (results.size() != 3) return;
            t.Equals(results[0].statusBits, 0x200u, "first start stops at D");
            t.Equals(results[1].statusBits, 0x400u, "resume captures a different enable and stops at T");
            t.Equals(results[2].statusBits, 0u, "final resume clears the previous stop reason");
            t.Equals(pcs[0], 8u, "D preserves next TPC");
            t.Equals(pcs[1], 16u, "T preserves next TPC");
            t.Equals(pcs[2], 32u, "E executes its delay slot after resume");
            t.Equals(startsObserved, 1u, "MSCNT must not create a new MSCAL snapshot");
            t.Equals(vu1.state().top, 12u, "TOP must reach execution");
            t.Equals(vu1.state().itop, 34u, "ITOP must reach execution");
            const uint32_t retirementStatus = 0xDEADBEEFu;
            for (const auto &result : results)
                t.Equals(result.mergeStatus(retirementStatus),
                         (retirementStatus & ~0x600u) | result.statusBits,
                         "completion must preserve unrelated EE/VU0 bits at retirement");
        });
        tc.Run("invalid VU1 execution command cannot change control or state", [](TestCase &t) {
            PS2Memory memory;
            t.IsTrue(memory.initialize(), "memory should initialize");
            GS gs;
            VU1Interpreter vu1;
            vu1.state().dBitEnabled = true;
            vu1.state().pc = 24;
            bool rejected = false;
            try { executePS2Vu1Command(vu1, memory, gs, static_cast<PS2Vu1Command>(99), {}, 0, 0, 0); }
            catch (const std::invalid_argument &) { rejected = true; }
            t.IsTrue(rejected, "invalid command must be rejected before execution");
            t.IsTrue(vu1.state().dBitEnabled, "invalid command must not apply captured control");
            t.Equals(vu1.state().pc, 24u, "invalid command must not advance TPC");
        });
        tc.Run("queued UNPACK and MSCAL consume distinct owned DMA payloads", [](TestCase &t) {
            PS2Memory memory;
            t.IsTrue(memory.initialize(), "memory should initialize");
            std::vector<uint32_t> samples, starts;
            memory.setVu1MscalCallback([&](uint32_t pc, uint32_t, uint32_t) {
                uint32_t value = 0;
                std::memcpy(&value, memory.getVU1Data() + 16, sizeof(value));
                samples.push_back(value);
                starts.push_back(pc);
            });
            std::promise<void> release;
            auto gate = release.get_future().share();
            Queue queue([&](const auto &item) {
                gate.wait();
                memory.processVIF1Data(item.bytes.data(), static_cast<uint32_t>(item.bytes.size()));
            }, 64, 2);
            uint32_t packet[] = {0x6C010001u, 0x3F800000u, 0, 0, 0, 0x14000000u};
            queue.enqueue(Queue::Kind::Vif1, reinterpret_cast<uint8_t *>(packet), sizeof(packet), {});
            packet[1] = 0x40000000u;
            packet[5] = 0x14000001u;
            queue.enqueue(Queue::Kind::Vif1, reinterpret_cast<uint8_t *>(packet), sizeof(packet), {});
            packet[1] = 0x40400000u; // EE reuses the same source before either command executes.
            release.set_value();
            queue.drain();
            t.Equals(samples.size(), size_t{2}, "both MSCAL commands should execute");
            if (samples.size() != 2 || starts.size() != 2) return;
            t.Equals(samples[0], 0x3F800000u, "first MSCAL must see its original UNPACK");
            t.Equals(samples[1], 0x40000000u, "second MSCAL must see its own newer UNPACK");
            t.Equals(starts[0], 0u, "first MSCAL start address must be preserved");
            t.Equals(starts[1], 8u, "second MSCAL start address must be preserved");
        });
        tc.Run("payload and control are copied before DMA source reuse", [](TestCase &t) {
            std::promise<void> release;
            auto gate = release.get_future().share();
            std::vector<Queue::Item> seen;
            Queue queue([&](const auto &item) { gate.wait(); seen.push_back(item); });
            uint8_t data[] = {1, 2, 3, 4};
            Queue::Control control{0xC00u, 6130};
            queue.enqueue(Queue::Kind::Vif1, data, sizeof(data), control);
            data[0] = 99;
            control.fbrst = 0;
            queue.enqueue(Queue::Kind::Gif, data, sizeof(data), control, 3, false, true);
            release.set_value();
            queue.drain();
            t.Equals(seen.size(), size_t{2}, "both commands should finish");
            if (seen.size() != 2) return;
            t.Equals(seen[0].bytes[0], uint8_t{1}, "VIF payload must own its original bytes");
            t.Equals(seen[0].control.fbrst, 0xC00u, "FBRST must be captured at publication");
            t.Equals(seen[0].control.eeVsync, uint64_t{6130}, "EE timestamp must be captured");
            t.Equals(seen[1].bytes[0], uint8_t{99}, "next command must capture the newer bytes");
            t.Equals(seen[1].pathId, 3u, "GIF path identity must be preserved");
            t.IsTrue(!seen[1].drainImmediately && seen[1].directHl, "GIF flags must be preserved");
        });
        tc.Run("bounded pressure preserves command sequence and stop drains", [](TestCase &t) {
            std::vector<uint64_t> sequences;
            Queue queue([&](const auto &item) { sequences.push_back(item.sequence); }, 8, 2);
            uint8_t data[4]{};
            for (unsigned i = 0; i < 2000; ++i)
                queue.enqueue(i % 2 ? Queue::Kind::Gif : Queue::Kind::Vif1,
                              data, sizeof(data), {}, i % 2 ? 2 : 0);
            queue.stop();
            t.Equals(sequences.size(), size_t{2000}, "stop must finish all accepted work");
            bool ordered = true;
            for (size_t i = 0; i < sequences.size(); ++i) ordered &= sequences[i] == i + 1;
            t.IsTrue(ordered, "VIF/GIF commands must retire in publication order under pressure");
            bool rejected = false;
            try { queue.enqueue(Queue::Kind::ArbiterDrain, nullptr, 0, {}); }
            catch (const std::logic_error &) { rejected = true; }
            t.IsTrue(rejected, "closed queue must reject publication");
        });
        tc.Run("host teardown can join a queue published by another owner", [](TestCase &t) {
            unsigned completed = 0;
            Queue queue([&](const auto &) { ++completed; });
            for (unsigned i = 0; i < 100; ++i)
                queue.enqueue(Queue::Kind::ArbiterDrain, nullptr, 0, {});
            auto stopped = std::async(std::launch::async, [&] { queue.stop(); });
            stopped.get();
            t.Equals(completed, 100u, "foreign host teardown must drain accepted EE work");
            queue.stop(); // Idempotent after another thread has already joined.
        });
        tc.Run("worker drain recursion cannot wait for itself", [](TestCase &t) {
            Queue *active = nullptr;
            bool wasWorker = false;
            Queue queue([&](const auto &) { wasWorker = active->onWorker(); active->drain(); });
            active = &queue;
            queue.enqueue(Queue::Kind::ArbiterDrain, nullptr, 0, {});
            queue.drain();
            t.IsTrue(wasWorker, "consumer must run on the worker");
            t.IsTrue(!queue.onWorker(), "owner must not be mistaken for worker");
        });
        tc.Run("consumer failure wakes drain and rejects subsequent work", [](TestCase &t) {
            std::promise<void> release;
            auto gate = release.get_future().share();
            unsigned calls = 0;
            Queue queue([&](const auto &) { ++calls; gate.wait(); throw std::runtime_error("VIF execution failed"); });
            queue.enqueue(Queue::Kind::ArbiterDrain, nullptr, 0, {});
            queue.enqueue(Queue::Kind::ArbiterDrain, nullptr, 0, {});
            release.set_value();
            bool drainFailed = false, enqueueFailed = false;
            try { queue.drain(); } catch (const std::runtime_error &) { drainFailed = true; }
            try { queue.enqueue(Queue::Kind::ArbiterDrain, nullptr, 0, {}); }
            catch (const std::runtime_error &) { enqueueFailed = true; }
            queue.stop();
            t.IsTrue(drainFailed && enqueueFailed, "execution errors must not become apparent success");
            t.Equals(calls, 1u, "work after a failed hardware command must not execute");
        });
        tc.Run("invalid payload paths and foreign producers are rejected", [](TestCase &t) {
            Queue queue([](const auto &) {}, 4, 2);
            uint8_t data[5]{};
            unsigned rejected = 0;
            try { queue.enqueue(Queue::Kind::Vif1, nullptr, 1, {}); }
            catch (const std::invalid_argument &) { ++rejected; }
            try { queue.enqueue(Queue::Kind::Vif1, data, sizeof(data), {}); }
            catch (const std::invalid_argument &) { ++rejected; }
            try { queue.enqueue(Queue::Kind::Gif, data, 4, {}, 4); }
            catch (const std::invalid_argument &) { ++rejected; }
            auto foreign = std::async(std::launch::async, [&] {
                try { queue.enqueue(Queue::Kind::ArbiterDrain, nullptr, 0, {}); }
                catch (const std::logic_error &) { return true; }
                return false;
            });
            t.Equals(rejected, 3u, "invalid inputs must fail before publication");
            t.IsTrue(foreign.get(), "only the EE owner may publish");
            queue.drain();
        });
    });
}
