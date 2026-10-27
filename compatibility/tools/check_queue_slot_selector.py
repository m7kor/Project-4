"""Compile a focused witness using the actual allocator helper from the runtime."""
from pathlib import Path
import json,hashlib
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'artifacts/experiments/vu-queue-allocation/selector';out.mkdir(exist_ok=False)
source=(ROOT/'engines/project4/ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp').read_text()
a=source.index('    template <typename Entry, size_t Count>\n    Entry *firstFreePipelineSlot(')
b=source.index('\n    constexpr uint8_t laneForComponent',a)
helper=source[a:b]
prefix='''#include <array>
#include <bit>
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <limits>
bool scanAllocationSlots = false;
'''
witness=r'''
struct Entry { bool valid = false; };
uint64_t checks = 0;
template <size_t Count> bool verify(uint32_t pending) {
    std::array<Entry, Count> slots{};
    uint32_t expected = UINT32_MAX;
    for (uint32_t i=0; i<Count; ++i) {
        slots[i].valid = (pending & (1u << i)) != 0;
        if (!slots[i].valid && expected == UINT32_MAX) expected = i;
    }
    for (bool scan : {false, true}) {
        scanAllocationSlots = scan;
        Entry *slot = firstFreePipelineSlot(slots, pending);
        uint32_t actual = slot ? uint32_t(slot - slots.data()) : UINT32_MAX;
        ++checks;
        if (actual != expected) {
            std::printf("Mismatch count=%zu mask=%08x scan=%d expected=%u actual=%u\n",Count,pending,int(scan),expected,actual);
            return false;
        }
    }
    return true;
}
template <size_t Count> bool exhaustive() {
    constexpr uint32_t count = 1u << Count;
    constexpr uint32_t high = ~(count-1u);
    for (uint32_t mask=0;mask<count;++mask)
        if (!verify<Count>(mask) || !verify<Count>(mask | high)) return false;
    return true;
}
int main() {
    if (!exhaustive<2>() || !exhaustive<8>() || !exhaustive<16>()) return 1;
    if (!verify<32>(0) || !verify<32>(UINT32_MAX)) return 1;
    for (uint32_t seed=0;seed<65536;++seed)
        if (!verify<32>(seed*0x9e3779b9u)) return 1;
    std::printf("PASS checks=%llu; exact lowest free slot, full queues, ignored high bits, scan and mask modes\n",(unsigned long long)checks);
}
'''
(out/'selector.cpp').write_text(prefix+helper+witness)
metadata={'scope':'Actual source helper with independent linear first-free reference; no game data','helper_sha256':hashlib.sha256(helper.encode()).hexdigest()}
(out/'identity.json').write_text(json.dumps(metadata,indent=2))
cmd='''@echo off
setlocal
set "PATH=%PATH:"=%"
call "C:\\Program Files (x86)\\Microsoft Visual Studio\\2022\\BuildTools\\VC\\Auxiliary\\Build\\vcvars64.bat"
if errorlevel 1 exit /b %errorlevel%
cd /d D:\\Project\\compatbilty\\artifacts\\experiments\\vu-queue-allocation\\selector
"C:\\Program Files\\LLVM\\bin\\clang-cl.exe" /nologo /std:c++20 /O2 /EHsc selector.cpp /Foselector.obj /Feselector.exe
if errorlevel 1 exit /b %errorlevel%
selector.exe
'''
(ROOT/'lab/check-slot-selector.cmd').write_text(cmd)
print('Prepared focused allocator witness from the actual runtime source')
