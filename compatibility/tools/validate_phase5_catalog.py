"""Execute the complete pinned snapshot catalog once, not merely inventory it."""
from pathlib import Path
import hashlib,json,os,re,shutil,subprocess,time,sys
ROOT=Path(__file__).resolve().parents[1]
requested_out=next((a.split('=',1)[1] for a in sys.argv[1:] if a.startswith('--out=')),None)
out=Path(requested_out).resolve() if requested_out else ROOT/'artifacts/phase5/catalog-01'
assert out.is_relative_to(ROOT/'artifacts');out.mkdir(exist_ok=False)
reuse=next((a.split('=',1)[1] for a in sys.argv[1:] if a.startswith('--reuse-fixtures=')),None)
fixtures=Path(reuse).resolve() if reuse else out/'fixtures'
if reuse:assert fixtures.is_relative_to(ROOT/'artifacts') and fixtures.is_dir()
else:fixtures.mkdir()
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
catalog=json.loads((ROOT/'artifacts/phase4/vu-fixture-inventory.json').read_text());assert not catalog['invalid'] and len(catalog['valid'])==3200
for number,row in enumerate(catalog['valid']):
    assert sha(row['path'])==row['sha256'];target=fixtures/f'vu1snap_{number:05}.bin'
    if reuse:assert sha(target)==row['sha256']
    else:shutil.copyfile(row['path'],target)
(out/'source-manifest.json').write_text(json.dumps(catalog['valid'],indent=2))
probe=ROOT/'lab/phase5-fmac-state-01/state_probe.exe'
probe_name=next((a.split('=',1)[1] for a in sys.argv[1:] if a.startswith('--probe-dir=')),None)
if probe_name:probe=(ROOT/'lab'/probe_name/'state_probe.exe').resolve();assert probe.is_relative_to(ROOT/'lab')
for path,digest in json.loads((probe.parent/'identity.json').read_text()).items():assert sha(path)==digest
env={k:v for k,v in os.environ.items() if not k.upper().startswith('PS2X_')};env.update(PS2X_VU1_CLEAN_BLOCKS='1',PS2X_VU1_FUSED='1');env['PATH']=str(ROOT/'artifacts/runs/baseline-01/guest')+os.pathsep+env['PATH']
rows=[];start=time.monotonic()
for mode in ('0','1'):
    log=out/(mode+'.states.txt')
    p=subprocess.run([str(probe),str(fixtures),'--budget','65536','--resumes','0','--repeat','1','--gif-hash'],cwd=out,env={**env,'PS2X_VU1_FMAC_CLASSIFY':mode,'PS2X_VU1_PIPELINE_STATE_LOG':str(log)},capture_output=True,text=True,timeout=240)
    (out/(mode+'.stdout.txt')).write_text(p.stdout);(out/(mode+'.stderr.txt')).write_text(p.stderr);assert p.returncode==0,(mode,p.stderr[-500:])
    row={'mode':mode,'checkpoints':len(log.read_text().splitlines()),'pipeline_sha256':sha(log)}
    for key,pattern in [('state',r' result=([a-f0-9]{16})'),('cycles',r'vu1_cycles=(\d+)'),('gif_packets',r'gif_packets=(\d+)'),('gif_result',r'gif_result=([a-f0-9]{16})')]:row[key]=re.search(pattern,p.stdout)[1]
    rows.append(row);print('Full catalog mode completed',mode,flush=True)
assert rows[0]['checkpoints']==3200 and {k:v for k,v in rows[0].items() if k!='mode'}=={k:v for k,v in rows[1].items() if k!='mode'}
(out/'report.json').write_text(json.dumps({'passed':True,'rows':rows,'seconds':time.monotonic()-start,'probe_sha256':sha(probe),'images':catalog['counts'],'scope':'All3200 pinned snapshots actually executed at budget65536; smaller-budget800 workload remains separate. Full state/pipelines/VU memory and GIF order compared.'},indent=2));print('All3200 snapshot executions matched in both modes',flush=True)
