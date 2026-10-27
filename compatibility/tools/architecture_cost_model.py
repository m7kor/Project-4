"""Measured diagnostic costs, explicit unknowns and non-overstated Amdahl bounds."""
from pathlib import Path
import collections,hashlib,json,re,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'reference-tools/tools/diagnostics'))
from game_speed_compare import endpoint
run=ROOT/'artifacts/runs/architecture-profile-01';out=ROOT/'artifacts/architecture/cost-model.json';assert not out.exists()
identity=json.loads((run/'report.json').read_text());assert identity['test_saves_unchanged']
rows=[json.loads(x) for x in (run/'diagnostics/vu-profile/profile.jsonl').read_text().splitlines()]
closed={x['index'] for x in rows if x['kind']=='end'};windows=[x for x in rows if x['kind']=='window' and x['index'] in closed]
groups=[x for x in rows if x['kind']=='group' and x['window'] in closed]
assert sum(x['calls'] for x in groups)==sum(x['calls'] for x in windows)
first=min(x['first_ee'] for x in windows);last=max(x['last_ee'] for x in windows)
states=[json.loads(x) for x in (run/'diagnostics/state.jsonl').read_text().splitlines()]
a,_=endpoint(states,first);b,_=endpoint(states,last);wall=b-a
rank=collections.defaultdict(lambda:collections.Counter())
for x in groups:
 c=rank[(x['code_fnv1a64'],x['start_pc'],x['resume'])]
 for k in ('calls','cycles','nanoseconds','compiled_calls'):c[k]+=x[k]
ranked=[{'image':k[0],'pc':hex(k[1]),'resume':k[2],**v} for k,v in sorted(rank.items(),key=lambda x:-x[1]['nanoseconds'])]
ns=sum(x['nanoseconds'] for x in windows);fraction=ns/1e9/wall
samples={}
for i in range(3):
 p=ROOT/f'artifacts/architecture/profile-01/{i}.stdout.txt';text=p.read_text();parts=text.split('--- inclusive time');leaf=parts[0].split('--- self time')[-1]
 parse=lambda s:[{'percent_of_sampled_thread':float(p),'samples':int(n),'function':f} for p,n,f in re.findall(r'^\s*([\d.]+)%\s+(\d+)\s+(.+)$',s,re.M)]
 samples[str(i)]={'self':parse(leaf),'inclusive':parse(parts[1]) if len(parts)>1 else [],'report':str(p)}
unavailable=['Per-subsystem allocation counts and copied bytes','Lock-contention durations','Exact per-instruction compiled-versus-interpreted cycles','GPU timestamps and guest frame pacing','Host loopback A/V latency','Native IOP-service time separated from emulated IOP','Complete unified EE/IOP/VU/audio/DMA event ordering']
result={'scope':'One representative loaded gameplay diagnostic, including aim/fire/inventory. Profiling and capture perturb execution; NOT controlled performance acceptance',
 'identity':identity,'first_ee':first,'last_ee':last,'completed_profile_windows':len(windows),'diagnostic_wall_seconds':wall,
 'vu_inclusive_seconds':ns/1e9,'vu_inclusive_wall_fraction':fraction,'vu_calls':sum(x['calls'] for x in windows),
 'vu_calls_per_guest_field':sum(x['calls'] for x in windows)/(last-first),
 'vu_cycles':sum(x['cycles'] for x in windows),'compiled_table_calls':sum(x['compiled_calls'] for x in groups),
 'coverage_contract':'usesCompiledProgram means a table was selected, not every instruction was a fully specialized native block',
 'ranked_vu_entries':ranked,'thread_samples':samples,'unavailable':{k:None for k in unavailable},
 'amdahl':{'contract':'VU measured host duration includes GIF work and possible waits. Treat elimination bounds as hypothetical upper bounds; thread sample percentages cannot be substituted for a whole-wall fraction.',
  'hypothetical_2x_of_measured_vu_envelope':1/(1-fraction+fraction/2),'hypothetical_elimination_of_entire_measured_vu_envelope':1/(1-fraction)},
 'decisions':{'native_vu':'Prototype expanded AOT blocks with continuation entrypoints, preserving semantic bodies and original fallback',
 'threaded_vu':'Defer: overlap and EE-visible memory/IRQ barrier costs unmeasured; existing ps2_mtvu.h contains declarations only',
 'iop':'Defer major service rewrite: no dominant measured IOP cost in current scene',
 'renderer':'Retain paraLLEl-GS; sampled renderer worker mostly waits; no evidence for replacement'},
 'source_manifest':'artifacts/architecture/freeze-01/manifest.json','profile_source_sha256':hashlib.sha256((ROOT/'engines/project4/ps2xRuntime/src/lib/ps2_vu1_execution.cpp').read_bytes()).hexdigest()}
assert 0<fraction<1
out.write_text(json.dumps(result,indent=2));print(json.dumps({k:result[k] for k in ['diagnostic_wall_seconds','vu_inclusive_seconds','vu_inclusive_wall_fraction','vu_calls','compiled_table_calls','amdahl']},indent=2))
