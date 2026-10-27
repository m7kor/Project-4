"""Extract the actual helper and compare visible retirement against a scalar oracle."""
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'artifacts/experiments/vu-flag-coalescing/retirement-witness'
out.mkdir(exist_ok=False)
archived=ROOT/'artifacts/experiments/vu-flag-coalescing/rejected-core.cpp'
source=archived if archived.exists() else ROOT/'engines/project4/ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp'
s=source.read_text()
a=s.index('    template <bool Coalesce, typename Entries>')
b=s.index('    constexpr uint8_t laneForComponent',a)
helper=s[a:b]
prefix='#include <array>\n#include <bit>\n#include <cstdint>\n#include <cstdio>\n#include <algorithm>\n'
body=r'''
struct Entry {
    bool valid, writesStatus, writesMac, writesSticky, writesClip;
    uint32_t status, extraSticky, mac, clip;
    uint64_t readyCycle;
};
struct State { uint32_t mac=123, status=0xA50, clip=321; };
uint32_t seed=0x51A71C;
uint32_t random32() { seed ^= seed<<13; seed ^= seed>>17; seed ^= seed<<5; return seed; }
template <typename Entries> uint32_t oracle(Entries &entries,uint32_t mask) {
    uint32_t sticky=0;
    for (uint32_t i=0;i<entries.size();++i) if ((mask&(1u<<i)) && entries[i].valid) {
        auto &e=entries[i];
        if(e.writesStatus) sticky |= ((e.status&15u)|e.extraSticky)<<6;
        e.writesStatus=false; e.writesMac=false;
    }
    return sticky;
}
template <typename Entries> void retire(Entries &entries,State &s,uint64_t cycle) {
    std::array<uint32_t,16> order{}; uint32_t n=0;
    for(uint32_t i=0;i<entries.size();++i) if(entries[i].valid && entries[i].readyCycle<=cycle) order[n++]=i;
    std::stable_sort(order.begin(),order.begin()+n,[&](auto a,auto b){return entries[a].readyCycle<entries[b].readyCycle;});
    for(uint32_t j=0;j<n;++j) {
        auto &e=entries[order[j]];
        if(e.writesMac) s.mac=e.mac;
        if(e.writesStatus) {auto c=e.status&15u;s.status=(s.status&0xFF0u)|c|((c|e.extraSticky)<<6);}
        if(e.writesSticky) s.status=(s.status&0x3Fu)|(e.status&0xFC0u);
        if(e.writesClip) s.clip=e.clip;
        e.valid=false;
    }
}
int main() {
    uint64_t checks=0,guarded=0;
    for(uint32_t trial=0;trial<262144;++trial) {
        std::array<Entry,16> original{};uint32_t mask=0;bool fsset=false;
        uint64_t drain=0;
        for(uint32_t i=0;i<original.size();++i) {
            auto &e=original[i]; auto r=random32();
            e={bool(r&1),bool(r&2),bool(r&4),bool((r&0x3f)==0x3f),bool(r&16),random32()&0xFFF,random32()&15,random32(),random32()&0xFFFFFF,random32()%12};
            if(e.valid) {mask|=1u<<i;fsset|=e.writesSticky;drain=std::max(drain,e.readyCycle);}
        }
        // Production caller refuses supersession across any FSSET.
        if(fsset) {++guarded;continue;}
        auto base=original, off=original,on=original;uint32_t offMask=mask,onMask=mask;
        auto sticky=oracle(base,mask);
        if(supersedeFmacEntries<false>(off,offMask)!=sticky || offMask!=mask) return 1;
        if(supersedeFmacEntries<true>(on,onMask)!=sticky) return 2;
        uint64_t actualDrain=0;
        for(uint32_t i=0;i<on.size();++i) {
            if(bool(onMask&(1u<<i))!=on[i].valid) return 3;
            if(on[i].valid) actualDrain=std::max(actualDrain,on[i].readyCycle);
            if(original[i].valid && original[i].writesClip && !on[i].valid) return 4;
        }
        if(actualDrain!=drain) return 5;
        State a,b,c;a.status|=sticky;b=a;c=a;
        for(uint32_t cycle=0;cycle<16;++cycle) {
            retire(base,a,cycle);retire(off,b,cycle);retire(on,c,cycle);
            if(a.mac!=c.mac || a.status!=c.status || a.clip!=c.clip || a.mac!=b.mac || a.status!=b.status || a.clip!=b.clip) return 6;
            ++checks;
        }
    }
    std::printf("PASS visible-retirement-checks=%llu FSSET-guard-cases=%llu; MAC/STATUS/sticky/CLIP and final drain deadline match\n",(unsigned long long)checks,(unsigned long long)guarded);
}
'''
(out/'witness.cpp').write_text(prefix+helper+body)
(out/'identity.json').write_text(json.dumps({'helper_sha256':hashlib.sha256(helper.encode()).hexdigest(),'source_sha256':hashlib.sha256(s.encode()).hexdigest(),'scope':'Actual extracted helper versus independent scalar supersession, each retirement cycle, final drain and CLIP survival; FSSET caller guard'},indent=2))
cmd=r'''@echo off
setlocal
set "PATH=%PATH:"=%"
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if errorlevel 1 exit /b %errorlevel%
cd /d D:\Project\compatbilty\artifacts\experiments\vu-flag-coalescing\retirement-witness
"C:\Program Files\LLVM\bin\clang-cl.exe" /nologo /std:c++20 /O2 /EHsc witness.cpp /Fowitness.obj /Fewitness.exe
if errorlevel 1 exit /b %errorlevel%
witness.exe
'''
(ROOT/'lab/check-flag-retirement.cmd').write_text(cmd)
print('Prepared extracted helper retirement witness')
