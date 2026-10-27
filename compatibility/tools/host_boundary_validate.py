"""Reuse all existing full-state cases against two genuinely different binaries."""
from pathlib import Path
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1]
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
reference_probe=ROOT/'lab/architecture-aot-state-02/state_probe.exe'
reference_unit=ROOT/'lab/phase4-suite-02/ps2x_tests.exe'
for path,h in json.loads((reference_probe.parent/'identity.json').read_text()).items():assert sha(path)==h,path
script=ROOT/'tools/architecture_validate.py';text=script.read_text()
old="out=ROOT/'artifacts/architecture'/('equivalence-01' if len(sys.argv)==1 else sys.argv[1]);assert out.parent==ROOT/'artifacts/architecture'"
new="out=ROOT/'artifacts/host-boundary'/('equivalence-01' if len(sys.argv)==1 else sys.argv[1]);assert out.parent==ROOT/'artifacts/host-boundary'"
assert text.count(old)==1;text=text.replace(old,new)
marker='def run(label,args,mode,exe=probe):\n';assert text.count(marker)==1
text=text.replace(marker,marker+" if mode=='0':exe=reference_unit if exe.name=='ps2x_tests.exe' else reference_probe\n")
text=text.replace("'PS2X_VU1_AOT_COVERAGE':mode","'PS2X_VU1_AOT_COVERAGE':'0'")
marker=" report['passed']=True";assert text.count(marker)==1
text=text.replace(marker," compare('new-commands1024',['--commands',ROOT/'artifacts/runs/architecture-input-clock-01/diagnostics/vu-commands','--repeat','1'])\n"+marker+"\n report['reference_probe_sha256']=sha(reference_probe);report['reference_unit_sha256']=sha(reference_unit);report['scope']='Independent Phase4 reference versus helper ABI candidate; all full-state fields retained; no AOT mode enabled'")
sys.argv=[str(script),'equivalence-01','host-boundary-inline-01','host-boundary-state-01']
exec(compile(text,str(script),'exec'),{'__file__':str(script),'__name__':'__main__','reference_probe':reference_probe,'reference_unit':reference_unit})
