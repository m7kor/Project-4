"""Reuse deterministic operand cases against independent reference/candidate."""
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]
reference=ROOT/'lab/architecture-aot-state-02/state_probe.exe'
for path,digest in json.loads((reference.parent/'identity.json').read_text()).items():
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest,path
script=ROOT/'tools/architecture_fuzz.py';text=script.read_text()
text=text.replace("ROOT/'artifacts/architecture/operand-fuzz-01'","ROOT/'artifacts/host-boundary/operand-fuzz-01'")
text=text.replace("binary=ROOT/'lab/architecture-aot-state-02/state_probe.exe'","binary=ROOT/'lab/host-boundary-state-01/state_probe.exe'")
text=text.replace("[str(binary),str(fixtures)","[str(reference if mode=='0' else binary),str(fixtures)")
text=text.replace("'PS2X_VU1_AOT_COVERAGE':mode","'PS2X_VU1_AOT_COVERAGE':'0'")
exec(compile(text,str(script),'exec'),{'__file__':str(script),'__name__':'__main__','reference':reference})
