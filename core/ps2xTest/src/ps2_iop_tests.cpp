#include "MiniTest.h"
#include <chrono>
#include <filesystem>
#include <fstream>
#include "ps2x/iop/ps2_path.h"
#include "../../ps2xIOP/tests/iop_compat_test_support.h"
#include "../../ps2xIOP/src/emulator/core/iop_kernel.h"
#include "../../ps2xIOP/src/emulator/core/iop_memory.h"
#include "../../ps2xIOP/src/emulator/core/iop_memory_card.h"
#include "../../ps2xIOP/src/emulator/core/iop_secrman.h"
#include "../../ps2xIOP/src/emulator/core/iop_pad.h"
#include "../../ps2xIOP/src/emulator/core/iop_sio2.h"
#include "../../ps2xIOP/src/emulator/imports/iop_cdvd.h"
#include "../../ps2xIOP/src/emulator/imports/iop_dmacman.h"
#include "../../ps2xIOP/src/emulator/imports/iop_intrman.h"
#include "../../ps2xIOP/src/emulator/imports/iop_vblank.h"
#include "../../ps2xIOP/src/emulator/iop_emulator_const.h"
#include "../../ps2xIOP/src/emulator/services/iop_rpc.h"
#include "../../ps2xIOP/src/emulator/iop_emulator.h"
#include "../../ps2xIOP/src/emulator/imports/iop_sysclib.h"

void register_ps2_iop_tests()
{
    MiniTest::Case("PS2IopSubsystem", [](TestCase &tc)
    {
        tc.Run("IOP RAM blocks preserve load delays, aliased jumps and self-modifying instructions across slices", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            using State = IopEmulator::GuestCallState;
            for (uint32_t budget : {1u, 100u})
            {
                iop_test::Host host;
                IopEmulator emulator(host);
                iop_test::Irx image(0x10000, 0x1000);
                image.words(0, {0x03e00008, 0x24020000});
                // Load, consume after one delay slot, patch a future
                // instruction, then jump to it through a cached RAM alias.
                image.words(0x100, {0x8c880000, 0x24090003, 0x01095021, 0xacaa0000,
                    0x3c0b2402, 0x356b002a, 0xaccb0000, 0x00c00008, 0x240c0007});
                image.words(0x140, {0x24020001, 0xacac0004, 0x03e00008, 0});
                image.install(host);
                t.IsTrue(emulator.loadModuleBuffer(0x1000, nullptr, 0).moduleId > 0, "load guest code");
                uint32_t input = 100;
                t.IsTrue(emulator.writeMemory(0x18000, &input, sizeof(input)), "supply RAM input");
                auto call = emulator.beginGuestCall(0x80010100, 0xa0018000, 0x80018010,
                    0x80010140, 0, 0, budget);
                uint64_t usedInstructions = call.instructions;
                unsigned slices = 0;
                while (call.state == State::Pending && slices++ < 40u)
                {
                    call = emulator.resumeGuestCall(call.token, budget);
                    usedInstructions += call.instructions;
                }
                t.IsTrue(call.state == State::Returned, "guest returns without a stale code cache");
                t.Equals(call.result, 42u, "new instruction executes after the guest patch");
                t.Equals(usedInstructions, 13ull, "batching and slicing preserve instruction count");
                uint32_t result[2]{};
                t.IsTrue(emulator.readMemory(0x18010, result, sizeof(result)), "read outputs");
                t.Equals(result[0], 103u, "load delay and RAM alias preserve arithmetic input");
                t.Equals(result[1], 7u, "jump delay slot executes before the target");
            }
        });
        tc.Run("IOP consecutive LWL LWR pairs merge both byte orders and preserve final load delay", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            for (uint32_t offset = 1; offset <= 3; ++offset)
            for (bool reversed : {false, true})
            for (bool residentWord : {false, true})
            {
                IopMemory memory; IopCpuCore core(memory); IopCpuState cpu;
                auto step = [&] { return residentWord ? core.executeInstruction(cpu, memory.read32(cpu.pc))
                                                     : core.executeInstruction(cpu); };
                const uint8_t bytes[] = {0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88};
                memory.writeRam(0x18000, bytes, sizeof(bytes));
                const uint32_t left = (0x22u << 26) | (4u << 21) | (8u << 16) | (offset + 3);
                const uint32_t right = (0x26u << 26) | (4u << 21) | (8u << 16) | offset;
                const uint32_t program[] = {reversed ? right : left, reversed ? left : right,
                                           (8u << 21) | (9u << 11) | 0x21u, 0}; // addu r9,r8,r0; nop
                memory.writeRam(0x10000, program, sizeof(program));
                cpu.pc = 0x10000; cpu.gpr[4] = 0x18000; cpu.gpr[8] = 0xdeadbeef;
                t.IsTrue(step(), "first partial load");
                const uint32_t partial = cpu.pendingLoadValue;
                t.IsTrue(step(), "second partial load");
                t.IsTrue(step(), "normal instruction in final load delay");
                uint32_t expected = 0;
                for (uint32_t i = 0; i < 4; ++i) expected |= uint32_t(bytes[offset + i]) << (8 * i);
                t.Equals(cpu.gpr[8], expected, "both halves reconstruct the original unaligned word");
                t.Equals(cpu.gpr[9], partial, "normal instruction cannot consume the final pending load early");
            }
        });
        tc.Run("resumable IOP calls exceed the old budget without losing registers or leased stacks", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            using State = IopEmulator::GuestCallState;
            iop_test::Host host; IopEmulator emulator(host);
            iop_test::Irx image(0x10000,0x1000);
            image.words(0,{0x03e00008,0x24020000});
            image.words(0x100,{0x27bdfff0,0xafbf000c,0xafa60008,0x00804021,0x00004821,
                0x25290001,0x2508ffff,0x1500fffd,0,
                0x8faa0008,0,0xaca90000,0xacaa0004,0x01270019,0x00001012,
                0x8fbf000c,0x03e00008,0x27bd0010});
            image.install(host);
            t.IsTrue(emulator.loadModuleBuffer(0x1000,nullptr,0).moduleId>0,"load real guest loop");
            auto longCall=emulator.beginGuestCall(0x10100,600000,0x18000,0x12345678,3,0,2000000);
            t.IsTrue(longCall.state==State::Pending,"budget boundary cannot complete a long operation");
            t.Equals(longCall.instructions,2000000u,"exact first slice");
            t.Equals(longCall.result,0u,"no partial result published");
            uint32_t output[2]{};
            emulator.readMemory(0x18000,output,sizeof(output));
            t.Equals(output[0],0u,"guest final store has not executed");
            // A second guest keeps its own stack and HI/LO state, including a
            // slice boundary immediately after MULTU.
            auto shortCall=emulator.beginGuestCall(0x10100,1,0x18010,0xaabbccdd,7,0,14);
            t.IsTrue(shortCall.state==State::Pending,"second call suspended after multiply");
            while(shortCall.state==State::Pending)
                shortCall=emulator.resumeGuestCall(shortCall.token,1);
            t.IsTrue(shortCall.state==State::Returned,"second call returns only at sentinel");
            t.Equals(shortCall.result,7u,"HI/LO survive one-instruction slices");
            // A legacy synchronous call also writes its stack. It must not
            // overwrite the marker saved by the suspended long call.
            iop_test::Irx callback(0x11000,0x1000);
            callback.words(0,{0x27bdfff0,0x3c08dead,0x3508beef,0xafa80008,
                0x24020000,0x03e00008,0x27bd0010});
            callback.install(host);
            t.IsTrue(emulator.loadModuleBuffer(0x1000,nullptr,0).moduleId>0,"interleaved synchronous guest executes");
            for(unsigned i=0;i<200 && longCall.state==State::Pending;++i)
                longCall=emulator.resumeGuestCall(longCall.token,4093);
            t.IsTrue(longCall.state==State::Returned,"original operation completes across budgets");
            t.Equals(longCall.result,1800000u,"original loop registers retained");
            emulator.readMemory(0x18000,output,sizeof(output));
            t.Equals(output[0],600000u,"all iterations executed exactly once");
            t.Equals(output[1],0x12345678u,"exclusive saved stack survived both other callers");
            t.IsTrue(emulator.resumeGuestCall(longCall.token,10).state==State::Rejected,"completed token cannot replay stores");
        });
        tc.Run("resumable IOP call cancellation reset and stack exhaustion preserve ownership", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            using State=IopEmulator::GuestCallState;
            iop_test::Host host; IopEmulator emulator(host);
            const uint32_t loop[]={0x1000ffff,0};
            emulator.writeMemory(0x10000,loop,sizeof(loop));
            t.IsTrue(emulator.beginGuestCall(0x10001,0,0,0,0,0,1).state==State::Rejected,"unaligned entry rejected");
            t.IsTrue(emulator.beginGuestCall(0x20010000,0,0,0,0,0,1).state==State::Rejected,"non-RAM alias rejected");
            t.IsTrue(emulator.beginGuestCall(0x10000,0,0,0,0,0,0).state==State::Rejected,"zero-budget start cannot allocate a call");
            std::vector<uint64_t> tokens;
            for(unsigned i=0;i<32;++i)
            {
                auto call=emulator.beginGuestCall(0x10000,0,0,0,0,0,1);
                if(call.state==State::Rejected)break;
                t.IsTrue(call.state==State::Pending,"infinite guest remains pending in bounded slice");
                tokens.push_back(call.token);
            }
            t.IsTrue(!tokens.empty() && tokens.size()<32,"finite stack capacity rejects overload");
            const auto old=tokens.front();
            t.IsTrue(emulator.resumeGuestCall(old,0).state==State::Rejected,"invalid resume leaves call untouched");
            t.IsTrue(emulator.resumeGuestCall(old,1).state==State::Pending,"branch delay state resumes after rejected request");
            t.IsTrue(emulator.cancelGuestCall(old),"cancel releases its stack");
            t.IsFalse(emulator.cancelGuestCall(old),"cancel cannot affect a replacement lease");
            auto replacement=emulator.beginGuestCall(0x10000,0,0,0,0,0,1);
            t.IsTrue(replacement.state==State::Pending && replacement.token>tokens.back(),"new call reuses space with fresh identity");
            emulator.reset();
            t.IsTrue(emulator.resumeGuestCall(replacement.token,1).state==State::Rejected,"reset invalidates old CPU states");
            emulator.writeMemory(0x10000,loop,sizeof(loop));
            auto fresh=emulator.beginGuestCall(0x10000,0,0,0,0,0,1);
            t.IsTrue(fresh.state==State::Pending && fresh.token>replacement.token,"reset cannot alias a stale token");
            t.IsTrue(emulator.cancelGuestCall(fresh.token),"fresh call remains independently cancellable");
            const uint32_t invalid=0xffffffffu;
            emulator.writeMemory(0x10010,&invalid,sizeof(invalid));
            auto fault=emulator.beginGuestCall(0x10010,0,0,0,0,0,1);
            t.IsTrue(fault.state==State::Faulted,"CPU exception is not a pending successful operation");
            t.IsTrue(emulator.resumeGuestCall(fault.token,1).state==State::Rejected,"fault releases the old context");
            auto afterFault=emulator.beginGuestCall(0x10000,0,0,0,0,0,1);
            t.IsTrue(afterFault.state==State::Pending,"fault releases its stack lease");
            t.IsTrue(emulator.cancelGuestCall(afterFault.token),"clean up replacement after fault");
        });
        tc.Run("VBlank callbacks preserve priority, interrupt context, masking and lifetime", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            IopMemory memory; IopKernel kernel(memory); IopIntrman intrman(memory); IopVblank blank(kernel,intrman);
            struct Executor : IopGuestExecutor
            {
                IopIntrman &intrman; IopVblank &blank;
                std::vector<uint32_t> calls, arguments, gps;
                bool context=true, rejected=true, complete=true, throwing=false;
                Executor(IopIntrman &i,IopVblank &b):intrman(i),blank(b){}
                bool lastGuestCallCompleted() const noexcept override { return complete; }
                uint32_t executeGuestFunction(uint32_t f,uint32_t arg,uint32_t,uint32_t,uint32_t,uint32_t gp) override
                {
                    calls.push_back(f); arguments.push_back(arg); gps.push_back(gp);
                    context &= intrman.inInterruptContext();
                    IopCpuState cpu{}; cpu.gpr[5]=f;
                    rejected &= blank.dispatchImport(9,cpu,0) && cpu.gpr[2]==uint32_t(-100);
                    if(throwing) throw std::runtime_error("test interrupt unwind");
                    return f==0x1100 ? 0 : 1;
                }
            } executor(intrman,blank);
            IopCpuState cpu{};
            const auto reg=[&](unsigned phase,uint32_t f,int priority) {
                cpu.gpr[4]=phase;cpu.gpr[5]=uint32_t(priority);cpu.gpr[6]=f;cpu.gpr[7]=f+4;cpu.gpr[28]=f+8;
                t.IsTrue(blank.dispatchImport(8,cpu,0),"registration import handled");return cpu.gpr[2];
            };
            t.Equals(reg(0,0x1000,30),0u,"register lower priority");
            t.Equals(reg(0,0x1100,10),0u,"register one-shot high priority");
            t.Equals(reg(0,0x1200,30),0u,"register equal priority");
            t.Equals(reg(1,0x1300,16),0u,"register end handler");
            t.Equals(reg(0,0x1000,0),uint32_t(-104),"reject duplicate in same phase");
            memory.setInterruptControl(0);
            blank.serviceDue(kVblankPeriodCycles,executor);
            t.IsTrue(executor.calls.empty(),"no callback in global disabled section");
            memory.setInterruptControl(1);
            blank.serviceDue(kVblankPeriodCycles,executor);
            t.IsTrue(executor.calls==std::vector<uint32_t>({0x1300,0x1100,0x1000,0x1200}),"pending phases retain chronological order; priority stable");
            t.IsTrue(executor.context && executor.rejected && !intrman.inInterruptContext(),"ISR context and forbidden registration unwind correctly");
            for(size_t i=0;i<executor.calls.size();++i) {
                t.Equals(executor.arguments[i],executor.calls[i]+4,"original userdata");
                t.Equals(executor.gps[i],executor.calls[i]+8,"original GP");
            }
            executor.calls.clear(); blank.serviceDue(kVblankPeriodCycles,executor);
            t.IsTrue(executor.calls.empty(),"same edge never duplicated");
            cpu.gpr[4]=0;cpu.gpr[5]=0; intrman.dispatchImport(7,cpu,executor);
            blank.serviceDue(2*kVblankPeriodCycles,executor);
            t.IsTrue(executor.calls==std::vector<uint32_t>({0x1300}),"only start line masked");
            executor.calls.clear(); intrman.dispatchImport(6,cpu,executor);
            blank.serviceDue(2*kVblankPeriodCycles,executor);
            t.IsTrue(executor.calls==std::vector<uint32_t>({0x1000,0x1200}),"re-enabled start delivered; zero-return handler removed");
            executor.calls.clear();executor.complete=false;
            // An incomplete zero return cannot unregister a handler.
            t.Equals(reg(0,0x1100,10),0u,"re-register removed handler");
            blank.serviceDue(3*kVblankPeriodCycles,executor);
            executor.calls.clear();executor.complete=true;
            blank.serviceDue(4*kVblankPeriodCycles,executor);
            t.IsTrue(std::find(executor.calls.begin(),executor.calls.end(),0x1100)!=executor.calls.end(),"incomplete callback retained");
            executor.throwing=true;
            try { blank.serviceDue(5*kVblankPeriodCycles,executor); } catch(const std::runtime_error &) {}
            t.IsFalse(intrman.inInterruptContext(),"exception clears ISR context");
            executor.throwing=false; executor.calls.clear();
            blank.serviceDue(6*kVblankPeriodCycles,executor);
            t.IsFalse(executor.calls.empty(),"exception clears service recursion guard");
            blank.reset();executor.calls.clear();blank.serviceDue(7*kVblankPeriodCycles,executor);
            t.IsTrue(executor.calls.empty(),"reset clears handlers and pending phases");
            for(unsigned i=0;i<14;++i) t.Equals(reg(0,0x2000+i*4,16),0u,"available ROM callback record");
            t.Equals(reg(1,0x3000,16),uint32_t(-400),"finite ROM callback capacity");
            cpu.gpr[4]=1;cpu.gpr[5]=0x3000;blank.dispatchImport(9,cpu,0);
            t.Equals(cpu.gpr[2],uint32_t(-105),"missing release reports error");
            cpu.gpr[4]=0;cpu.gpr[5]=0x2000;blank.dispatchImport(9,cpu,0);
            t.Equals(cpu.gpr[2],0u,"release frees record");
            t.Equals(reg(1,0x3000,16),0u,"freed record reused");
        });
        tc.Run("Original-style IRX VBlank handler runs from idle scheduler in ISR context", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            iop_test::Host host; iop_test::Irx image(0x10000,0x1000);
            image.words(0, {0x27bdffe0,0xafbf001c,
                0x24040000,0x24050010,0x3c060001,0x34c60180,0x3c070001,0x34e70400,
                0x0c004085,0, // native vblank ordinal 8 import
                0x8fbf001c,0x27bd0020,0x03e00008,0x00001021});
            image.words(0x180,{0x27bdfff0,0xafbf000c,0xafa40008,
                0x0c0040a5,0, // QueryIntrContext through native import
                0x8fa40008,0,0xac820004,
                0x8c820000,0,0x24420001,0xac820000,
                0x8fbf000c,0x27bd0010,0x03e00008,0x24020001});
            image.words(0x200,{0x41e00000,0,0x101,0x616c6276,0x00006b6e,0x03e00008,0x24000008,0,0});
            image.words(0x280,{0x41e00000,0,0x101,0x72746e69,0x006e616d,0x03e00008,0x24000017,0,0});
            image.install(host); IopEmulator emulator(host);
            t.IsTrue(emulator.loadModuleBuffer(0x1000,nullptr,0).moduleId>0,"register real guest callback");
            emulator.runEeCycles(kVblankPeriodCycles*8+1000);
            uint32_t observed[2]{};
            t.IsTrue(emulator.readMemory(0x10400,observed,sizeof(observed)),"read guest-observed callbacks");
            t.Equals(observed[0],1u,"idle scheduler wakes exactly at first field");
            t.Equals(observed[1],1u,"native QueryIntrContext sees ISR");
            emulator.runEeCycles(kVblankPeriodCycles*8);
            emulator.readMemory(0x10400,observed,sizeof(observed));
            t.Equals(observed[0],2u,"recurring field delivered again");
        });
        tc.Run("DualShock2 serial negotiation preserves modes, buttons, axes and pressure order", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            IopPad pad; ps2x::iop::IopHost::PadInput input;
            const auto send = [&](std::initializer_list<uint8_t> bytes) {
                const std::vector<uint8_t> packet(bytes); return pad.exchange(packet,input);
            };
            t.IsTrue(send({1,0x42,0,0,0}) == std::vector<uint8_t>({0xff,0x41,0x5a,0xff,0xff}), "initial digital device ID and released buttons");
            for (unsigned bit = 0; bit < 16; ++bit)
            {
                input.buttons = uint16_t(~(1u << bit));
                const auto data = send({1,0x42,0,0,0});
                t.Equals(uint16_t(data[3] | (uint16_t(data[4]) << 8)), input.buttons, "all PS2 button bits preserve active-low order");
            }
            input.buttons = 0xffff;
            send({1,0x43,0,1,0,0,0,0,0});
            t.IsTrue(send({1,0x45,0,0,0,0,0,0,0}) == std::vector<uint8_t>({0xff,0xf3,0x5a,3,2,0,2,1,0}), "configuration query identifies a standard DualShock2");
            t.IsTrue(send({1,0x46,0,0,0,0,0,0,0}) == std::vector<uint8_t>({0xff,0xf3,0x5a,0,0,1,2,0,0x0a}), "mode zero actuator descriptor");
            t.IsTrue(send({1,0x46,0,1,0,0,0,0,0}) == std::vector<uint8_t>({0xff,0xf3,0x5a,0,0,1,1,1,0x14}), "mode one actuator descriptor");
            send({1,0x44,0,1,3,0,0,0,0});
            t.IsTrue(send({1,0x41,0,0,0,0,0,0,0}) == std::vector<uint8_t>({0xff,0xf3,0x5a,0xff,0xff,3,0,0,0x5a}), "button mask query after analog selection");
            send({1,0x43,0,0,0,0,0,0,0});
            input.buttons = uint16_t(~0x4008u); input.rx=0; input.ry=255; input.lx=17; input.ly=234;
            t.IsTrue(send({1,0x42,0,0,0,0,0,0,0}) == std::vector<uint8_t>({0xff,0x73,0x5a,0xf7,0xbf,0,255,17,234}), "analog report carries host Cross/Start and independent axes");
            send({1,0x43,0,1,0,0,0,0,0});
            send({1,0x4f,0,0xff,0xff,3,0,0,0});
            send({1,0x4d,0,0,1,0xff,0xff,0xff,0xff});
            send({1,0x43,0,0,0,0,0,0,0});
            for (size_t i=0;i<input.pressure.size();++i) input.pressure[i]=uint8_t(i+1);
            std::vector<uint8_t> request(21,0); request[0]=1; request[1]=0x42; request[3]=3; request[4]=173;
            const auto report = pad.exchange(request,input);
            t.Equals(report[1],uint8_t(0x79), "pressure mode ID survives configuration exit");
            for (size_t i=0;i<input.pressure.size();++i) t.Equals(report[9+i],input.pressure[i], "DS2 pressure byte ordering");
            t.Equals(pad.smallMotor(),uint8_t(1), "small motor uses mapped input LSB");
            t.Equals(pad.largeMotor(),uint8_t(173), "large motor preserves full intensity");
            const std::vector<uint8_t> malformed{1,0x44};
            t.IsTrue(pad.exchange(malformed,input)==std::vector<uint8_t>(2,0xff), "incomplete header is rejected");
            t.Equals(pad.mode(),uint8_t(0x79), "malformed command cannot change negotiated mode");
            pad.reset(); t.Equals(pad.mode(),uint8_t(0x41), "hardware reset restores digital mode");
        });
        tc.Run("SIO2 pad responses use the host sample and preserve independent port negotiation", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            IopSio2 bus; ps2x::iop::IopHost::PadInput input; input.buttons=uint16_t(~0x4010u);
            bool present = true; unsigned samples = 0;
            bus.setPadSampler([&](int port,int slot,ps2x::iop::IopHost::PadInput &out) {
                ++samples; out=input; return present && port==0 && slot==0;
            });
            const auto transaction = [&](uint32_t descriptor,std::initializer_list<uint8_t> bytes) {
                bus.write(0x1f808200,descriptor); bus.write(0x1f808204,0);
                for (auto byte:bytes) bus.input(byte);
                std::vector<uint8_t> result; while(bus.available()) result.push_back(bus.output()); return result;
            };
            t.IsTrue(transaction(0x500,{1,0x42,0,0,0})==std::vector<uint8_t>({0xff,0x41,0x5a,0xef,0xbf}), "actual sample appears on serial wire");
            t.Equals(bus.read(0x1f80826c),0x1100u,"sampled pad connected status");
            t.IsTrue(transaction(0x501,{1,0x42,0,0,0})==std::vector<uint8_t>(5,0xff),"unattached second port stays absent");
            transaction(0x900,{1,0x43,0,1,0,0,0,0,0}); transaction(0x900,{1,0x44,0,1,3,0,0,0,0});
            transaction(0x900,{1,0x43,0,0,0,0,0,0,0});
            t.Equals(transaction(0x900,{1,0x42,0,0,0,0,0,0,0})[1],uint8_t(0x73),"mode persists across command queue resets");
            present=false;
            t.IsTrue(transaction(0x900,{1,0x42,0,0,0,0,0,0,0})==std::vector<uint8_t>(9,0xff),"host disconnect is reflected immediately");
            bus.reset(); present=true;
            t.Equals(transaction(0x500,{1,0x42,0,0,0})[1],uint8_t(0x41),"full reset clears negotiation but retains sampler");
            t.IsTrue(samples >= 8,"each packet refreshes host input");
        });
        tc.Run("SECRMAN authentication validates a complete card and MechaCon exchange", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            const auto path = std::filesystem::temp_directory_path() /
                ("ps2x-secrman-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()) + ".ps2");
            struct Cleanup { std::filesystem::path path; ~Cleanup() { std::error_code ec; std::filesystem::remove(path, ec); } } cleanup{path};
            IopMemoryCard card; t.IsTrue(card.open(path), "create independent card");
            IopMechaAuth mecha;
            std::vector<uint16_t> transcript;
            int step = 0, failAt = -1;
            const IopSecrman::Transfer transfer = [&](int port, int slot, std::span<const uint8_t> input,
                std::vector<uint8_t> &output, uint32_t &status) {
                transcript.push_back(uint16_t(input[1]) << 8 | input[2]);
                if (++step == failAt || port != 2 || slot != 0) return false;
                output = card.exchange(input); status = 0x1100; return true;
            };
            const IopSecrman::Mecha device = [&](uint8_t command, std::span<const uint8_t> input,
                std::vector<uint8_t> &output) {
                transcript.push_back(command);
                if (++step == failAt) return false;
                return mecha.exchange(command, input, output);
            };
            t.IsTrue(IopSecrman::authenticate(2,0,0,transfer,device), "authentication passes real protocol replies");
            const std::vector<uint16_t> expected{0xf300,0x80,0xf701,0xf000,0x81,0xf001,0xf002,0x82,
                0xf003,0xf004,0x83,0xf005,0x8f,0x84,0x85,0xf006,0xf007,0xf008,0xf009,0xf00a,
                0xf00b,0xf00c,0xf00d,0xf00e,0xf00f,0xf010,0xf011,0x86,0xf012,0xf013,0x87,0x8f,0xf014,0x88};
            t.IsTrue(transcript == expected, "full PS2SDK card/device ordering");
            const int exchanges = step;
            for (int failure = 1; failure <= exchanges; ++failure)
            {
                card.reset(); mecha.reset(); step = 0; failAt = failure; transcript.clear();
                t.IsTrue(!IopSecrman::authenticate(2,0,0,transfer,device), "any failed exchange rejects authentication");
                t.IsTrue(transcript.size() >= 2 && transcript[transcript.size()-2] == 0xf300
                    && transcript.back() == 0x80, "failed session resets card and MechaCon");
            }
            failAt = -1; mecha.reset(); card.reset();
            const IopSecrman::Transfer corrupted = [&](int p, int s, std::span<const uint8_t> input,
                std::vector<uint8_t> &output, uint32_t &status) {
                if (!transfer(p,s,input,output,status)) return false;
                if (input[1] == 0xf0 && input[2] == 1) output[12] ^= 1;
                return true;
            };
            t.IsTrue(!IopSecrman::authenticate(2,0,0,corrupted,device), "bad challenge checksum is rejected");
            t.IsTrue(!IopSecrman::authenticate(2,0,0,{},device), "missing registered transport cannot succeed");
            std::vector<uint8_t> output;
            mecha.reset();
            t.IsTrue(!mecha.exchange(0x84,{},output), "challenge cannot be read before authentication setup");
            const std::array<uint8_t,1> id{0};
            t.IsTrue(mecha.exchange(0x80,id,output), "reset accepts device number");
            t.IsTrue(!mecha.exchange(0x82,{},output), "invalid command length/order rejected");
        });
        tc.Run("SIO2 DMA retains both completions and transfers command bytes with block padding", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            const auto path = std::filesystem::temp_directory_path() /
                ("ps2x-sio2-dma-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()) + ".ps2");
            struct Cleanup { std::filesystem::path path; ~Cleanup() { std::error_code ec; std::filesystem::remove(path, ec); } } cleanup{path};
            IopMemory memory;
            t.IsTrue(memory.enableNativeSio2(path), "raw card attached on port zero");
            memory.write32(0x1f808200, 0x140572); // native reset-auth descriptor: five bytes
            memory.write32(0x1f808204, 0);
            std::vector<uint8_t> packet(256, 0xcc);
            packet[0] = 0x81; packet[1] = 0xf3; packet[2] = packet[3] = packet[4] = 0;
            memory.writeRam(0x10000, packet.data(), packet.size());
            memory.write8(0x11000 - 1, 0xa5); memory.write8(0x11100, 0x5a);
            memory.write32(0x1f801550, 0x11000); memory.write32(0x1f801554, 0x10040);
            memory.write32(0x1f801558, 0x41000200); // receive waits for the response
            t.Equals(memory.read32(0x1f801558), 0x41000200u, "receive stays busy until bytes exist");
            t.IsTrue(!memory.takeDmaStart().has_value(), "no premature DMA completion");
            memory.write32(0x1f801540, 0x10000); memory.write32(0x1f801544, 0x10040);
            memory.write32(0x1f801548, 0x01000201);
            t.Equals(memory.read32(0x1f80826c), 0x1100u, "actual card reset reports connected device");
            const auto first = memory.takeDmaStart(), second = memory.takeDmaStart();
            t.IsTrue(first && second && first->irq == 0x2b && second->irq == 0x2c, "both DMA completions retained");
            t.Equals(memory.read32(0x1f801540), 0x10100u, "send MADR advances full DMA block");
            t.Equals(memory.read32(0x1f801550), 0x11100u, "receive MADR advances full DMA block");
            t.Equals(memory.read32(0x1f801548), 0x201u, "send start bit cleared");
            t.Equals(memory.read32(0x1f801558), 0x40000200u, "receive start bit cleared");
            std::vector<uint8_t> actual(256); memory.readRam(0x11000, actual.data(), actual.size());
            std::vector<uint8_t> expected(256, 0); expected[3] = 0x2b; expected[4] = 0x55;
            t.IsTrue(actual == expected, "protocol handles five bytes; DMA padding does not become another command");
            t.Equals(memory.read8(0x10fff), uint8_t(0xa5), "before-output guard preserved");
            t.Equals(memory.read8(0x11100), uint8_t(0x5a), "after-output guard preserved");
            memory.write32(0x1f808268, 1);
            auto irq = memory.takeDmaStart(); t.IsTrue(irq && irq->irq == 17, "SIO2 start schedules native interrupt");
            memory.write32(0x1f808268, 1);
            t.IsTrue(!memory.takeDmaStart(), "unacknowledged SIO2 interrupt not duplicated");
            memory.write8(0x1f808280, 1);
            t.Equals(memory.read32(0x1f808280), 0u, "SIO2 ISTAT uses write-one-to-clear");
            memory.write32(0x1f808268, 1);
            irq = memory.takeDmaStart(); t.IsTrue(irq && irq->irq == 17, "ack permits the next SIO2 interrupt");
            memory.write32(0x1f808200, 0x00000500);
            for (const uint8_t byte : {0x81,0xf3,0,0,0}) memory.write8(0x1f808260, byte);
            const std::vector<uint8_t> pioExpected{0,0,0,0x2b,0x55};
            for (const auto byte : pioExpected) t.Equals(memory.read8(0x1f808264), byte, "PIO FIFO returns one byte per read");
            t.Equals(memory.read8(0x1f808264), uint8_t(0xff), "FIFO empty response");
            memory.write32(0x1f808200, 0x00000501); // second port has no attached card
            for (const uint8_t byte : {0x81,0xf3,0,0,0}) memory.write8(0x1f808260, byte);
            t.Equals(memory.read32(0x1f80826c), 0x1d100u, "second card is absent");
            for (int i = 0; i < 5; ++i) t.Equals(memory.read8(0x1f808264), uint8_t(0xff), "missing card never acknowledges");
        });
        tc.Run("SIO2 card response clocks exceed input and retain full DMA replies", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            const auto path = std::filesystem::temp_directory_path() /
                ("ps2x-sio2-asymmetric-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()) + ".ps2");
            struct Cleanup { std::filesystem::path path; ~Cleanup() { std::error_code ec; std::filesystem::remove(path, ec); } } cleanup{path};
            IopSio2 sio; t.IsTrue(sio.openCard(path), "separate erased test card");
            sio.reset();
            // Exact original MCMAN finish descriptor and its three sent bytes.
            sio.write(0x1f808200u, 0x100370u);
            for (uint8_t byte : {0x81, 0x12, 0}) sio.input(byte);
            t.Equals(sio.available(), size_t{4}, "four response clocks from three input bytes");
            for (uint8_t byte : {0, 0, 0x2B, 0x55}) t.Equals(sio.output(), byte, "original finish marker received");
            t.Equals(sio.output(), uint8_t{0xFF}, "FIFO exhausted at actual response boundary");
            sio.write(0x1f808268u, 0xCu);
            sio.write(0x1f808200u, (7u << 8u) | (9u << 18u));
            for (uint8_t byte : {0x81,0x23,0,0,0,0,0}) sio.input(byte);
            t.Equals(sio.available(), size_t{9}, "sector request does not need its reply clock bytes as payload");
            for (int i=0; i<9; ++i) (void)sio.output();
            sio.write(0x1f808268u, 0xCu);
            sio.write(0x1f808200u, (3u << 8u) | (134u << 18u));
            for (int i=0; i<16; ++i) sio.input(i==0 ? 0x81 : i==1 ? 0x43 : i==2 ? 128 : 0, 16u);
            t.Equals(sio.available(), size_t{144}, "full 134-byte read response aligned to DMA block size");
            for (int i=0; i<144; ++i)
            {
                const uint8_t expected = i==3 ? 0x2B : i>=4 && i<132 ? 0xFF : i==133 ? 0x55 : 0;
                t.Equals(sio.output(), expected, "payload, checksum, terminator and DMA padding retained");
            }
            t.Equals(sio.available(), size_t{0}, "complete DMA response drained");
        });
        tc.Run("Native card NAND programming requires erase and survives reopen", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            const auto path = std::filesystem::temp_directory_path() /
                ("ps2x-card-nand-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()) + ".ps2");
            struct Cleanup { std::filesystem::path path; ~Cleanup() { std::error_code ec; std::filesystem::remove(path, ec); } } cleanup{path};
            IopMemoryCard card;
            t.IsTrue(card.open(path), "create isolated test card");
            const auto select = [](IopMemoryCard &device, uint8_t command, uint8_t page) {
                const std::vector<uint8_t> packet{0x81, command, page, 0, 0, 0, page, 0, 0};
                return device.exchange(packet);
            };
            const auto write = [](IopMemoryCard &device, uint8_t page, uint8_t value) {
                const std::vector<uint8_t> packet{0x81, 0x22, page, 0, 0, 0, page, 0, 0};
                device.exchange(packet);
                const std::vector<uint8_t> data{0x81, 0x42, 4, value, value, value, value, 0, 0, 0};
                return device.exchange(data);
            };
            const auto read = [&](IopMemoryCard &device, uint8_t page, uint8_t expected) {
                select(device, 0x23, page);
                const std::vector<uint8_t> packet{0x81, 0x43, 4, 0, 0, 0, 0, 0, 0, 0};
                const auto reply = device.exchange(packet);
                t.IsTrue(reply == std::vector<uint8_t>({0, 0, 0, 0x2b, expected, expected, expected, expected, 0, 0x55}),
                         "raw card read matches the programmed NAND bits");
            };
            write(card, 16, 0x55);
            write(card, 16, 0xFF); // programming cannot restore zero bits
            read(card, 16, 0x55);
            write(card, 16, 0xAA); // complementary bits clear the remaining ones
            read(card, 16, 0x00);
            write(card, 32, 0xA5);
            IopMemoryCard reopened;
            t.IsTrue(reopened.open(path), "programmed bits persist on disk");
            read(reopened, 16, 0x00);
            select(reopened, 0x21, 19); // erase the block containing page 16
            const std::vector<uint8_t> erase{0x81, 0x82, 0, 0};
            t.IsTrue(reopened.exchange(erase) == std::vector<uint8_t>({0, 0, 0x2b, 0x55}), "erase acknowledges persistence");
            read(reopened, 16, 0xFF);
            read(reopened, 32, 0xA5);
            write(reopened, 16, 0xAA);
            IopMemoryCard finalCard;
            t.IsTrue(finalCard.open(path), "erased and reprogrammed card reopens");
            read(finalCard, 16, 0xAA);
            read(finalCard, 32, 0xA5);
        });
        tc.Run("Native card protocol persists sectors and rejects malformed transfers", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            const auto path = std::filesystem::temp_directory_path() /
                ("ps2x-card-protocol-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()) + ".ps2");
            struct Cleanup { std::filesystem::path path; ~Cleanup() { std::error_code ec; std::filesystem::remove(path, ec); } } cleanup{path};
            IopMemoryCard card;
            t.IsTrue(card.open(path), "create separate raw card");
            t.Equals(std::filesystem::file_size(path), uintmax_t(IopMemoryCard::ImageBytes), "ECC-inclusive 8MB geometry");
            const auto send = [&](std::initializer_list<uint8_t> bytes) {
                const std::vector<uint8_t> packet(bytes); return card.exchange(packet);
            };
            t.IsTrue(send({0x81,0xf3,0,0,0}) == std::vector<uint8_t>({0,0,0,0x2b,0x55}), "F3 reset response includes fifth byte");
            t.IsTrue(send({0x81,0xf3,0,0}) == std::vector<uint8_t>({0,0,0,0x2b,0x55}), "reset response can exceed input clocks");
            auto specs = send({0x81,0x26,0,0,0,0,0,0,0,0,0,0,0});
            t.IsTrue(specs == std::vector<uint8_t>({0,0,0x2b,0,2,0x10,0,0,0x40,0,0,0x52,0x55}), "sector size, erase size, capacity and XOR");
            send({0x81,0x23,0,0,0,0,0,0,0});
            auto blank = send({0x81,0x43,4,0,0,0,0,0,0,0});
            t.IsTrue(blank == std::vector<uint8_t>({0,0,0,0x2b,0xff,0xff,0xff,0xff,0,0x55}), "new card is unformatted FF, not a fabricated filesystem");
            send({0x81,0x22,16,0,0,0,16,0,0});
            auto wrote = send({0x81,0x42,4,1,2,3,7,0,0,0});
            t.Equals(wrote[8], uint8_t(7), "write checksum covers actual payload");
            IopMemoryCard reopened;
            t.IsTrue(reopened.open(path), "reopen persisted card without resizing");
            const std::vector<uint8_t> select{0x81,0x23,16,0,0,0,16,0,0};
            reopened.exchange(select);
            const std::vector<uint8_t> read{0x81,0x43,4,0,0,0,0,0,0,0};
            t.IsTrue(reopened.exchange(read) == std::vector<uint8_t>({0,0,0,0x2b,1,2,3,7,7,0x55}), "saved bytes survive restart");
            send({0x81,0x22,16,0,0,0,0,0,0});
            t.IsTrue(send({0x81,0x42,4,9,9,9,9,0,0,0}) == std::vector<uint8_t>(10,0xff), "bad sector XOR blocks writes");
            send({0x81,0x22,0,0x40,0,0,0x40,0,0});
            t.IsTrue(send({0x81,0x42,4,9,9,9,9,0,0,0}) == std::vector<uint8_t>(10,0xff), "sector beyond capacity cannot wrap");
            send({0x81,0x22,0,0,0,0,0,0,0});
            t.IsTrue(send({0x81,0x42,255,1}) == std::vector<uint8_t>(4,0xff), "truncated write has no side effects");
            send({0x81,0x42,4,8,8,8,8,0,0,0});
            send({0x81,0x21,3,0,0,0,3,0,0});
            send({0x81,0x82,0,0});
            send({0x81,0x23,0,0,0,0,0,0,0});
            t.IsTrue(send({0x81,0x43,4,0,0,0,0,0,0,0}) == blank, "erase aligns to 16-sector block");
            send({0x81,0x23,16,0,0,0,16,0,0});
            t.IsTrue(send({0x81,0x43,4,0,0,0,0,0,0,0}) == std::vector<uint8_t>({0,0,0,0x2b,1,2,3,7,7,0x55}), "neighboring block preserved");
            send({0x81,0x27,0x5a,0,0});
            t.IsTrue(send({0x81,0x28,0,0,0}) == std::vector<uint8_t>({0,0,0x2b,0x5a,0x5a}), "both terminator positions support old and new MCMAN");
            auto auth = send({0x81,0xf0,1,1,2,3,4,5,6,7,8,0,0,0});
            t.Equals(auth[12], uint8_t(8), "auth XOR matches eight challenge bytes");
            // Existing incompatible files are refused intact, not converted or truncated.
            { std::ofstream file(path, std::ios::binary | std::ios::trunc); file << "sentinel"; }
            t.IsTrue(!reopened.open(path), "wrong-size card rejected");
            t.Equals(std::filesystem::file_size(path), uintmax_t(8), "rejection preserves existing bytes");
        });
        tc.Run("IOP sysclib character masks allow original numeric option parsing", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            iop_test::Host host;
            iop_test::Irx image(0x10000u, 0x1000u);
            image.words(0u, {
                0x27BDFFE0u, 0xAFBF001Cu, 0x24040030u,
                0x0C004085u, 0u, 0x30420004u,
                0x10400008u, 0x24030001u,
                0x3C040001u, 0x34840440u, 0x00002821u,
                0x2406000Au, 0x0C004087u, 0u, 0x00401821u,
                0x3C080001u, 0x35080400u, 0xAD030000u,
                0x8FBF001Cu, 0x27BD0020u, 0x03E00008u, 0x00001021u});
            image.words(0x200u, {0x41E00000u, 0u, 0x104u, 0x63737973u, 0x0062696Cu,
                0x03E00008u, 0x24000008u, 0x03E00008u, 0x24000024u, 0u, 0u});
            image.words(0x440u, {0x00000030u});
            image.install(host);
            IopEmulator emulator(host);
            t.IsTrue(emulator.loadModuleBuffer(0x1000u, nullptr, 0u).moduleId > 0, "IRX parser executes");
            uint32_t flag = 1u;
            t.IsTrue(emulator.readMemory(0x10400u, &flag, sizeof(flag)), "read parsed flag");
            t.Equals(flag, 0u, "sdinit=0 numeric option replaces default one");
            IopMemory memory;
            IopSysclib sysclib(memory);
            const std::array<std::pair<uint32_t,uint32_t>, 12> masks{{
                {0,0x20}, {9,8}, {13,8}, {32,0x18}, {'0',4}, {'9',4},
                {'A',0x41}, {'F',0x41}, {'G',1}, {'a',0x42}, {'z',2}, {127,0x20}}};
            for (const auto &[character, expected] : masks)
            {
                IopCpuState cpu{}; cpu.gpr[4] = character;
                t.IsTrue(sysclib.dispatchImport(8u,cpu), "look_ctype_table handled");
                t.Equals(cpu.gpr[2], expected, "PS2SDK ASCII masks preserved");
            }
        });
        tc.Run("Direct IRX loads pass argc and a terminated argv array", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            for (const bool buffer : {false, true})
            for (const bool packed : {false, true})
            {
                iop_test::Host host;
                iop_test::Irx image(0x10000u, 0x1000u);
                // Copy the entry arguments while their storage is still live.
                // Do not dereference malformed argv on the old implementation.
                image.words(0u, {
                    0x3C080001u, 0x35080400u, 0xAD040000u,
                    0x24090001u, 0x10890003u, 0u,
                    0x24090003u, 0x14890014u, 0u,
                    0x8CA90000u, 0u, 0x912A0000u, 0u, 0xAD0A0004u,
                    0x00044880u, 0x00A94821u, 0x8D2A0000u, 0u, 0xAD0A0008u,
                    0x24090001u, 0x10890007u, 0u,
                    0x8CA90004u, 0x8CAB0008u, 0x912A0000u, 0x916C0000u,
                    0xAD0A000Cu, 0xAD0C0010u,
                    0x03E00008u, 0x24020002u});
                host.file = image.bytes;
                image.install(host);
                IopEmulator emulator(host);
                const char arguments[] = {'a', 'b', 0, 'c', 0};
                const auto loaded = buffer
                    ? emulator.loadModuleBuffer(0x1000u, packed ? arguments : nullptr, packed ? sizeof(arguments) : 0u)
                    : emulator.loadModule("host:test.irx", packed ? arguments : nullptr, packed ? sizeof(arguments) : 0u);
                t.IsTrue(loaded.moduleId > 0, "module executes successfully");
                t.Equals(loaded.startResult, 2, "entry result preserved");
                uint32_t evidence[5]{};
                t.IsTrue(emulator.readMemory(0x10400u, evidence, sizeof(evidence)), "read copied entry arguments");
                t.Equals(evidence[0], packed ? 3u : 1u, "argc includes name and packed strings, not byte length");
                t.Equals(evidence[1], buffer ? uint32_t{'b'} : uint32_t{'h'}, "argv[0] contains the loader name");
                t.Equals(evidence[2], 0u, "argv[argc] is null");
                if (packed)
                {
                    t.Equals(evidence[3], uint32_t{'a'}, "first argument reached entry");
                    t.Equals(evidence[4], uint32_t{'c'}, "second argument reached entry");
                }
            }
        });
        tc.Run("IOP priority queues preserve execution across host slices and rotate explicitly", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            IopMemory memory;
            IopKernel kernel(memory);
            IopCpuState caller{};
            const auto create = [&](uint32_t priority) {
                memory.write32(0x2008u, 0x10000u);
                memory.write32(0x200Cu, 0x400u);
                memory.write32(0x2010u, priority);
                caller.gpr[4] = 0x2000u;
                t.IsTrue(kernel.dispatchThreadImport(4u, caller, 0u), "create thread");
                const int id = static_cast<int>(caller.gpr[2]);
                caller.gpr[4] = static_cast<uint32_t>(id);
                t.IsTrue(kernel.dispatchThreadImport(6u, caller, 0u), "start thread");
                return id;
            };
            const int first = create(39u), second = create(39u);
            auto *thread = kernel.beginNextReady(0u);
            t.IsTrue(thread && thread->id == first, "first ready thread starts");
            if (!thread) return;
            kernel.sleepCurrent(thread->cpu);
            kernel.endTimeslice(*thread, 0x1FFFFF00u);
            thread = kernel.beginNextReady(1u);
            t.IsTrue(thread && thread->id == second, "second runs while first sleeps");
            if (!thread) return;
            thread->cpu.gpr[4] = static_cast<uint32_t>(first);
            t.IsTrue(kernel.dispatchThreadImport(25u, thread->cpu, 1u), "wake equal priority peer");
            for (uint64_t tick = 2u; tick < 5u; ++tick)
            {
                kernel.endTimeslice(*thread, 0x1FFFFF00u);
                thread = kernel.beginNextReady(tick);
                t.IsTrue(thread && thread->id == second, "host budget does not rotate equal priorities");
                if (!thread) return;
            }
            const int high = create(20u);
            kernel.endTimeslice(*thread, 0x1FFFFF00u);
            thread = kernel.beginNextReady(5u);
            t.IsTrue(thread && thread->id == high, "higher priority still preempts");
            if (!thread) return;
            kernel.sleepCurrent(thread->cpu);
            kernel.endTimeslice(*thread, 0x1FFFFF00u);
            thread = kernel.beginNextReady(6u);
            t.IsTrue(thread && thread->id == second, "preempted thread resumes before its peer");
            if (!thread) return;
            thread->cpu.gpr[4] = 39u;
            t.IsTrue(kernel.dispatchThreadImport(16u, thread->cpu, 6u), "explicit rotate");
            kernel.endTimeslice(*thread, 0x1FFFFF00u);
            thread = kernel.beginNextReady(7u);
            t.IsTrue(thread && thread->id == first, "rotation runs waiting peer");
            if (!thread) return;
            thread->cpu.gpr[4] = 0u;
            t.IsTrue(kernel.dispatchThreadImport(16u, thread->cpu, 7u), "rotate current priority");
            kernel.endTimeslice(*thread, 0x1FFFFF00u);
            thread = kernel.beginNextReady(8u);
            t.IsTrue(thread && thread->id == second, "rotation does not prefer lower thread ID");
            if (!thread) return;
            thread->cpu.gpr[4] = static_cast<uint32_t>(high);
            t.IsTrue(kernel.dispatchThreadImport(25u, thread->cpu, 8u), "wake higher priority thread");
            kernel.endTimeslice(*thread, 0x1FFFFF00u);
            thread = kernel.beginNextReady(9u);
            t.IsTrue(thread && thread->id == high, "higher priority resumes");
            if (!thread) return;
            thread->cpu.gpr[4] = 39u;
            t.IsTrue(kernel.dispatchThreadImport(16u, thread->cpu, 9u), "rotate another priority queue");
            t.IsTrue(!thread->cpu.yielded, "foreign rotation does not yield current thread");
            kernel.sleepCurrent(thread->cpu);
            kernel.endTimeslice(*thread, 0x1FFFFF00u);
            thread = kernel.beginNextReady(10u);
            t.IsTrue(thread && thread->id == first, "foreign rotation moved the queue head to the back");
            if (!thread) return;
            memory.setInterruptControl(0u);
            thread->cpu.gpr[4] = 39u;
            t.IsTrue(kernel.dispatchThreadImport(16u, thread->cpu, 10u), "rotate with interrupts suspended");
            kernel.endTimeslice(*thread, 0x1FFFFF00u);
            thread = kernel.beginNextReady(11u);
            t.IsTrue(thread && thread->id == second, "explicit rotation remains a dispatch point while masked");
        });
        tc.Run("IOP thread switches preserve each thread's interrupt control", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            IopMemory memory;
            IopKernel kernel(memory);
            IopCpuState caller{};
            auto create = [&](uint32_t priority) {
                memory.write32(0x2008u, 0x10000u);
                memory.write32(0x200Cu, 0x400u);
                memory.write32(0x2010u, priority);
                caller.gpr[4] = 0x2000u;
                t.IsTrue(kernel.dispatchThreadImport(4u, caller, 0u), "CreateThread handled");
                const int id = static_cast<int>(caller.gpr[2]);
                caller.gpr[4] = static_cast<uint32_t>(id);
                t.IsTrue(kernel.dispatchThreadImport(6u, caller, 0u), "StartThread handled");
                return id;
            };
            const int first = create(16u), second = create(32u);
            auto *a = kernel.beginNextReady(0u);
            t.IsTrue(a && a->id == first, "higher-priority first thread selected");
            if (!a) return;
            memory.setInterruptControl(0u);
            kernel.sleepCurrent(a->cpu);
            kernel.endTimeslice(*a, 0x1FFFFF00u);
            auto *b = kernel.beginNextReady(1u);
            t.IsTrue(b && b->id == second, "second thread runs while first sleeps");
            if (!b) return;
            t.Equals(memory.interruptControl(), 1u, "new thread does not inherit another thread's disable");
            memory.setInterruptControl(1u);
            b->cpu.gpr[4] = static_cast<uint32_t>(first);
            t.IsTrue(kernel.dispatchThreadImport(25u, b->cpu, 1u), "WakeupThread handled");
            kernel.endTimeslice(*b, 0x1FFFFF00u);
            a = kernel.beginNextReady(2u);
            t.IsTrue(a && a->id == first, "first thread resumes after wakeup");
            if (!a) return;
            t.Equals(memory.interruptControl(), 0u, "resumed thread retains its own disabled state");
            memory.setInterruptControl(1u);
            kernel.sleepCurrent(a->cpu);
            kernel.endTimeslice(*a, 0x1FFFFF00u);
            b = kernel.beginNextReady(3u);
            t.IsTrue(b && b->id == second, "second thread resumes");
            t.Equals(memory.interruptControl(), 1u, "second thread's enabled state survives switching");
            if (!b) return;
            memory.setInterruptControl(0u);
            kernel.sleepCurrent(b->cpu);
            kernel.endTimeslice(*b, 0x1FFFFF00u);
            t.IsTrue(kernel.beginNextReady(4u) == nullptr, "both threads are sleeping");
            t.Equals(memory.interruptControl(), 1u, "idle context permits interrupt-driven wakeup");
            caller.gpr[4] = static_cast<uint32_t>(second);
            t.IsTrue(kernel.dispatchThreadImport(25u, caller, 4u), "wake second thread from idle");
            b = kernel.beginNextReady(5u);
            t.IsTrue(b && b->id == second, "second thread resumes from idle");
            t.Equals(memory.interruptControl(), 0u, "idle does not discard the blocked thread's disabled state");
        });

        tc.Run("IOP thread with suspended interrupts is not preempted at slice end", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            IopMemory memory;
            IopKernel kernel(memory);
            IopCpuState caller{};
            auto create = [&](uint32_t priority) {
                memory.write32(0x2008u, 0x10000u);
                memory.write32(0x200Cu, 0x400u);
                memory.write32(0x2010u, priority);
                caller.gpr[4] = 0x2000u;
                t.IsTrue(kernel.dispatchThreadImport(4u, caller, 0u), "CreateThread handled");
                const int id = static_cast<int>(caller.gpr[2]);
                caller.gpr[4] = static_cast<uint32_t>(id);
                t.IsTrue(kernel.dispatchThreadImport(6u, caller, 0u), "StartThread handled");
                return id;
            };
            const int high = create(16u), low = create(32u);
            auto *h = kernel.beginNextReady(0u);
            t.IsTrue(h && h->id == high, "high-priority thread runs first");
            if (!h) return;
            kernel.sleepCurrent(h->cpu);
            kernel.endTimeslice(*h, 0x1FFFFF00u);
            auto *l = kernel.beginNextReady(1u);
            t.IsTrue(l && l->id == low, "low-priority thread runs while high sleeps");
            if (!l) return;
            memory.setInterruptControl(0u); // CpuSuspendIntr inside a critical section
            kernel.endTimeslice(*l, 0x1FFFFF00u);
            caller.gpr[4] = static_cast<uint32_t>(high);
            t.IsTrue(kernel.dispatchThreadImport(25u, caller, 2u), "external wakeup of the high thread");
            auto *again = kernel.beginNextReady(3u);
            t.IsTrue(again && again->id == low, "external wakeup does not preempt a suspended-interrupt section");
            if (!again) return;
            t.Equals(memory.interruptControl(), 0u, "critical section keeps interrupts suspended");
            memory.setInterruptControl(1u); // CpuResumeIntr
            kernel.endTimeslice(*again, 0x1FFFFF00u);
            h = kernel.beginNextReady(4u);
            t.IsTrue(h && h->id == high, "high thread runs once interrupts are resumed");
            if (!h) return;
            kernel.sleepCurrent(h->cpu);
            kernel.endTimeslice(*h, 0x1FFFFF00u);
            l = kernel.beginNextReady(5u);
            t.IsTrue(l && l->id == low, "low thread resumes");
            if (!l) return;
            memory.setInterruptControl(0u);
            l->cpu.gpr[4] = static_cast<uint32_t>(high);
            t.IsTrue(kernel.dispatchThreadImport(25u, l->cpu, 6u), "own WakeupThread inside the section");
            kernel.endTimeslice(*l, 0x1FFFFF00u);
            h = kernel.beginNextReady(7u);
            t.IsTrue(h && h->id == high, "a syscall readying a higher thread is still a dispatch point");
        });

        tc.Run("IOP idle scheduling preserves deadlines, new work and reset", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            IopMemory memory;
            IopKernel kernel(memory);
            IopCpuState caller{};
            auto start = [&](uint32_t entry, uint32_t priority) {
                memory.write32(0x2008u, entry);
                memory.write32(0x200Cu, 0x400u);
                memory.write32(0x2010u, priority);
                caller.gpr[4] = 0x2000u;
                t.IsTrue(kernel.dispatchThreadImport(4u, caller, 0u), "create thread");
                const auto id = caller.gpr[2];
                caller.gpr[4] = id;
                t.IsTrue(kernel.dispatchThreadImport(6u, caller, 0u), "start thread");
                return id;
            };
            const auto first = start(0x10000u, 16u);
            const auto second = start(0x11000u, 32u);
            auto *thread = kernel.beginNextReady(0u);
            if (!thread) { t.IsTrue(false, "first thread ready"); return; }
            kernel.delayCurrentUntil(100u, thread->cpu);
            kernel.endTimeslice(*thread, 0x1FFFFF00u);
            thread = kernel.beginNextReady(0u);
            if (!thread) { t.IsTrue(false, "second thread ready"); return; }
            kernel.delayCurrentUntil(50u, thread->cpu);
            kernel.endTimeslice(*thread, 0x1FFFFF00u);
            for (uint64_t cycle = 0u; cycle < 50u; ++cycle)
            {
                memory.setInterruptControl(0u);
                t.IsTrue(kernel.beginNextReady(cycle) == nullptr, "no premature delay wake");
                t.Equals(memory.interruptControl(), 1u, "cached idle enables interrupts");
                t.Equals(kernel.nextWakeCycle(200u), uint64_t{50}, "earliest deadline retained");
                t.Equals(kernel.nextWakeCycle(30u), uint64_t{30}, "peripheral deadline not extended");
            }
            thread = kernel.beginNextReady(50u);
            t.IsTrue(thread && static_cast<uint32_t>(thread->id) == second, "lower priority wakes at its earlier deadline");
            if (!thread) return;
            kernel.sleepCurrent(thread->cpu);
            kernel.endTimeslice(*thread, 0x1FFFFF00u);
            t.IsTrue(kernel.beginNextReady(51u) == nullptr, "remaining delay cached");
            const auto third = start(0x12000u, 8u);
            thread = kernel.beginNextReady(51u);
            t.IsTrue(thread && static_cast<uint32_t>(thread->id) == third, "new start invalidates idle before delay expires");
            if (!thread) return;
            kernel.sleepCurrent(thread->cpu);
            kernel.endTimeslice(*thread, 0x1FFFFF00u);
            t.IsTrue(kernel.beginNextReady(99u) == nullptr, "original delay remains asleep");
            thread = kernel.beginNextReady(100u);
            t.IsTrue(thread && static_cast<uint32_t>(thread->id) == first, "original deadline wakes exactly");
            if (!thread) return;
            kernel.delayCurrentUntil(200u, thread->cpu);
            kernel.endTimeslice(*thread, 0x1FFFFF00u);
            t.IsTrue(kernel.beginNextReady(101u) == nullptr, "idle before removal");
            kernel.terminateThreadsInRange(0x10000u, 4u);
            kernel.cleanupDeadThreads();
            t.Equals(kernel.nextWakeCycle(300u), uint64_t{300}, "removed delay cannot leave stale deadline");
            t.IsTrue(kernel.beginNextReady(102u) == nullptr, "idle with no deadlines");
            kernel.reset();
            t.Equals(kernel.nextWakeCycle(400u), uint64_t{400}, "reset discards cached deadline");
            const auto restarted = start(0x10000u, 16u);
            thread = kernel.beginNextReady(0u);
            t.IsTrue(thread && static_cast<uint32_t>(thread->id) == restarted, "reset permits new scheduling epoch");
        });

        tc.Run("IOP cached idle is invalidated by semaphore, event and deferred RPC work", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            IopMemory memory;
            IopKernel kernel(memory);
            IopCpuState caller{};
            memory.write32(0x2008u, 0x10000u);
            memory.write32(0x200Cu, 0x400u);
            memory.write32(0x2010u, 16u);
            caller.gpr[4] = 0x2000u;
            t.IsTrue(kernel.dispatchThreadImport(4u, caller, 0u), "create worker");
            const int id = static_cast<int>(caller.gpr[2]);
            caller.gpr[4] = static_cast<uint32_t>(id);
            t.IsTrue(kernel.dispatchThreadImport(6u, caller, 0u), "start worker");
            memory.write32(0x2108u, 0u); memory.write32(0x210Cu, 1u);
            caller.gpr[4] = 0x2100u;
            t.IsTrue(kernel.dispatchSemaphoreImport(4u, caller), "create semaphore");
            const auto sema = caller.gpr[2];
            auto *thread = kernel.beginNextReady(0u);
            if (!thread) { t.IsTrue(false, "worker ready"); return; }
            thread->cpu.gpr[4] = sema;
            t.IsTrue(kernel.dispatchSemaphoreImport(8u, thread->cpu), "wait semaphore");
            kernel.endTimeslice(*thread, 0x1FFFFF00u);
            t.IsTrue(kernel.beginNextReady(0u) == nullptr, "idle awaiting semaphore");
            caller.gpr[4] = sema;
            t.IsTrue(kernel.dispatchSemaphoreImport(7u, caller), "interrupt signal semaphore");
            thread = kernel.beginNextReady(0u);
            t.IsTrue(thread && thread->id == id, "semaphore makes worker immediately ready");
            if (!thread) return;
            const int event = kernel.createInternalEventFlag(0u, 0u, 0u);
            thread->cpu.gpr[4] = static_cast<uint32_t>(event);
            thread->cpu.gpr[5] = 1u; thread->cpu.gpr[6] = 0u; thread->cpu.gpr[7] = 0x2300u;
            t.IsTrue(kernel.dispatchEventImport(10u, thread->cpu), "wait event");
            kernel.endTimeslice(*thread, 0x1FFFFF00u);
            t.IsTrue(kernel.beginNextReady(0u) == nullptr, "idle awaiting event");
            t.IsTrue(kernel.setInternalEventFlag(event, 1u), "internal event signal");
            thread = kernel.beginNextReady(0u);
            t.IsTrue(thread && thread->id == id, "internal event invalidates idle");
            t.Equals(memory.read32(0x2300u), 1u, "event result delivered");
            if (!thread) return;
            kernel.parkRpcCurrent(thread->cpu);
            kernel.endTimeslice(*thread, 0x1FFFFF00u);
            t.IsTrue(kernel.beginNextReady(0u) == nullptr, "idle awaiting RPC");
            t.IsTrue(kernel.startRpcCall(id, 1u, 0x12000u, 4u, 0x2500u, 16u, 0u, 0x1FFFFF00u), "queue deferred RPC");
            thread = kernel.beginNextReady(0u);
            t.IsTrue(thread && thread->id == id, "RPC starts from cached idle");
            if (!thread) return;
            thread->cpu.pc = 0x1FFFFF00u; thread->cpu.gpr[2] = 7u;
            const auto completion = kernel.finishRpcCall(*thread, 0x1FFFFF00u);
            t.IsTrue(completion && completion->token == 1u && completion->result == 7u, "RPC completion preserved");
            kernel.endTimeslice(*thread, 0x1FFFFF00u);
            t.IsTrue(kernel.beginNextReady(0u) == nullptr, "RPC worker returns to idle");
            t.IsTrue(kernel.startRpcCall(id, 2u, 0x12000u, 4u, 0x2500u, 16u, 0u, 0x1FFFFF00u), "queue second RPC");
            kernel.cancelRpcCall(2u);
            t.IsTrue(kernel.beginNextReady(0u) == nullptr, "cancelled RPC does not become runnable");
            t.IsTrue(kernel.startRpcCall(id, 3u, 0x12000u, 4u, 0x2500u, 16u, 0u, 0x1FFFFF00u), "RPC after cancellation accepted");
            thread = kernel.beginNextReady(0u);
            t.IsTrue(thread && thread->id == id, "RPC after cancellation wakes worker");
        });

        tc.Run("Original SIO2MAN style DMA imports configure and start the memory-card channel", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            iop_test::Host host;
            iop_test::Irx image(0x10000u, 0x1000u);
            // o32 direction is at sp+16; $t0 is not the fifth argument.
            image.words(0u, {0x27BDFFE0u, 0xAFBF001Cu,
                0x2404000Bu, 0x3C05A006u, 0x34A54958u, 0x24060040u, 0x24070001u,
                0x24080001u, 0xAFA80010u, 0x24080000u, 0x0C004085u, 0u,
                0x3C080001u, 0x35080400u, 0xAD020000u,
                0x0C004087u, 0u,
                0x3C091F80u, 0x35291540u, 0x8D2A0000u, 0x8D2B0004u, 0x8D2C0008u,
                0xAD0A0004u, 0xAD0B0008u, 0xAD0C000Cu,
                0x8FBF001Cu, 0x27BD0020u, 0x03E00008u, 0x00001021u});
            image.words(0x200u, {0x41E00000u, 0u, 0x102u, 0x63616D64u, 0x006E616Du,
                0x03E00008u, 0x2400001Cu, 0x03E00008u, 0x24000020u, 0u, 0u});
            image.install(host);
            IopEmulator emulator(host);
            t.IsTrue(emulator.loadModuleBuffer(0x1000u, nullptr, 0u).moduleId > 0,
                     "execute actual IRX with SIO2MAN DMA imports");
            uint32_t result[4]{};
            t.IsTrue(emulator.readMemory(0x10400u, result, sizeof(result)), "read guest DMA observation");
            t.Equals(result[0], 1u, "slice DMA setup must report acceptance");
            t.Equals(result[1], 0x00064958u, "DMA address uses the physical 24-bit pointer");
            t.Equals(result[2], 0x00010040u, "64 words in one DMA block");
            t.Equals(result[3], 0x01000201u, "start bit, slice mode, and stack-supplied direction");
        });

        tc.Run("Nested IOP CPU interrupt suspension reports disabled state and restores the outer state", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            iop_test::Host host;
            iop_test::Irx image(0x10000u, 0x1000u);
            std::vector<uint32_t> code{0x27BDFFE0u, 0xAFBF001Cu};
            auto call = [&](uint32_t instruction) { code.insert(code.end(), {instruction, 0u}); };
            auto address = [&](uint32_t value) { code.insert(code.end(), {0x3C040001u, 0x34840000u | value}); };
            auto record = [&](uint32_t offset) {
                code.insert(code.end(), {0x3C080001u, 0x35080400u, 0xAD020000u | offset});
            };
            auto control = [&](uint32_t offset) {
                code.insert(code.end(), {0x3C091F80u, 0x35291078u, 0x8D220000u, 0u});
                record(offset);
            };
            call(0x0C004085u); // CpuEnableIntr
            address(0x440u); call(0x0C004087u); record(0u); // outer CpuSuspendIntr
            address(0x444u); call(0x0C004087u); record(4u); // nested CpuSuspendIntr
            code.insert(code.end(), {0x8C840000u, 0u}); call(0x0C004089u); control(8u); // resume inner
            address(0x440u); code.insert(code.end(), {0x8C840000u, 0u});
            call(0x0C004089u); control(12u); // resume outer
            call(0x0C00408Bu); record(16u); // CpuDisableIntr
            call(0x0C00408Bu); record(20u); // repeated CpuDisableIntr
            code.push_back(0x00002021u); call(0x0C004087u); record(24u); // null state while disabled
            call(0x0C004085u);
            code.push_back(0x00002021u); call(0x0C004087u); record(28u); control(32u); // null state while enabled
            call(0x0C004085u);
            code.insert(code.end(), {0x8FBF001Cu, 0x27BD0020u, 0x03E00008u, 0x00001021u});
            for (size_t i = 0; i < code.size(); ++i) image.words(static_cast<uint32_t>(i * 4u), {code[i]});
            image.words(0x200u, {0x41E00000u, 0u, 0x102u, 0x72746E69u, 0x006E616Du,
                                0x03E00008u, 0x24000009u, 0x03E00008u, 0x24000011u,
                                0x03E00008u, 0x24000012u, 0x03E00008u, 0x24000008u, 0u, 0u});
            image.install(host);
            IopEmulator emulator(host);
            const auto loaded = emulator.loadModuleBuffer(0x1000u, nullptr, 0u);
            t.IsTrue(loaded.moduleId > 0, "execute original-style IRX import calls");
            uint32_t results[9]{}, saved[2]{};
            t.IsTrue(emulator.readMemory(0x10400u, results, sizeof(results)), "read guest results");
            t.IsTrue(emulator.readMemory(0x10440u, saved, sizeof(saved)), "read saved interrupt states");
            constexpr uint32_t disabledError = static_cast<uint32_t>(-102); // PS2SDK KE_CPUDI
            t.Equals(saved[0], 1u, "outer suspension saves enabled state");
            t.Equals(saved[1], 0u, "nested suspension writes disabled state even on error");
            t.Equals(results[0], 0u, "first suspension succeeds");
            t.Equals(results[1], disabledError, "nested suspension reports already disabled");
            t.Equals(results[2], 0u, "inner resume does not enable interrupts prematurely");
            t.Equals(results[3], 1u, "outer resume restores enabled state");
            t.Equals(results[4], 0u, "first disable succeeds");
            t.Equals(results[5], disabledError, "repeated disable reports already disabled");
            t.Equals(results[6], disabledError, "null state does not suppress disabled error");
            t.Equals(results[7], 0u, "null state suspension succeeds when enabled");
            t.Equals(results[8], 0u, "null state suspension still disables interrupts");
        });

        for (const unsigned scenario : {0u, 1u, 2u})
        {
        const bool lineMasked = scenario != 0u;
        const bool rearm = scenario == 2u;
        tc.Run(rearm ? "IOP DMA handler can schedule a new transfer on its own line"
                     : lineMasked ? "IOP DMA completion survives masking its individual interrupt"
                                  : "IOP DMA completion stays pending while CPU interrupts are disabled", [lineMasked, rearm](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            iop_test::Host host;
            iop_test::Irx image(0x10000u, 0x1000u);
            std::vector<uint32_t> code{
                0x27BDFFE0u, 0xAFBF001Cu,
                0x24040024u, 0x24050001u, 0x3C060001u, 0x34C60180u,
                0x3C070001u, 0x34E70400u, 0x0C004085u, 0u, // RegisterIntrHandler
                0x24040024u, 0x0C004087u, 0u, // EnableIntr
                0x24050000u, lineMasked ? 0x0C00408Fu : 0x0C004089u, 0u, // DisableIntr or CpuDisableIntr
                0x3C080001u, 0x35080400u, // counter address
                0x3C0A1F80u, 0x354A10C0u, // SPU0 DMA registers
                0x3C090001u, 0x35290010u, 0xAD490004u, // BCR = one block of 16 words
                0x3C090100u, 0x35290201u, 0xAD490008u}; // CHCR starts DMA
            auto spin = [&] {
                code.insert(code.end(), {0x34090800u, 0x2529FFFFu, 0x1520FFFEu, 0u});
            };
            spin();
            code.insert(code.end(), {0x8D090000u, 0u, 0xAD090004u, // count while masked
                                    lineMasked ? 0x0C004087u : 0x0C00408Bu, 0u}); // EnableIntr or CpuEnableIntr
            spin();
            code.insert(code.end(), {0x8D090000u, 0u, 0xAD090008u,
                                    0x0C00408Du, 0u, 0xAD020010u, // QueryIntrContext after delivery
                                    0x8FBF001Cu, 0x27BD0020u, 0x03E00008u, 0x00001021u});
            for (size_t i = 0; i < code.size(); ++i) image.words(static_cast<uint32_t>(i * 4u), {code[i]});
            std::vector<uint32_t> handler{0x27BDFFF0u, 0xAFBF000Cu, 0xAFA40008u,
                                         0x0C00408Du, 0u, // QueryIntrContext inside the actual DMA handler
                                         0x8FA40008u, 0u, 0xAC82000Cu,
                                         0x8C820000u, 0u, 0x24420001u, 0xAC820000u};
            if (rearm)
                handler.insert(handler.end(), {0x24090001u, 0x14490006u, 0u, // only the first IRQ rearms DMA
                                               0x3C0A1F80u, 0x354A10C0u,
                                               0x3C090100u, 0x35290201u, 0xAD490008u});
            handler.insert(handler.end(), {0x8FBF000Cu, 0x27BD0010u, 0x03E00008u, 0x24020001u});
            for (size_t i = 0; i < handler.size(); ++i)
                image.words(0x180u + static_cast<uint32_t>(i * 4u), {handler[i]});
            image.words(0x200u, {0x41E00000u, 0u, 0x102u, 0x72746E69u, 0x006E616Du,
                                0x03E00008u, 0x24000004u, 0x03E00008u, 0x24000006u,
                                0x03E00008u, 0x24000008u, 0x03E00008u, 0x24000009u,
                                0x03E00008u, 0x24000017u,
                                0x03E00008u, 0x24000007u, 0u, 0u});
            image.install(host);
            IopEmulator emulator(host);
            const auto loaded = emulator.loadModuleBuffer(0x1000u, nullptr, 0u);
            t.IsTrue(loaded.moduleId > 0, "load and execute actual synthetic IRX");
            uint32_t counts[5]{};
            t.IsTrue(emulator.readMemory(0x10400u, counts, sizeof(counts)), "read guest-observed interrupt counts");
            t.Equals(counts[1], 0u, "handler does not run in the interrupt-disabled section");
            const uint32_t expected = rearm ? 2u : 1u;
            t.Equals(counts[2], expected, "each started transfer is delivered once after re-enable");
            t.Equals(counts[0], expected, "final handler count matches started transfers");
            t.Equals(counts[3], 1u, "DMA handler observes interrupt context");
            t.Equals(counts[4], 0u, "module code observes thread context after handler returns");
        });
        }

        tc.Run("IOP CDVD clock writes bounded BCD calendar data without aliasing EE memory", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            iop_test::Host host; IopMemory memory; IopKernel kernel(memory);
            IopCdvd cdvd(host, memory, kernel);
            constexpr uint32_t address = 0x2401u;
            for (uint32_t i = address - 1u; i <= address + 8u; ++i) memory.write8(i, 0xA5u);
            IopCpuState cpu{}; cpu.gpr[4] = 0x80000000u | address;
            t.IsTrue(cdvd.dispatchImport(24u, cpu), "read clock import handled");
            t.Equals(cpu.gpr[2], 1u, "valid clock returns success");
            t.Equals(memory.read8(address), uint8_t{0u}, "successful RTC status");
            t.Equals(memory.read8(address + 4u), uint8_t{0u}, "reserved byte initialized");
            auto decimal = [&](uint32_t offset) {
                const uint8_t value = memory.read8(address + offset);
                t.IsTrue((value & 15u) <= 9u && (value >> 4u) <= 9u, "calendar byte is valid BCD");
                return (value >> 4u) * 10u + (value & 15u);
            };
            t.IsTrue(decimal(1u) <= 59u, "seconds range");
            t.IsTrue(decimal(2u) <= 59u, "minutes range");
            t.IsTrue(decimal(3u) <= 23u, "hours range");
            t.IsTrue(decimal(5u) >= 1u && decimal(5u) <= 31u, "day range");
            t.IsTrue(decimal(6u) >= 1u && decimal(6u) <= 12u, "month range");
            (void)decimal(7u);
            t.Equals(memory.read8(address - 1u), uint8_t{0xA5}, "leading guard retained");
            t.Equals(memory.read8(address + 8u), uint8_t{0xA5}, "trailing guard retained");
            t.Equals(host.guestWrites, size_t{0}, "clock never writes EE space");
            for (uint32_t bad : {0u, IopMemory::RamSize - 7u, 0x1F801000u})
            {
                memory.write8(IopMemory::RamSize - 1u, 0xA5u);
                cpu.gpr[4] = bad;
                t.IsTrue(cdvd.dispatchImport(24u, cpu), "invalid clock import handled");
                t.Equals(cpu.gpr[2], 0u, "invalid range returns failure");
                t.Equals(memory.read8(IopMemory::RamSize - 1u), uint8_t{0xA5}, "invalid range cannot partially write");
            }
            cpu.gpr[4] = address;
            t.IsTrue(cdvd.dispatchImport(51u, cpu), "raw clock import handled");
            t.Equals(cpu.gpr[2], 1u, "raw clock returns valid host RTC");
        });

        tc.Run("SIF GetOtherData copies EE payload and rejects invalid ranges atomically", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            iop_test::Host host;
            IopMemory memory;
            IopKernel kernel(memory);
            IopCdvd cdvd(host, memory, kernel);
            IopRpcBridge rpc(host, memory, kernel, cdvd);
            constexpr uint32_t descriptor = 0x2400u, source = 0x1800u, target = 0x3000u;
            for (uint32_t i = 0; i < 64u; ++i) host.guest[source + i] = static_cast<uint8_t>(i * 7u);
            for (uint32_t i = 0; i < 32u; ++i) memory.write8(descriptor + i, 0xA5u);
            memory.write8(target - 1u, 0xA5u); memory.write8(target + 64u, 0xA5u);
            auto transfer = [&](uint32_t rd, uint32_t src, uint32_t dst, uint32_t size) {
                IopCpuState cpu{};
                cpu.gpr[4] = rd; cpu.gpr[5] = src; cpu.gpr[6] = dst; cpu.gpr[7] = size;
                t.IsTrue(rpc.dispatchSifCmdImport(23u, cpu), "GetOtherData import handled");
                return cpu.gpr[2];
            };
            t.Equals(transfer(descriptor, source, 0x80000000u | target, 64u), 0u, "valid transfer succeeds");
            for (uint32_t i = 0; i < 64u; ++i)
                t.Equals(memory.read8(target + i), host.guest[source + i], "payload reaches IOP in order");
            t.Equals(memory.read32(descriptor + 16u), source, "descriptor records EE source");
            t.Equals(memory.read32(descriptor + 20u), 0x80000000u | target, "descriptor records destination alias");
            t.Equals(memory.read32(descriptor + 24u), 64u, "descriptor records length");
            t.Equals(memory.read8(descriptor + 28u), uint8_t{0xA5}, "descriptor guard preserved");
            t.Equals(memory.read8(target - 1u), uint8_t{0xA5}, "leading payload guard preserved");
            t.Equals(memory.read8(target + 64u), uint8_t{0xA5}, "trailing payload guard preserved");
            const auto reads = host.guestReads;
            t.IsTrue(transfer(descriptor, source, IopMemory::RamSize - 32u, 64u) != 0u, "reject destination overrun");
            t.IsTrue(transfer(IopMemory::RamSize - 24u, source, target, 64u) != 0u, "reject descriptor overrun");
            t.IsTrue(transfer(descriptor, source, target, 0xFFFFFFFFu) != 0u, "reject negative length");
            t.IsTrue(transfer(descriptor, source, target, 0x7FFFFFFFu) != 0u, "reject oversized allocation");
            t.Equals(host.guestReads, reads, "invalid IOP ranges never read EE memory");
            t.IsTrue(transfer(descriptor, 0x1FFF0u, target, 64u) != 0u, "reject invalid EE source");
            t.Equals(memory.read32(descriptor + 16u), source, "failure preserves descriptor");
            t.Equals(memory.read8(target + 7u), host.guest[source + 7u], "failure preserves payload");
            t.Equals(transfer(descriptor, source, target, 0u), 0u, "empty transfer succeeds");
            t.Equals(memory.read32(descriptor + 24u), 0u, "empty transfer records zero length");
        });

        tc.Run("DVD raw reads preserve payloads and deliver later DMA chunks", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            const auto suffix = std::to_string(std::chrono::steady_clock::now().time_since_epoch().count());
            struct Fixture
            {
                std::filesystem::path root;
                ~Fixture() { std::error_code error; std::filesystem::remove_all(root, error); }
            } fixture{std::filesystem::temp_directory_path() / ("ps2x-raw-dvd-" + suffix)};
            std::filesystem::create_directories(fixture.root);
            iop_test::Host host;
            host.cdRoot = fixture.root.string();
            host.file.resize(26u * 2048u);
            for (size_t i = 0; i < host.file.size(); ++i)
                host.file[i] = static_cast<uint8_t>((i / 2048u) * 7u + i % 2048u);
            { std::ofstream file(fixture.root / "RAW.BIN", std::ios::binary);
              file.write(reinterpret_cast<const char *>(host.file.data()), host.file.size()); }
            IopMemory memory;
            IopKernel kernel(memory);
            IopCdvd cdvd(host, memory, kernel);
            constexpr uint32_t param = 0x2400u, pathAddress = 0x2500u, sp = 0x3000u, mode = 0x3100u;
            const char path[] = "cdrom0:\\RAW.BIN;1";
            t.IsTrue(memory.writeRam(pathAddress, path, sizeof(path)), "write file path");
            memory.write32(param, 0u);
            IopCpuState cpu{};
            cpu.gpr[4] = static_cast<uint32_t>(-14); cpu.gpr[5] = param;
            t.IsTrue(cdvd.dispatchImport(50u, cpu), "shared state control handled");
            t.Equals(cpu.gpr[2], 0xFFu, "shared state query succeeds");
            const uint32_t state = memory.read32(param);
            t.IsTrue(state != 0u && memory.ownsRamRange(state, 0x200u), "shared state is real owned storage");
            t.IsTrue(cdvd.dispatchImport(50u, cpu), "repeat query handled");
            t.Equals(memory.read32(param), state, "state pointer remains stable");
            cpu.gpr[4] = param; cpu.gpr[5] = pathAddress;
            t.IsTrue(cdvd.dispatchImport(10u, cpu), "search raw payload file");
            const uint32_t lsn = memory.read32(param);
            const uint32_t storage = memory.allocate(16u * 2064u + 32u, 16u);
            t.IsTrue(storage != 0u, "allocate reusable raw workspace");
            if (storage == 0u) return;
            const uint32_t buffer = storage + 16u;
            for (uint32_t i = 0; i < 16u * 2064u + 32u; ++i) memory.write8(storage + i, 0xA5u);
            memory.write32(sp + 16u, 16u); memory.write32(sp + 20u, 0x4000u);
            memory.write32(mode, 0x100u);
            auto rawRead = [&](uint32_t start, uint32_t count, uint32_t destination) {
                cpu = {}; cpu.gpr[4] = start; cpu.gpr[5] = count; cpu.gpr[6] = destination;
                cpu.gpr[7] = mode; cpu.gpr[28] = 0x1234u; cpu.gpr[29] = sp;
                t.IsTrue(cdvd.dispatchImport(63u, cpu), "raw read import handled");
                return cpu.gpr[2];
            };
            auto verifyChunk = [&](uint32_t firstSector, uint32_t count) {
                for (uint32_t i = 0; i < count; ++i)
                {
                    const uint32_t address = buffer + i * 2064u;
                    const uint32_t id = (uint32_t{memory.read8(address + 1u)} << 16u) |
                                        (uint32_t{memory.read8(address + 2u)} << 8u) | memory.read8(address + 3u);
                    t.Equals(id - 0x30000u, lsn + firstSector + i, "sector identity matches LSN");
                    t.Equals(memory.read8(address), uint8_t{0x20}, "layer-zero data sector ID");
                    for (uint32_t j = 0; j < 2048u; ++j)
                        if (memory.read8(address + 12u + j) != host.file[(firstSector + i) * 2048u + j])
                        { t.IsTrue(false, "raw sector preserves every payload byte"); return; }
                }
            };
            t.Equals(rawRead(lsn, 26u, buffer), 1u, "first chunk accepted");
            verifyChunk(0u, 16u);
            cpu.gpr[4] = 1u; t.IsTrue(cdvd.dispatchImport(11u, cpu), "poll read completion");
            t.Equals(cpu.gpr[2], 1u, "command remains busy while ten sectors remain");
            auto cb = cdvd.takeCompletionCallback();
            t.IsTrue(cb.has_value() && cb->address == 0x4000u && cb->gp == 0x1234u, "chunk callback preserves address and GP");
            t.Equals(memory.read16(state + 0xA4u), uint16_t{12}, "retail CDVDFSV lw at 0x17a8 observes DMA words");
            t.Equals(memory.read16(state + 0xA6u), uint16_t{43}, "retail CDVDFSV lw at 0x1798 observes blocks per sector");
            t.Equals(memory.read32(state + 0xA8u), buffer, "retail CDVDFSV DMA destination field");
            auto dmaImport = [&](uint16_t ordinal, uint32_t value) {
                IopCpuState dmaCpu{}; dmaCpu.gpr[4] = 3u; dmaCpu.gpr[5] = value;
                t.IsTrue(dispatchDmacmanRegister(memory, ordinal, dmaCpu), "physical CDVDFSV DMACMAN import handled");
                cdvd.serviceDma();
                return dmaCpu.gpr[2];
            };
            dmaImport(8u, 0u);
            t.Equals(dmaImport(9u, 0u), 0u, "stopped DMA channel reads back zero");
            dmaImport(4u, buffer);
            dmaImport(6u, (uint32_t{memory.read16(state + 0xA6u)} * 10u << 16u) |
                                      memory.read16(state + 0xA4u));
            dmaImport(8u, 0x41000200u);
            cdvd.serviceDma();
            verifyChunk(16u, 10u);
            t.Equals(memory.read32(0xBF8010B0u), buffer + 10u * 2064u, "DMA advances byte destination");
            t.Equals(memory.read32(0xBF8010B4u), 12u, "DMA consumes all block counts");
            t.Equals(memory.read32(0xBF8010B8u) & 0x01000000u, 0u, "DMA clears active bit after payload transfer");
            cpu.gpr[4] = 1u; t.IsTrue(cdvd.dispatchImport(11u, cpu), "poll final completion");
            t.Equals(cpu.gpr[2], 0u, "all requested sectors delivered");
            const uint32_t before = memory.read32(buffer + 12u);
            t.Equals(rawRead(0xFFFFFFFEu, 4u, buffer), 0u, "wrapped LSN is rejected");
            t.Equals(rawRead(lsn, 2u, IopMemory::RamSize - 1u), 0u, "invalid output range rejected");
            t.Equals(rawRead(lsn + 26u, 1u, buffer), 0u, "unmapped sector rejects before workspace overwrite");
            t.Equals(memory.read32(buffer + 12u), before, "failed reads preserve previous payload");
            t.Equals(memory.read8(state + 1u), uint8_t{0x30}, "shared error state agrees with failed read");
            for (uint32_t i = 0; i < 16u; ++i)
            {
                t.Equals(memory.read8(storage + i), uint8_t{0xA5}, "leading guard preserved");
                t.Equals(memory.read8(buffer + 16u * 2064u + i), uint8_t{0xA5}, "trailing guard preserved");
            }
        });
        tc.Run("CDVDFSV internal readiness distinguishes raw status and media compatibility", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            iop_test::Host host;
            IopMemory memory;
            IopKernel kernel(memory);
            IopCdvd cdvd(host, memory, kernel);
            constexpr uint32_t param = 0x2000u;
            memory.write32(param, 0xAABBCCDDu);
            auto call = [&](uint16_t ordinal, uint32_t argument) {
                IopCpuState cpu{};
                cpu.gpr[4] = argument;
                cpu.gpr[5] = param;
                t.IsTrue(cdvd.dispatchImport(ordinal, cpu), "CDVD import handled");
                return cpu.gpr[2];
            };
            auto diskReady = [&]() {
                const uint32_t raw = call(13u, 8u);
                const uint32_t busy = call(50u, static_cast<uint32_t>(-3));
                const uint32_t compatible = call(50u, static_cast<uint32_t>(-12));
                return (raw & 0xC0u) == 0x40u && busy == 0u && compatible != 0u;
            };
            t.Equals(call(13u, 0u), 2u, "public blocking ready code remains 2");
            t.Equals(call(13u, 1u), 2u, "public polling ready code remains 2");
            t.Equals(memory.read8(0xBF402005u), uint8_t{0x40}, "inlined uncached status reads ready byte");
            t.Equals(memory.read8(0x9F40200Fu), uint8_t{0x14}, "cached disc type alias sees PS2 DVD");
            t.Equals(call(13u, 8u), uint32_t{memory.read8(0x1F402005u)}, "mode 8 and direct MMIO share status");
            t.Equals(call(12u, 0u), uint32_t{memory.read8(0xBF40200Fu)}, "type import and inlined read agree");
            t.IsTrue(memory.isHardwareAddress(0xBF402005u), "CDVD addresses are hardware, not missing RAM");
            memory.write8(0xBF402005u, 0u);
            t.Equals(call(13u, 1u), 6u, "not-ready register is not reported ready");
            t.Equals(call(13u, 8u), 0u, "raw mode preserves changed hardware status");
            cdvd.reset();
            t.IsTrue(diskReady(), "CDVDFSV readiness predicate accepts automatic DVD mode");
            call(75u, 1u);
            t.IsTrue(!diskReady(), "CD-only mode rejects DVD instead of forcing success");
            call(75u, 2u);
            t.IsTrue(diskReady(), "explicit DVD mode accepts the disc");
            t.Equals(memory.read32(param), 0xAABBCCDDu, "readiness queries do not overwrite unused output argument");
            call(75u, 1u);
            cdvd.reset();
            t.IsTrue(diskReady(), "reset restores automatic media selection");
            t.Equals(call(50u, static_cast<uint32_t>(-22)), 0u, "missing DVD root cannot validate layer mapping");
        });
        tc.Run("IOP heap reuses released buffers and joins adjacent free space", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            IopMemory memory;
            constexpr uint32_t request = 266304u;
            constexpr uint32_t capacity = IopMemory::HeapLimit - IopMemory::HeapBase;
            const uint32_t first = memory.allocate(0x20000u, 64u);
            const uint32_t second = memory.allocate(request - 0x20000u, 64u);
            const uint32_t live = memory.allocate(capacity - request, 64u);
            t.IsTrue(first != 0 && second != 0 && live != 0, "fill heap with temporary and live allocations");
            if (!first || !second || !live) return;
            memory.write32(live, 0x12345678u);
            t.Equals(memory.maxFreeMemory(), 0u, "full heap reports no free block");
            t.Equals(memory.allocate(16u), 0u, "full heap cannot allocate");
            t.IsTrue(memory.freeAllocation(first), "release first half");
            t.IsTrue(memory.freeAllocation(second), "release neighboring half");
            t.Equals(memory.maxFreeMemory(), request, "largest free block combines released neighbors");
            const uint32_t reused = memory.allocate(request, 64u);
            t.Equals(reused, first, "RE4-sized request fits below the previous allocation cursor");
            t.Equals(memory.read32(live), 0x12345678u, "reuse preserves live memory");
            t.IsTrue(memory.ownsRamRange(reused, request), "reused buffer is owned for RPC transfers");
            t.Equals(memory.allocate(0xFFFFFFFFu), 0u, "overflowing allocation is rejected");
            t.Equals(memory.allocate(32u, 16u, 0xFFFFFFF0u), 0u, "wrapping fixed address is rejected");
            t.Equals(memory.allocate(32u, 24u), 0u, "invalid alignment is rejected");
        });
        tc.Run("modload loads IOP buffers without executing then starts with five argument ABI", [](TestCase &t)
        {
            for (const uint32_t argumentLength : {3u, 4u})
            {
                using namespace ps2x::iop::detail;
                iop_test::Host host;
                iop_test::Irx child(0x30000u);
                child.words(0u, {0x3C080001u, 0x35081E00u, 0x24090001u,
                    0xAD090000u, 0xAD040004u, 0x8CA90004u, 0u, 0xAD090008u,
                    0x03E00008u, 0x24020002u});
                iop_test::Irx parent(0x10000u, 0x2000u);
                parent.words(0u, {
                    0x27BDFFD0u, 0xAFBF002Cu,
                    0x3C040001u, 0x34840500u, 0x0C00403Du, 0u,
                    0x3C080001u, 0x35081E00u, 0xAD020010u,
                    0x8D090000u, 0xAD090014u, // entry must not run at load time
                    0x00402021u, 0x3C050001u, 0x34A51D00u, (0x24060000u | argumentLength),
                    0x3C070001u, 0x34E71D20u, 0x25090018u, 0xAFA90010u,
                    0x0C00403Fu, 0u,
                    0x3C080001u, 0x35081E00u, 0xAD02001Cu,
                    0x8FBF002Cu, 0x27BD0030u, 0x03E00008u, 0x00001021u});
                parent.words(0xE0u, {0x41E00000u, 0u, 0x107u, 0x6C646F6Du, 0x0064616Fu,
                    0x03E00008u, 0x2400000Au, 0x03E00008u, 0x24000008u, 0u, 0u});
                std::copy(child.bytes.begin(), child.bytes.end(), parent.bytes.begin() + 0x600u);
                parent.words(0x1D00u, {0x00646F6Du}); // "mod"
                parent.words(0x1D20u, {0x00636261u}); // "abc"
                host.file = parent.bytes;
                IopEmulator emulator(host);
                const auto loaded = emulator.loadModule("host:parent.irx", nullptr, 0u);
                t.IsTrue(loaded.moduleId > 0, "parent completed through real import stubs");
                uint32_t evidence[8]{};
                t.IsTrue(emulator.readMemory(0x11E00u, evidence, sizeof(evidence)), "read guest evidence");
                t.Equals(evidence[0], 1u, "child entry executed");
                t.Equals(evidence[1], 2u, "argc counts module name and packed argument");
                uint32_t copiedArgument = 0u;
                t.IsTrue(emulator.readMemory(evidence[2], &copiedArgument, 4u), "read argv string");
                t.Equals(copiedArgument, 0x00636261u, "owned final argument is safely terminated");
                t.Equals(evidence[5], 0u, "LoadModuleBuffer did not execute child");
                t.Equals(evidence[6], 2u, "result is written through fifth stack argument");
                t.IsTrue(evidence[4] > 0u, "load returns a module ID");
                t.Equals(evidence[7], evidence[4], "StartModule returns the loaded module ID");
                uint32_t packed = 0u;
                t.IsTrue(emulator.readMemory(0x11D20u, &packed, 4u), "read original argument");
                t.Equals(packed, 0x00636261u, "a3 is an input string, not result pointer");
                t.Equals(host.guestReads, size_t{0}, "modload ELF is read from IOP RAM, not EE RAM");
            }
        });
        tc.Run("CDVD layer search returns readable file metadata and rejects unavailable layers", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            const auto suffix = std::to_string(std::chrono::steady_clock::now().time_since_epoch().count());
            struct Fixture
            {
                std::filesystem::path root;
                ~Fixture() { std::error_code error; std::filesystem::remove_all(root, error); }
            } fixture{std::filesystem::temp_directory_path() / ("ps2x-layer-search-" + suffix)};
            std::filesystem::create_directories(fixture.root / "MOVIE");
            { std::ofstream file(fixture.root / "MOVIE" / "OPENING.PSS", std::ios::binary); file.write("PSS!", 4); }
            iop_test::Host host;
            host.cdRoot = fixture.root.string();
            host.file = {'P', 'S', 'S', '!'};
            IopMemory memory;
            IopKernel kernel(memory);
            IopCdvd cdvd(host, memory, kernel);
            const char path[] = "cdrom0:\\movie\\opening.pss;1";
            t.IsTrue(memory.writeRam(0x2480u, path, sizeof(path)), "write lookup path");
            IopCpuState cpu{};
            cpu.gpr[4] = static_cast<uint32_t>(-22); cpu.gpr[5] = 0x2380u;
            memory.write32(0x2380u, 0xAABBCCDDu);
            t.IsTrue(cdvd.dispatchImport(50u, cpu), "DVD geometry control handled");
            t.Equals(cpu.gpr[2], 1u, "extracted DVD has a validated continuous layer mapping");
            t.Equals(memory.read32(0x2380u), 0xAABBCCDDu, "geometry query leaves unused output unchanged");
            cpu.gpr[4] = static_cast<uint32_t>(-23); cpu.gpr[5] = 0x2380u;
            memory.write32(0x2380u, 21u);
            t.IsTrue(cdvd.dispatchImport(50u, cpu), "DVD LSN translation handled");
            t.Equals(cpu.gpr[2], 21u, "virtual single-layer LSN remains unchanged");
            cpu.gpr[4] = 0x2400u; cpu.gpr[5] = 0x2480u; cpu.gpr[6] = 0u;
            t.IsTrue(cdvd.dispatchImport(84u, cpu), "layer search import handled");
            t.Equals(cpu.gpr[2], 1u, "layer zero resolves case-insensitive ISO path");
            const uint32_t lsn = memory.read32(0x2400u);
            t.IsTrue(lsn >= 20u, "valid file sector");
            t.Equals(memory.read32(0x2404u), 4u, "actual file size");
            t.Equals(memory.readString(0x2408u, 16u), std::string("OPENING.PSS"), "normalized leaf name");
            const uint32_t sectorBuffer = memory.allocate(2048u, 64u);
            t.IsTrue(sectorBuffer != 0u, "allocate owned sector buffer");
            cpu.gpr[4] = lsn; cpu.gpr[5] = 1u; cpu.gpr[6] = sectorBuffer;
            t.IsTrue(cdvd.dispatchImport(6u, cpu), "read returned sector");
            t.Equals(cpu.gpr[2], 1u, "sector read succeeds");
            t.Equals(memory.read32(sectorBuffer), 0x21535350u, "returned LSN reads the actual file bytes");
            t.Equals(memory.read32(sectorBuffer + 4u), 0u, "short file sector is padded");
            for (const uint32_t layer : {1u, 0xFFFFFFFFu})
            {
                cpu.gpr[4] = 0x2400u; cpu.gpr[5] = 0x2480u; cpu.gpr[6] = layer;
                memory.write32(0x2400u, 0xDEADBEEFu);
                t.IsTrue(cdvd.dispatchImport(84u, cpu), "unsupported layer import handled");
                t.Equals(cpu.gpr[2], 0u, "unavailable layer fails");
                t.Equals(memory.read32(0x2400u), 0xDEADBEEFu, "failure preserves result");
            }
            const char absent[] = "cdrom0:missing.bin;1";
            t.IsTrue(memory.writeRam(0x2480u, absent, sizeof(absent)), "write absent path"); cpu.gpr[6] = 0u;
            t.IsTrue(cdvd.dispatchImport(84u, cpu), "missing file import handled");
            t.Equals(cpu.gpr[2], 0u, "missing file fails");
            t.Equals(memory.read32(0x2400u), 0xDEADBEEFu, "missing file preserves result");
        });
        tc.Run("CDVD shared read buffer owns stable IOP storage and fails when full", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            iop_test::Host host;
            IopMemory memory;
            IopKernel kernel(memory);
            IopCdvd cdvd(host, memory, kernel);
            IopCpuState cpu{};
            t.IsTrue(cdvd.dispatchImport(47, cpu), "read buffer import handled");
            const uint32_t buffer = cpu.gpr[2];
            t.IsTrue(buffer != 0u && (buffer & 63u) == 0u, "workspace is aligned IOP memory");
            t.IsTrue(memory.ownsRamRange(buffer, 42128u), "whole workspace is owned");
            memory.write32(buffer + 42124u, 0x12345678u);
            cdvd.dispatchImport(47, cpu);
            t.Equals(cpu.gpr[2], buffer, "repeat calls return the same workspace");
            t.Equals(memory.read32(buffer + 42124u), 0x12345678u, "repeat calls preserve data");
            cdvd.reset();
            t.IsFalse(memory.ownsRamRange(buffer, 42128u), "reset releases the old workspace");
            memory.reset();
            t.IsTrue(memory.allocate(IopMemory::HeapLimit - IopMemory::HeapBase) != 0u, "fill heap");
            cdvd.dispatchImport(47, cpu);
            t.Equals(cpu.gpr[2], 0u, "allocation failure cannot return an invalid workspace");
            memory.reset(); cdvd.reset();
            cdvd.dispatchImport(47, cpu);
            t.IsTrue(cpu.gpr[2] != 0u, "workspace can be created after IOP reboot");
            t.Equals(memory.read32(cpu.gpr[2] + 42124u), 0u, "new workspace starts cleared");
        });
        tc.Run("queued native RPC uses its original thread across long execution and semaphore waits", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            iop_test::Host host; host.acceptSifCommands=true;
            IopEmulator emulator(host); iop_test::Irx image(0x10000,0x1000);
            image.words(0,{0x27bdfff0,0xafbf000c,0x3c040001,0x34840700,
                0x0c004145,0,0x00402021,0x00002821,0x0c004147,0,
                0x8fbf000c,0x27bd0010,0x03e00008,0x24020000});
            image.words(0x100,{0x27bdffd0,0xafbf002c,
                0x0c004149,0,0x00402821,0x3c040001,0x34840720,0x0c004165,0,
                0x3c040001,0x34840780,0x0c004189,0,0x3c080001,0xad020900,
                0x3c040001,0x34840740,0x24051234,0x3c060001,0x34c60280,
                0x3c070001,0x34e70800,0xafa00010,0xafa00014,
                0x3c080001,0x35080720,0xafa80018,0x0c004167,0,
                0x0800407c,0});
            image.words(0x1f0,{0x3c040001,0x34840720,0x0c004169,0,0x0800407c,0});
            image.words(0x280,{0x27bdffe0,0xafbf001c,0xafb00018,0x00a08021,
                0x24080002,0x14880006,0,0x3c040001,0x8c840900,0,
                0x0c004185,0,0x0c004149,0,0xae020008,
                0x8e080000,0,0x00004821,0x25290001,0x2508ffff,0x1500fffd,0,
                0xae090000,0x02001021,0x8fbf001c,0x8fb00018,0x27bd0020,0x03e00008,0});
            image.words(0x500,{0x41e00000,0,0x101,0x61626874,0x00006573,
                0x03e00008,0x24000004,0x03e00008,0x24000006,0x03e00008,0x24000014,
                0x03e00008,0x24000005,0,0});
            image.words(0x580,{0x41e00000,0,0x101,0x63666973,0x0000646d,
                0x03e00008,0x24000013,0x03e00008,0x24000011,0x03e00008,0x24000016,0,0});
            image.words(0x600,{0x41e00000,0,0x101,0x65736874,0x0070616d,
                0x03e00008,0x24000008,0x03e00008,0x24000006,0x03e00008,0x24000004,0,0});
            image.words(0x700,{0,0,0x10100,0x2000,24});
            image.words(0x780,{0,0,0,1});
            image.install(host);
            t.IsTrue(emulator.loadModuleBuffer(0x1000,nullptr,0).moduleId>0,"start original-style service thread");
            emulator.runEeCycles(16000);
            t.IsTrue(emulator.hasRpcServer(0x1234),"thread registers its real callback");
            const auto queue=[&](uint32_t count,uint32_t marker,uint32_t function,uint32_t receive) {
                const uint32_t send[]={count,marker,0};host.writeGuest(0x1000,send,sizeof(send));
                ps2x::iop::RpcRequest request{};request.sid=0x1234;request.function=function;
                request.send={0x1000,sizeof(send)};request.receive={receive,12};request.deferredNative=true;
                request.nativeEndPacket[0]=64;request.nativeEndPacket[2]=0x80000008;
                request.nativeEndPacket[5]=marker;
                const auto result=emulator.handleRpc(request);
                t.IsTrue(result.handled && result.deferredNative && !result.signalCompletion,"accept without early completion");
            };
            queue(600000,0x11112222,1,0x4000);
            queue(1,0x33334444,2,0x4100);
            host.fill(0x1000,12,0xee); // Caller memory is no longer owned by the queued request.
            emulator.runEeCycles(16000000);
            t.IsTrue(host.sifCommands.empty(),"no completion at the old two-million-instruction limit");
            t.Equals(host.word(0x4000),0xccccccccu,"no partial output while callback runs");
            emulator.runEeCycles(8000000);
            t.Equals(host.sifCommands.size(),size_t{1},"first request finishes while second waits on a semaphore");
            t.Equals(host.word(0x4000),600000u,"first payload retained through all execution slices");
            t.Equals(host.word(0x4004),0x11112222u,"FIFO buffer ownership preserves first marker");
            t.Equals(host.word(0x4008),1u,"callback observes original server thread identity");
            t.Equals(host.word(0x4100),0xccccccccu,"semaphore wait cannot be resumed prematurely");
            iop_test::Irx signal(0x11000,0x1000);
            signal.words(0,{0x27bdfff0,0xafbf000c,0x3c040001,0x8c840900,0,
                0x0c004187,0,0x8fbf000c,0x27bd0010,0x03e00008,0x24020000});
            signal.install(host);emulator.loadModuleBuffer(0x1000,nullptr,0);
            emulator.runEeCycles(16000);
            t.Equals(host.sifCommands.size(),size_t{2},"real signal wakes original RPC thread and finishes second request");
            t.Equals(host.word(0x4100),1u,"second result comes from original callback");
            t.Equals(host.word(0x4104),0x33334444u,"second staged payload retained");
            t.Equals(host.word(0x4108),1u,"thread identity remains stable after wakeup");
            if(host.sifCommands.size()==2) {
                uint32_t identity[2]{};
                for(unsigned i=0;i<2;++i) {
                    t.Equals(host.sifCommands[i].command,0x80000008u,"native RPC_END command");
                    std::memcpy(&identity[i],host.sifCommands[i].packet.data()+20,4);
                }
                t.Equals(identity[0],0x11112222u,"first packet identity");
                t.Equals(identity[1],0x33334444u,"second packet identity");
            }
            queue(1,0x55556666,2,0x4200);emulator.runEeCycles(16000);
            emulator.reset();emulator.runEeCycles(16000);
            t.Equals(host.sifCommands.size(),size_t{2},"reset cancels old pending native response");
            t.Equals(host.word(0x4200),0xccccccccu,"cancelled request never writes its old result");
            image.install(host);emulator.loadModuleBuffer(0x1000,nullptr,0);emulator.runEeCycles(16000);
            queue(1,0x77778888,2,0x4300);emulator.runEeCycles(16000);
            iop_test::Irx deletion(0x11000,0x1000);
            deletion.words(0,{0x27bdfff0,0xafbf000c,0x24040001,0x0c00414b,0,
                0x8fbf000c,0x27bd0010,0x03e00008,0x24020000});
            deletion.install(host);emulator.loadModuleBuffer(0x1000,nullptr,0);emulator.runEeCycles(16000);
            t.Equals(host.sifCommands.size(),size_t{2},"deleted service cannot send stale completion");
            t.Equals(host.word(0x4300),0xccccccccu,"deleted service never publishes partial output");
            t.IsTrue(std::any_of(host.logs.begin(),host.logs.end(),[](const auto &line){
                return line.find("deferred RPC faulted before return")!=std::string::npos;
            }),"deletion produces an explicit fault instead of leaving an orphan request");
            emulator.reset();image.install(host);
            const auto module=emulator.loadModuleBuffer(0x1000,nullptr,0);emulator.runEeCycles(16000);
            queue(1,0x9999aaaa,2,0x4400);emulator.runEeCycles(16000);
            int32_t stopped=-1;
            t.IsTrue(emulator.stopModule(module.moduleId,&stopped),"unload module owning suspended RPC");
            emulator.runEeCycles(16000);
            t.IsFalse(emulator.hasRpcServer(0x1234),"unload removes service registration");
            t.Equals(emulator.threadCount(),0u,"cancellation cannot resurrect dead service threads");
            t.Equals(host.sifCommands.size(),size_t{2},"unloaded handler cannot send stale response");
            t.Equals(host.word(0x4400),0xccccccccu,"unload preserves incomplete result memory");
        });
        tc.Run("IOP RPC refuses completion from an unfinished guest handler", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            struct Executor : IopGuestExecutor
            {
                bool complete = false;
                bool lastGuestCallCompleted() const noexcept override { return complete; }
                uint32_t executeGuestFunction(uint32_t, uint32_t, uint32_t, uint32_t, uint32_t, uint32_t) override
                { return 0x4000u; }
            } executor;
            iop_test::Host host;
            IopMemory memory;
            IopKernel kernel(memory);
            IopCdvd cdvd(host, memory, kernel);
            IopRpcBridge bridge(host, memory, kernel, cdvd);
            memory.zeroRam(0x4000, 0x100);
            memory.write32(0x4000, 0x12345678u);
            IopCpuState cpu{};
            cpu.gpr[4] = 0x5000; cpu.gpr[5] = 0x1234;
            cpu.gpr[6] = 0x6000; cpu.gpr[7] = 0x4000;
            t.IsTrue(bridge.dispatchSifCmdImport(17, cpu), "register server");
            ps2x::iop::RpcRequest request{};
            request.sid = 0x1234; request.receive = {0x1000, 4u};
            const auto incomplete = bridge.handleRpc(request, executor);
            t.IsFalse(incomplete.handled, "unfinished handler cannot acknowledge RPC");
            t.IsFalse(incomplete.signalCompletion, "no completion signal before return");
            uint32_t received = 0;
            host.readGuest(0x1000, &received, 4);
            t.Equals(received, 0xccccccccu, "unfinished result cannot overwrite EE output");
            executor.complete = true;
            t.IsTrue(bridge.handleRpc(request, executor).handled, "completed handler can return output");
            host.readGuest(0x1000, &received, 4);
            t.Equals(received, 0x12345678u, "completed handler copies real IOP result");
        });
        tc.Run("IOP mailbox queues messages by FIFO or priority and reports empty", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            IopMemory memory;
            t.IsTrue(memory.zeroRam(0x2000, 0x1000), "test structures own their IOP memory");
            IopKernel kernel(memory);
            const auto call = [&](uint16_t ordinal, uint32_t a0, uint32_t a1)
            {
                IopCpuState cpu{};
                cpu.gpr[4] = a0; cpu.gpr[5] = a1;
                t.IsTrue(kernel.dispatchMailboxImport(ordinal, cpu), "mailbox import handled");
                return static_cast<int32_t>(cpu.gpr[2]);
            };
            memory.write32(0x2000, 0u);
            const auto fifo = call(4, 0x2000, 0);
            memory.write8(0x2104, 9u); memory.write8(0x2204, 1u);
            t.Equals(call(6, fifo, 0x2100), 0, "send first");
            t.Equals(call(7, fifo, 0x2200), 0, "interrupt send second");
            t.Equals(memory.read32(0x2100), 0x2200u, "message list links forward");
            t.Equals(memory.read32(0x2200), 0x2100u, "message list is circular");
            t.Equals(call(9, 0x2300, fifo), 0, "poll first");
            t.Equals(memory.read32(0x2300), 0x2100u, "FIFO ignores message priority");
            t.Equals(call(9, 0x2300, fifo), 0, "poll second");
            t.IsTrue(call(9, 0x2300, fifo) < 0, "empty mailbox returns an error");
            memory.write32(0x2000, 4u);
            const auto priority = call(4, 0x2000, 0);
            call(6, priority, 0x2100); call(6, priority, 0x2200);
            call(11, priority, 0x2400);
            t.Equals(memory.read32(0x240c), 2u, "status counts actual queued messages");
            call(9, 0x2300, priority);
            t.Equals(memory.read32(0x2300), 0x2200u, "priority mailbox delivers lower value first");
            kernel.reset();
            t.IsTrue(call(6, priority, 0x2100) < 0, "reset removes mailbox handles");
        });

        tc.Run("IOP mailbox blocks a thread then delivers or cancels its wait", [](TestCase &t)
        {
            using namespace ps2x::iop::detail;
            IopMemory memory;
            t.IsTrue(memory.zeroRam(0x2000, 0x1000), "test structures own their IOP memory");
            IopKernel kernel(memory);
            IopCpuState cpu{}; cpu.gpr[4] = 0x2000;
            kernel.dispatchMailboxImport(4, cpu);
            const uint32_t mailbox = cpu.gpr[2];
            memory.write32(0x2108, 0x3000); memory.write32(0x210c, 0x100);
            memory.write32(0x2110, 10);
            cpu = {}; cpu.gpr[4] = 0x2100;
            kernel.dispatchThreadImport(4, cpu, 0);
            const uint32_t threadId = cpu.gpr[2];
            cpu.gpr[4] = threadId; kernel.dispatchThreadImport(6, cpu, 0);
            auto *thread = kernel.beginNextReady(0);
            t.IsTrue(thread != nullptr, "thread started");
            if (!thread) return;
            thread->cpu.gpr[4] = 0x2300; thread->cpu.gpr[5] = mailbox;
            kernel.dispatchMailboxImport(8, thread->cpu);
            t.Equals(thread->state, IopThreadState::Mailbox, "empty receive suspends thread");
            kernel.endTimeslice(*thread, 0xffffffffu);
            t.IsTrue(kernel.beginNextReady(0) == nullptr, "blocked receiver cannot run");
            cpu = {}; cpu.gpr[4] = mailbox; cpu.gpr[5] = 0x2400;
            kernel.dispatchMailboxImport(6, cpu);
            t.Equals(memory.read32(0x2300), 0x2400u, "sender fills receiver's pointer");
            thread = kernel.beginNextReady(0);
            t.IsTrue(thread != nullptr, "sender wakes receiver");
            if (!thread) return;
            thread->cpu.gpr[4] = 0x2300; thread->cpu.gpr[5] = mailbox;
            kernel.dispatchMailboxImport(8, thread->cpu);
            kernel.endTimeslice(*thread, 0xffffffffu);
            t.IsTrue(kernel.beginNextReady(0) == nullptr, "idle cache sees second mailbox wait before deletion");
            cpu = {}; cpu.gpr[4] = mailbox; kernel.dispatchMailboxImport(5, cpu);
            thread = kernel.beginNextReady(0);
            t.IsTrue(thread != nullptr, "deleting mailbox wakes waiter");
            if (thread) t.IsTrue(static_cast<int32_t>(thread->cpu.gpr[2]) < 0, "deleted wait returns an error");
        });
        tc.Run("PS2 path parsing is shared and normalizes ISO/module names", [](TestCase &t)
        {
            const ps2x::iop::ParsedPs2Path cd = ps2x::iop::parsePs2Path("CDROM0:\\MODULES\\LIBSD.IRX;1");
            t.Equals(cd.device, ps2x::iop::Ps2PathDevice::Cdrom,
                     "device names should be case-insensitive");
            t.Equals(cd.path, std::string("MODULES/LIBSD.IRX"),
                     "separators and ISO version suffixes should normalize once");
            t.Equals(ps2x::iop::ps2PathLeafKey(cd), std::string("libsd"),
                     "module lookup should use a normalized IRX leaf key");

            const ps2x::iop::ParsedPs2Path rom = ps2x::iop::parsePs2Path("rom0:ROMVER");
            t.Equals(rom.device, ps2x::iop::Ps2PathDevice::Rom0,
                     "ROM0 should remain a distinct virtual device");
            t.IsFalse(static_cast<bool>(ps2x::iop::parsePs2Path("unknown0:file.irx")),
                      "unsupported devices must not fall through to cdrom0");
        });

        tc.Run("HLE services activate only after a recognized module load", [](TestCase &t)
        {
            iop_test::Host host;
            ps2x::iop::IopSubsystem subsystem(host);
            t.IsFalse(subsystem.canBindRpc(0x80000701u),
                      "LIBSD RPC must not exist before LIBSD is loaded");

            const ps2x::iop::ModuleLoadResult unknown = subsystem.loadModule("rom0:NOT_A_REAL_MODULE");
            t.IsTrue(unknown.handled, "the module manager should return a real load result");
            t.IsTrue(unknown.moduleId < 0, "unknown ROM modules must fail instead of receiving fake IDs");

            const ps2x::iop::ModuleLoadResult loaded = subsystem.loadModule("rom0:LIBSD");
            t.IsTrue(loaded.moduleId > 0, "a registered no-BIOS HLE module should load");
            t.IsTrue(subsystem.canBindRpc(0x80000701u),
                     "loading LIBSD should activate its HLE RPC endpoint");

            ps2x::iop::RpcRequest request{};
            request.sid = 0x80000701u;
            request.function = 3u;
            t.IsTrue(subsystem.handleRpc(request).handled,
                     "the activated LIBSD service should handle its RPC");
            t.Equals(host.audioCalls, 1u, "the RPC should reach the HLE audio contract");

            int32_t stopResult = -1;
            t.IsTrue(subsystem.stopModule(loaded.moduleId, &stopResult),
                     "an HLE module should have a real stoppable lifecycle");
            t.Equals(stopResult, 0, "stopping an HLE module should report success");
            t.IsFalse(subsystem.canBindRpc(0x80000701u),
                      "stopping LIBSD should deactivate its RPC endpoint");
        });

        tc.Run("unknown SID remains unhandled without a loaded IRX", [](TestCase &t)
        {
            iop_test::Host host;
            ps2x::iop::IopSubsystem subsystem(host);

            ps2x::iop::RpcRequest request{};
            request.sid = 0xDEADC0DEu;
            request.function = 0x99u;
            const ps2x::iop::RpcResult result = subsystem.handleRpc(request);
            t.IsFalse(result.handled, "an unknown SID should not be claimed by the IOP subsystem");
            t.Equals(result.resultAddress, 0u, "an unknown SID should not return a guest result address");
            t.IsFalse(result.signalNowaitCompletion, "an unknown SID should not signal nowait completion");
            t.Equals(result.callbackPolicy, ps2x::iop::CallbackPolicy::RuntimeDefault,
                     "an unknown SID should preserve runtime callback handling");

        });

    });
}
