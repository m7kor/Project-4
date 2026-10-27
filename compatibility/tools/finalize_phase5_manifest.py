"""Pin final source, tested binaries, protected files and evidence identities."""
from pathlib import Path
import hashlib,json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 out=ROOT/'artifacts/phase5'/('final-manifest-01.json' if len(sys.argv)==1 else sys.argv[1]);assert out.parent==ROOT/'artifacts/phase5' and not out.exists()
 protected={'lab/shared-link/ps2EntryRunner.exe':'e17998c7099f3bff2892529d7726836d9689b9af1d6cd091bfa5b29c9a88542a',
 'lab/phase4-game-03/ps2EntryRunner.exe':'fa528081c83a6ef3c54d050c4a103d5527afb99e708987e2640d462a32e08f53',
 'artifacts/runs/manual-20261024-112541-942897/guest/saves/cards/native-card-0.ps2':'ae9c30f7ec60b2cba2363fe38de568f9f6fcad61e204e65a82ad9e15619554d6'}
 for name,digest in protected.items():assert sha(ROOT/name)==digest,name
 expected=json.loads((ROOT/'artifacts/phase2/hardware-inputs.json').read_text());assert len(expected)==55
 for row in expected:assert sha(ROOT/f"artifacts/phase2/hardware-inputs/{row['id']}.expected")==row['expected_sha256'],row['id']
 files=list((ROOT/'tools').glob('*phase5*'))+list((ROOT/'tests').glob('*phase5*'))
 files += [ROOT/p for p in ('tools/replay_input_quality.py','tests/test_replay_input_quality.py','tools/run_lab.py','tools/lab_regression.py',
 'engines/project4/ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp','lab/phase5-game-02/ps2EntryRunner.exe',
 'lab/phase5-suite-02/ps2x_tests.exe','lab/phase5-fmac-state-v2-01/state_probe.exe','lab/phase5-fmac-01/ps2x_vu1_bench.exe')]
 for p in files:assert p.is_file(),f'Missing identity input: {p}'
 result={'files':{str(p.relative_to(ROOT)):sha(p) for p in files},'protected_verified':protected,'unchanged_hardware_expected_files':55,
 'public_source_commit':subprocess.check_output(['git','-C',str(ROOT/'lab/phase4-public-source'),'rev-parse','HEAD'],text=True).strip(),
 'lab_parent_commit':subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip(),
 'scope':'Working source hashes plus tested binary hashes; base commit alone does not identify inherited private changes',
 'promoted':False,'pushed':False,'evidence':{}}
 for name in ['artifacts/phase5/final-analysis-03/report.json','artifacts/phase5/save-reload-01.json',
 'artifacts/phase5/post-measurement-01/equivalence-v2/report.json','artifacts/phase5/post-measurement-01/catalog-v2/report.json',
 'artifacts/phase5/post-measurement-01/random-v2/report.json','artifacts/phase5/fmac-sanitizers-repair.json',
 'artifacts/regression/20261026T095604.995030Z/report.json','artifacts/regression/20261026T101932.882359Z/report.json']:
  result['evidence'][name]=sha(ROOT/name)
 result['scenario_checkpoints']=[]
 for label,ticks in [('phase5-save-03',[6600,10320,11400,12420]),('phase5-reload-01',[2040,3900]),
                     ('phase5-perf-6-1',[9840,10920,11220,12060,12540])]:
  run=ROOT/'artifacts/runs'/label;states={s['tick']:s for s in map(json.loads,(run/'diagnostics/state.jsonl').read_text().splitlines())}
  for tick in ticks:
   p=run/f'diagnostics/frame-{tick}.png';s=states[tick]
   result['scenario_checkpoints'].append({'run':label,'tick':tick,'ee':s['ee_vsync_tick'],'elapsed_seconds':s['elapsed_seconds'],
     'presentation':s['presentation_vsync_tick'],'frame_sha256':sha(p)})
  for p in [run/'identity.json',run/'report.json',run/'stderr.txt',run/'input.csv',*sorted((run/'live-commands').glob('*.json'))]:
   result['evidence'][str(p.relative_to(ROOT))]=sha(p)
 out.write_text(json.dumps(result,indent=2));print('Protected runners/card and all55 expected files unchanged; final identities pinned')
if __name__=='__main__':main()
