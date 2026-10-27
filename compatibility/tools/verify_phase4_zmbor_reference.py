"""Re-execute pinned Phase7 binaries, source-equivalent to current main; no rebuild claim."""
from pathlib import Path
import collections,hashlib,json,os,shutil,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1];REF=Path('D:/Project/Zmbor/wt-phase7');SOURCE=ROOT/'lab/zmbor-phase4-src'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    out=ROOT/'artifacts/phase4/zmbor-reference';out.mkdir(exist_ok=False);start=time.monotonic()
    manifest=json.loads(Path('D:/Project/Zmbor/hwtest_work/p7/p7_gate4.manifest.json').read_text());commit=manifest['commit']
    assert subprocess.check_output(['git','-C',str(REF),'rev-parse','HEAD'],text=True).strip()==commit
    assert not subprocess.check_output(['git','-C',str(REF),'status','--porcelain','--untracked-files=no'],text=True).strip()
    assert not subprocess.check_output(['git','-C',str(SOURCE),'diff','--name-only',commit,'HEAD','--','ps2xRuntime','ps2xRecomp','ps2xIOP','ps2xTest','CMakeLists.txt','cmake'],text=True).strip()
    build=REF/'build';binaries=out/'binaries';binaries.mkdir();env={k:v for k,v in os.environ.items() if not k.upper().startswith('PS2X_')};(out/'temp').mkdir();env.update(TEMP=str(out/'temp'),TMP=str(out/'temp'),PS2X_HIDDEN_WINDOW='1')
    for name,digest in manifest['binaries'].items():assert sha(build/name)==digest
    unit=binaries/'ps2x_tests.exe';shutil.copy2(build/'ps2xTest/ps2x_tests.exe',unit)
    u=subprocess.run([unit],cwd=SOURCE,env=env,capture_output=True,text=True,timeout=180);(out/'unit.stdout.txt').write_text(u.stdout);(out/'unit.stderr.txt').write_text(u.stderr);assert u.returncode==0
    tests=[]
    for name,digest in manifest['program_executables'].items():
        if not name.startswith('ps2x_hw_'):continue
        original=build/'ps2xTest/e2e'/name;assert sha(original)==digest;exe=binaries/name;shutil.copy2(original,exe)
        id=name.removeprefix('ps2x_hw_').removesuffix('.exe');work=out/id;work.mkdir();elf=ROOT/'artifacts/phase2/hardware-inputs'/(id+'.elf');expected=elf.with_suffix('.expected')
        p=subprocess.run([sys.executable,SOURCE/'tools/hwtest/hwtest.py','run','--runner',exe,'--elf',elf,'--expected',expected,'--result',work/'result.json','--timeout','15'],cwd=work,env=env,capture_output=True,text=True,timeout=25)
        (work/'driver.log').write_text(p.stdout+p.stderr);r=json.loads((work/'result.json').read_text());r.update(id=id,runner_sha256=digest,expected_sha256=sha(expected));tests.append(r);print(id,r['status'],flush=True)
    counts=dict(collections.Counter(r['status'] for r in tests));assert len(tests)==55
    report={'compiled_commit':commit,'current_main':subprocess.check_output(['git','-C',str(SOURCE),'rev-parse','HEAD'],text=True).strip(),'source_equivalent':True,'unit_exit':u.returncode,'unit_sha256':sha(unit),'tests':tests,'counts':counts,'seconds':time.monotonic()-start,'scope':'Fresh execution of hash-checked previously built cleanPhase7 binaries; NOT a new build or Project4 candidate hardware result'};(out/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(counts))
if __name__=='__main__':main()
