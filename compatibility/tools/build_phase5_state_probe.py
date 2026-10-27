"""Extend existing replay tests with test-only, field-wise pipeline checkpoints."""
from pathlib import Path
import hashlib,json,re,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'lab'/('phase5-state-probe-03' if len(sys.argv)==1 else sys.argv[1]);out.mkdir(exist_ok=False)
runtime=ROOT/'lab'/('phase5-pipeline-01' if len(sys.argv)<3 else sys.argv[2])
observer=ROOT/'tests'/('phase5_pipeline_state_v2.inl' if len(sys.argv)>3 and sys.argv[3]=='v2' else 'phase5_pipeline_state.inl')
original=ROOT/'engines/project4/ps2xTest/src'
bench=(original/'vu1_bench.cpp').read_text(encoding='utf-8')
prefix='''#include <array>
#include <cstdint>
#include <cstring>
#include <vector>
#include <memory>
#define private public
#include "runtime/ps2_vu1.h"
#undef private
'''
bench=prefix+bench
marker='#include "vu1_command_replay.inl"';assert bench.count(marker)==1
bench=bench.replace(marker,'#include "'+str(observer).replace('\\','/')+'"\n#include "'+str(ROOT/'tests/phase5_pipeline_random.inl').replace('\\','/')+'"\n'+marker)
marker='int main(int argc, char **argv)\n{';assert bench.count(marker)==1
bench=bench.replace(marker,marker+'\n    if (argc==2 && std::string(argv[1])=="--phase5-random") return phase5RandomRetirement();')
# Checkpoint after Start and every separate Continue API call, not just final state.
begin=bench.index('            // Exercise separate run/resume');end=bench.index('            seconds +=',begin)
region=bench[begin:end];body_start=region.index('                if (detachedExecutor)')
loop=region[:body_start]+'            {\n'+region[body_start:]+'                phase5Checkpoint(vu1, memory.getVU1Data());\n            }\n'
bench=bench[:begin]+'            phase5Checkpoint(vu1, memory.getVU1Data());\n'+loop+bench[end:]
commands=(original/'vu1_command_replay.inl').read_text(encoding='utf-8')
marker='                seconds += std::chrono::duration<double>';assert commands.count(marker)==1
commands=commands.replace(marker,'                phase5Checkpoint(*vu, memory.getVU1Data());\n'+marker)
(out/'vu1_command_replay.inl').write_text(commands,encoding='utf-8')
source=out/'state_probe.cpp';source.write_text(bench,encoding='utf-8')
db=json.loads(Path('C:/Project/PS2redmption/core/out/build/compile_commands.json').read_text());row=next(r for r in db if Path(r['file']).name=='vu1_bench.cpp')
obj=out/'state_probe.obj';cmd=re.sub(r'/Fo(?:"[^"]+"|\S+)',lambda _: '/Fo"'+str(obj)+'"',row['command']);cmd=re.sub(r'/Fd(?:"[^"]+"|\S+)',lambda _: '/Fd"'+str(out/'compiler.pdb')+'"',cmd)
cmd=cmd[:cmd.rindex(' -c -- ')]+' -I"'+str(original)+'" -c -- "'+str(source)+'"';subprocess.run(cmd,cwd=out,check=True)
rsp=(runtime/'ps2x_vu1_bench.exe.rsp').read_text();old=next(p for p in re.findall(r'"([^"]+\.obj)"',rsp) if Path(p).name=='vu1_bench.cpp.obj');rsp=rsp.replace(old,str(obj))
for option,suffix in [('out',''),('pdb','.pdb'),('implib','.lib')]:rsp=re.sub('/'+option+r':"[^"]+"',lambda _: '/'+option+':"'+str(out/('state_probe.exe'+suffix))+'"',rsp)
(out/'link.rsp').write_text(rsp);subprocess.run(['C:/Program Files/LLVM/bin/lld-link.exe','@'+str(out/'link.rsp')],cwd=out,check=True)
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
(out/'identity.json').write_text(json.dumps({str(p):sha(p) for p in [out/'state_probe.exe',obj,source,out/'vu1_command_replay.inl',observer,ROOT/'tests/phase5_pipeline_state.inl',ROOT/'tests/phase5_pipeline_random.inl',runtime/'ps2_vu1_core.cpp.obj']},indent=2))
print('Full pipeline state observer built',flush=True)
