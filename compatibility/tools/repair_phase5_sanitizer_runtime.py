"""Retest the identical sanitizer binary with its matching LLVM DLL locally."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'lab/phase5-fmac-sanitizers-02';out.mkdir(exist_ok=False)
previous=json.loads((ROOT/'artifacts/phase5/fmac-sanitizers-report.json').read_text())
original=ROOT/'lab/phase5-fmac-sanitizers-01/witness.exe';sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert sha(original)==previous['binary_sha256']
compiler='C:/Program Files/LLVM/bin/clang++.exe'
resource=Path(subprocess.check_output([compiler,'-print-resource-dir'],text=True).strip())
runtime=resource/'lib/windows/clang_rt.asan_dynamic-x86_64.dll';assert runtime.is_file()
shutil.copy2(original,out/original.name);shutil.copy2(runtime,out/runtime.name)
temp=out/'temp';temp.mkdir();env={**os.environ,'TEMP':str(temp),'TMP':str(temp),'PATH':str(out)+os.pathsep+os.environ['PATH']}
r=subprocess.run([str(out/'witness.exe')],cwd=out,env=env,capture_output=True,text=True,timeout=90);(out/'run.log').write_text(r.stdout+r.stderr)
report={'passed':r.returncode==0,'returncode':r.returncode,'binary_sha256':sha(out/'witness.exe'),'same_binary_as_failed_loader_run':sha(out/'witness.exe')==previous['binary_sha256'],'runtime_source':str(runtime),'runtime_sha256':sha(runtime),'source_sha256':previous['source_sha256'],'result':r.stdout,'stderr':r.stderr,'scope':'Identical ASan+UBSan helper binary, matching LLVM runtime DLL copied into isolated directory. No system DLL/PATH changes; not a sanitized full game.'}
(ROOT/'artifacts/phase5/fmac-sanitizers-repair.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
raise SystemExit(0 if report['passed'] else 1)
