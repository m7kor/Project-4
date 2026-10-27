"""Prove identical decoded regions and reuse their existing specialized blocks."""
from pathlib import Path
import importlib.util,hashlib,json,re,shutil
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'artifacts/experiments/vu-shared-regions';out.mkdir(exist_ok=False)
vu=ROOT/'engines/project4/ps2xRuntime/src/lib/vu'
base=Path('C:/Project/PS2redmption/artifacts/tool-audit/20261016/vu-clean-blocks-before/vu1_compiled_programs.inc').read_text(encoding='utf-8')
regions=json.loads(Path('C:/Project/PS2redmption/tmp/diag/claude-vu1/regions-extended.json').read_text())
spec=importlib.util.spec_from_file_location('codegen',ROOT/'tools/vu1_fusion_codegen.py')
gen=importlib.util.module_from_spec(spec);spec.loader.exec_module(gen)
args=(base,(vu/'ps2_vu1_upper.cpp').read_text(),(vu/'ps2_vu1_step.inl').read_text(),regions,64)
prior,prior_rows=gen.generate(*args,fused=True)
target=vu/'generated/vu1_compiled_programs.inc'
assert prior.encode()==target.read_bytes(), 'Existing candidate must reproduce exactly before extending it'
candidate,rows=gen.generate(*args,fused=True,share_identical=True)
def tables(text,kind):
    return {k:re.findall(r'&([^,\s]+)',v) for k,v in re.findall(r'CompiledPairFn '+kind+r'_([0-9a-f]{16})\[2048\] = \{(.*?)\n    \};',text,re.S)}
generic=tables(prior,'t');old=tables(prior,'c');new=tables(candidate,'c')
aliases={r['hash']:r['alias_of'] for r in rows if 'alias_of' in r}
assert len(aliases)==2
for key,entries in new.items():
    assert len(entries)==2048
    source=aliases.get(key,key)
    for index,entry in enumerate(entries):
        if entry.startswith(('clean_','fused_')):
            block=next(r for r in rows if r['hash']==key and r['begin']==index*8)
            a,b=block['begin']//8,block['end']//8
            assert generic[key][a:b]==generic[source][a:b],(key,index)
            assert entry==old[source][index]
        else:assert entry==generic[key][index],(key,index,'fallback changed')
shutil.copy2(target,out/'before.inc')
(out/'generation.json').write_text(json.dumps({'sha256':hashlib.sha256(candidate.encode()).hexdigest(),'blocks':rows},indent=2))
record={'scope':'Reuse existing exact same-PC decoded regions; no math or scheduling changes',
        'aliases':aliases,'original_blocks':len(prior_rows),'covered_blocks':len(rows),
        'new_function_bodies':0,'all_alias_blocks_exact':True,'all_outside_entries_unchanged':True,
        'before_sha256':hashlib.sha256(prior.encode()).hexdigest(),'after_sha256':hashlib.sha256(candidate.encode()).hexdigest(),
        'status':'Experimental; tests and real-game comparisons required'}
(out/'proof.json').write_text(json.dumps(record,indent=2))
target.write_bytes(candidate.encode())
print(json.dumps(record,indent=2))
