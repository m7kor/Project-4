"""Reuse the existing linked-code inspection for exact new binary identities."""
from pathlib import Path
import hashlib,sys,json,re,collections
ROOT=Path(__file__).resolve().parents[1]
choices={'game':('lab/architecture-input-01/ps2EntryRunner.exe','f8eb7e8e608a8f38f306f15e93fee7027b3d3f797ee9628cc31b7eca7cca727c'),
         'candidate':('lab/host-boundary-inline-01/ps2x_vu1_bench.exe','ad1d9722779cc171366e8123f7339dc74151971a3694d0adea0d9fb5f50f9d7e'),
         'baseline-game':('lab/phase4-game-03/ps2EntryRunner.exe','fa528081c83a6ef3c54d050c4a103d5527afb99e708987e2640d462a32e08f53'),
         'candidate-game':('lab/host-boundary-game-01/ps2EntryRunner.exe','55b31f4f2470c06ebcd3f39cf11f223bcefb644efa6a10707d2e1f7a1103f87e')}
which=sys.argv[1];relative,digest=choices[which]
script=ROOT/'tools/architecture_host_code.py';text=script.read_text().replace("ROOT/'artifacts/architecture'","ROOT/'artifacts/host-boundary'")
text=text.replace("exe=ROOT/'lab/shared-link/ps2x_vu1_bench.exe'",'exe=ROOT/'+repr(relative))
old="assert sha(exe)==sha(baseline)=='75f8c403b362f87403714d4d1808b9549b767302f896e1d73de51cb50b49dfd5'";assert text.count(old)==1;text=text.replace(old,'assert sha(exe)=='+repr(digest))
sys.argv=[str(script),which+'-hostcode-01'];context={'__file__':str(script),'__name__':'__main__'};exec(compile(text,str(script),'exec'),context)
if which=='game':
    samples=json.loads((ROOT/'artifacts/host-boundary/live-profile-03/sampler.samples.json').read_text())
    instructions=context['instructions'];base=instructions[0][0];lookup={a-base:(op,args) for a,op,args in instructions};rows=[];counts=collections.Counter()
    for sample in samples['rows']:
        if sample['function']!='VU1CompiledPrograms::fused_770ea85198e8e87f_12b8':continue
        offset=sample['displacement'];instruction=lookup.get(offset)
        if not instruction:kind='unmapped'
        else:
            op,args=instruction
            if re.search(r'%(?:rsp|rbp)\b',args):kind='stack-memory-or-stack-address'
            elif op.startswith('call'):kind='call-site'
            elif op.startswith(('j','cmov','set','cmp','test')):kind='branch-or-condition'
            elif '(' in args:kind='other-memory-or-address'
            else:kind='register-operation'
        counts[kind]+=sample['count'];rows.append({'count':sample['count'],'offset':offset,'instruction':instruction,'kind':kind})
    report={'sampled_target_leaf_instructions':sum(counts.values()),'categories':dict(counts),'rows':rows,
            'scope':'Sample IP maps to exact linked instruction. A stack access is not proof of a spill; memory operands include addresses, and instruction category is not stall attribution.'}
    (context['out']/'sampled-instructions.json').write_text(json.dumps(report,indent=2));print('Sample IP categories',dict(counts))
