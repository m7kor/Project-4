"""Focused ASan/UBSan helper probe; not a sanitized full RE4 runtime."""
from pathlib import Path
import hashlib,json,os,subprocess,shutil
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'lab/phase5-fmac-sanitizers-01';out.mkdir(exist_ok=False)
source=ROOT/'engines/project4/ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp';text=source.read_text(encoding='utf-8')
helper=text[text.index('bool ps2Vu1ClassifyNormalFmac('):text.index('static const bool fmacClassifyEnabled')]
code=out/'helper.cpp';code.write_text('#include <cstdint>\n#include <cstring>\n#include <emmintrin.h>\n#define PS2X_FMAC_CLASSIFY_SSE2 1\n'+helper,encoding='utf-8')
temp=out/'temp';temp.mkdir();env={**os.environ,'TEMP':str(temp),'TMP':str(temp)};env['PATH']='C:/Program Files/LLVM/bin'+os.pathsep+env['PATH']
exe=out/'witness.exe';command=['C:/Program Files/LLVM/bin/clang++.exe','-std=c++20','-O2','-fsanitize=address,undefined','-fno-sanitize-recover=all',str(code),str(ROOT/'tests/phase5_fmac_classify_witness.cpp'),'-o',str(exe)]
p=subprocess.run(command,cwd=out,env=env,capture_output=True,text=True,timeout=90);(out/'build.log').write_text(p.stdout+p.stderr)
report={'scope':'Standalone actual bit-classifier helper only; full engine/game is not sanitizer-built','compiler_returncode':p.returncode,'available':p.returncode==0,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
if p.returncode==0:
    resource=Path(subprocess.check_output(['C:/Program Files/LLVM/bin/clang++.exe','-print-resource-dir'],text=True).strip())
    runtime=resource/'lib/windows/clang_rt.asan_dynamic-x86_64.dll'
    if runtime.is_file():shutil.copy2(runtime,out/runtime.name)
    r=subprocess.run([str(exe)],cwd=out,env=env,capture_output=True,text=True,timeout=60);(out/'run.log').write_text(r.stdout+r.stderr)
    report.update(returncode=r.returncode,passed=r.returncode==0,binary_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),result=r.stdout)
else:report.update(passed=False,blocker=p.stderr[-1500:])
(ROOT/'artifacts/phase5/fmac-sanitizers-report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
raise SystemExit(0 if report.get('passed') else 1)
