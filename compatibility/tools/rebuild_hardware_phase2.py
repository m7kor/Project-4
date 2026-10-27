"""Fresh hardware baseline from the exact archived Zmbor integration revision."""
from pathlib import Path
import hashlib,json,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'lab/zmbor-phase2';ART=ROOT/'artifacts/phase2';BUILD=WORK/'build';SRC=WORK/'src'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    start=time.monotonic();identity=json.loads((WORK/'source-identity.json').read_text())
    assert identity['source_commit']=='00173a2d4a9d740adac2d5a1df5f1cf1ecb9abcb'
    generated=ART/'hardware-generated';assert not generated.exists(), 'Use a new build generation; do not overwrite results'
    inputs=json.loads((ART/'hardware-inputs.json').read_text());assert len(inputs)==55
    recompiler=BUILD/'ps2xRecomp/ps2_recomp.exe';assert recompiler.exists()
    subprocess.run([sys.executable,str(SRC/'tools/hwtest/hwtest.py'),'prepare','--tests',str(ART/'hardware-inputs'),'--recompiler',str(recompiler),'--out',str(generated)],check=True)
    assert len(list(generated.glob('*/hwtest.cmake')))==55,'Some hardware ELFs failed recompilation'
    subprocess.run(['cmake','-S',str(SRC),'-B',str(BUILD),'-DPS2X_HWTEST_GENERATED='+str(generated)],check=True)
    targets=['ps2x_hw_'+r['id'] for r in inputs]
    subprocess.run(['cmake','--build',str(BUILD),'--target',*targets,'--parallel','4'],check=True)
    results=[]
    out=ART/'hardware-current';out.mkdir(exist_ok=False)
    historic=json.loads((ROOT/'artifacts/hardware/summary.json').read_text())['tests'];historic={r['id']:r for r in historic}
    for row in inputs:
        name='ps2x_hw_'+row['id'];runner=BUILD/'ps2xTest/e2e'/(name+'.exe');work=out/name;work.mkdir()
        elf=ART/'hardware-inputs'/(row['id']+'.elf');expected=elf.with_suffix('.expected')
        assert sha(expected)==row['expected_sha256']
        p=subprocess.run([sys.executable,str(SRC/'tools/hwtest/hwtest.py'),'run','--runner',str(runner),'--elf',str(elf),'--expected',str(expected),'--result',str(work/'result.json'),'--timeout','15'],cwd=work,capture_output=True,text=True,timeout=25)
        (work/'driver.log').write_text(p.stdout+p.stderr)
        result=json.loads((work/'result.json').read_text());result.update(id=name,source_commit=identity['source_commit'],runner=str(runner),runner_sha256=sha(runner),elf=str(elf),elf_sha256=sha(elf),expected=str(expected),expected_sha256=sha(expected),tty_sha256=sha(work/'run.tty.txt'))
        old=historic[name];result['historical_status']=old['status']
        result['classification']='exact' if result['status']=='PASS' else 'known-mismatch' if result['status']=='MISMATCH' and old['status']=='MISMATCH' and sha(work/'run.tty.txt')==sha(ROOT/'artifacts/hardware'/name/'run.tty.txt') else 'new-regression'
        results.append(result);print(name,result['status'],result['classification'],flush=True)
        (out/'progress.json').write_text(json.dumps(results,indent=2))
    import collections
    report={'source_identity':identity,'recompiler_sha256':sha(recompiler),'runtime_sha256':sha(BUILD/'ps2xRuntime/ps2_runtime.lib'),'compile_commands_sha256':sha(BUILD/'compile_commands.json'),'tests':results,'counts':dict(collections.Counter(r['classification'] for r in results)),'seconds':time.monotonic()-start,'scope':'All55 freshly recompiled and linked against newly built00173a2 runtime. No historical executables used.'}
    (out/'catalog.json').write_text(json.dumps(report,indent=2));print(json.dumps(report['counts']),flush=True)
if __name__=='__main__':main()
