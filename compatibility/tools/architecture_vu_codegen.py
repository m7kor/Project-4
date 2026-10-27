"""Profile-guided AOT coverage experiment; generate from existing semantic metadata.

No GoW/PCSX2 source is imported. Current reference tables remain the default.
Only the actual dominant image receives additional independent compiled blocks.
"""
from pathlib import Path
import hashlib,importlib.util,json,re,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'lab/architecture-aot-02'
out.mkdir(exist_ok=False);source=ROOT/'engines/project4/ps2xRuntime/src/lib/vu';local=out/'src';local.mkdir();(local/'generated').mkdir()
freeze=ROOT/'artifacts/architecture/freeze-01'
assert hashlib.sha256((freeze/'ps2_vu1_core.cpp').read_bytes()).hexdigest()=='9d57a24024632c1beeb84bc11eb4fc1d968598092e920b52b5093eb9bee347df'
for p in source.iterdir():
 if p.is_file() and p.suffix in ('.cpp','.h','.inl'):shutil.copyfile(p,local/p.name)
# Use the unchanged Phase4 core, isolating AOT coverage from the disabled FMAC experiment.
core=ROOT/'artifacts/phase5/fmac-01/before-core.cpp';assert hashlib.sha256(core.read_bytes()).hexdigest()=='48077ba02c66e8d0dc0efe6182db011ca2d7575db19e6b4f1e03412dfd207f98'
shutil.copyfile(core,local/'ps2_vu1_core.cpp')
spec=importlib.util.spec_from_file_location('existing_vu_codegen',ROOT/'tools/vu1_fusion_codegen.py');gen=importlib.util.module_from_spec(spec);spec.loader.exec_module(gen)
base_path=Path('C:/Project/PS2redmption/artifacts/tool-audit/20261016/vu-clean-blocks-before/vu1_compiled_programs.inc')
base=base_path.read_text(encoding='utf-8');reference=(freeze/'vu1_compiled_programs.inc').read_text(encoding='utf-8')
key='53c46ebcaf7db574';heads={0,0x50,0xa0,0xc0,0x498,0x7c8,0x1408,0x4000}
pattern=r'CompiledPairFn c_'+key+r'\[2048\] = \{(.*?)\n    \};'
prior=re.findall(r'&([^,\s]+)',re.search(pattern,reference,re.S)[1]);assert len(prior)==2048
# Only compile runs which the reference executes pair-by-pair. Never cross an
# existing optimized entry: its sequence/stale-scoreboard accounting is distinct.
for i,entry in enumerate(prior):
 if not entry.startswith('step<'):heads.update([i*8,(i+1)*8])
cuts=sorted(heads);spans=[(a,b) for a,b in zip(cuts,cuts[1:]) if b-a>=16 and all(prior[i].startswith('step<') for i in range(a//8,b//8))]
regions={key:[list(x) for x in spans]}
# Exact per-pair bookkeeping is deliberately retained in newly compiled ranges.
generated,rows=gen.generate(base,(source/'ps2_vu1_upper.cpp').read_text(),(source/'ps2_vu1_step.inl').read_text(),regions,64,fused=False)
begin=generated.index('    static int clean_'+key+'_');end=generated.index('\n};\n\nstatic const VU1Interpreter::CompiledPairFn *vu1FindCompiledProgram',begin)
extra=generated[begin:end].replace('CompiledPairFn c_'+key+'[','CompiledPairFn a_'+key+'[')
table_pattern=r'(CompiledPairFn a_'+key+r'\[2048\] = \{)(.*?)(\n    \};)'
new=re.findall(r'&([^,\s]+)',re.search(table_pattern,extra,re.S)[2]);assert len(new)==2048
merged=[b if not b.startswith('step<') else a for a,b in zip(prior,new)]
assert all(a==b for a,b in zip(prior,merged) if not a.startswith('step<'))
table='\n'+''.join('        &'+entry+',\n' for entry in merged)
extra=re.sub(table_pattern,lambda m:m[1]+table+m[3],extra,flags=re.S)
assert 'clean_'+key+'_' not in reference and len(rows)>0
marker='\n};\n\nstatic const VU1Interpreter::CompiledPairFn *vu1FindCompiledProgram';assert reference.count(marker)==1
candidate=reference.replace(marker,'\n'+extra+marker)
needle='    case 0x'+key+'ull: return clean ? VU1CompiledPrograms::c_'+key+' : VU1CompiledPrograms::t_'+key+';'
assert candidate.count(needle)==1
candidate=candidate.replace(needle,'    case 0x'+key+'ull: { static const bool aot = [] { const char *p=std::getenv("PS2X_VU1_AOT_COVERAGE"); return p && *p==\'1\'; }(); return clean && aot ? VU1CompiledPrograms::a_'+key+' : (clean ? VU1CompiledPrograms::c_'+key+' : VU1CompiledPrograms::t_'+key+'); }')
target=local/'generated/vu1_compiled_programs.inc';target.write_text(candidate,encoding='utf-8',newline='\n')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
identity={'hypothesis':'Expand true native block coverage for the measured dominant image and MSCNT landing PCs; retain original scheduling and fallback',
 'regions':regions,'native_blocks':len(rows),'rows':rows,'reference_include_sha256':sha(freeze/'vu1_compiled_programs.inc'),
 'input_files':{str(p):sha(p) for p in [base_path,ROOT/'tools/vu1_fusion_codegen.py',Path(__file__),core]},
 'generated_files':{str(p):sha(p) for p in local.rglob('*') if p.is_file()},'default_enabled':False,'generated_game_source_is_private':True}
(out/'generation.json').write_text(json.dumps(identity,indent=2));print('Generated',len(rows),'additional native blocks; reference preserved; defaultOFF')
