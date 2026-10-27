"""Private, offline-first compatibility checks. Never launches RE4 implicitly."""
from __future__ import annotations
import argparse,collections,datetime,hashlib,json,os,re,shutil,statistics,subprocess,sys,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GROUPS={'fast','vu','vif','dma','iop','ee','graphics','audio','hardware','integration','full','auto','mutations','semantics'}
ANSI=re.compile(r'\x1b\[[0-9;]*m')
ACCEPTED={'ps2EntryRunner.exe':'e17998c7099f3bff2892529d7726836d9689b9af1d6cd091bfa5b29c9a88542a',
 'ps2x_tests.exe':'48aff8704e05f14b67465f513fd795b3d0ae542ba844ddd5ac95b09aec745812',
 'ps2x_vu1_bench.exe':'75f8c403b362f87403714d4d1808b9549b767302f896e1d73de51cb50b49dfd5'}

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()

def impact(files):
    """Unknown changes select every offline group, never silently disappear."""
    groups=set();unknown=[]
    for raw in files:
        p=raw.replace('\\','/').lower()
        if any(x in p for x in ('transport_replay','phase3_fixtures','dma_iop_replay','build_vif_replay')):groups|={'dma','iop','fast'}
        if 'iop' in p or 'sif' in p:groups.add('iop')
        if 'scheduler' in p:groups.add('dma')
        if '/vu/' in p or 'vu1_' in p:groups|={'vu'}
        elif 'vif' in p or 'dma' in p:groups|={'vu','graphics','ee','dma'}
        elif any(x in p for x in ('/gs/','gif','graphics')):groups|={'graphics'}
        elif any(x in p for x in ('audio','spu2','pcm')):groups|={'audio'}
        elif any(x in p for x in ('iop','sif','pad','save','scheduler')):groups|={'fast','audio','ee','iop'}
        elif any(x in p for x in ('recomp','mmi','fpu','r5900','code_generator')):groups|={'ee','hardware','semantics'}
        elif p.endswith(('.md','.svg','.png','.html')):groups|={'fast'}
        elif p.startswith(('tools/','tests/')):groups|={'fast','ee'}
        else:unknown.append(raw)
    if unknown or not files:groups|={'fast','vu','ee','graphics','audio','hardware','dma','iop','semantics'}
    return sorted(groups),unknown

def signature(text):
    """Bench performs its own per-command golden checks; preserve key output too."""
    for line in reversed(text.splitlines()):
        if line.startswith('{'):
            row=json.loads(line)
            if 'state_result' in row:
                if not row.get('gif_verified_passes'):raise ValueError('GIF was not verified')
                return {k:row[k] for k in ('state_result','cycles','gif_packets')}
    patterns={'state':r'\bresult=([a-f0-9]{16})','cycles':r'vu1_cycles=(\d+)',
              'gif_packets':r'gif_packets=(\d+)','gif_result':r'gif_result=([a-f0-9]{16})'}
    result={k:re.search(v,text) for k,v in patterns.items()}
    if not all(result.values()):raise ValueError('Incomplete state/cycle/GIF signature')
    return {k:v[1] for k,v in result.items()}

def compare_signatures(a,b):
    return next(({'field':k,'reference':a.get(k),'candidate':b.get(k)}
                 for k in sorted(set(a)|set(b)) if a.get(k)!=b.get(k)),None)

def performance_decision(changes):
    if not changes:return 'mixed-inconclusive'
    return 'isolated-gain-needs-game-acceptance' if all(c>0 for c in changes) else 'reject-consistently-slower' if all(c<0 for c in changes) else 'mixed-inconclusive'

def gate_exit(regressions_passed,benchmark_requested,decision):
    if not regressions_passed:return 1
    if benchmark_requested and decision!='isolated-gain-needs-game-acceptance':return 2
    return 0

def analyze_pairs(rows,pairs):
    changes=[]
    for pair in range(pairs):
        group=[r for r in rows if r['pair']==pair]
        if len(group)!=2 or {r['label'] for r in group}!={'reference','candidate'}:raise ValueError('Incomplete benchmark pair')
        a=next(r['ns_per_cycle'] for r in group if r['label']=='reference')
        b=next(r['ns_per_cycle'] for r in group if r['label']=='candidate')
        import math
        if not all(math.isfinite(x) and x>0 for x in (a,b)):raise ValueError('Invalid benchmark cost')
        changes.append((a-b)/a*100)
    return changes

def hardware_status(result,baseline,actual_tty_hash):
    if result['status']=='PASS':return 'passed'
    if result['status']=='MISMATCH' and baseline.get('classification')=='known-mismatch' and actual_tty_hash==baseline['tty_sha256']:return 'known-mismatch'
    return 'failed'

def revision(folder):
    def git(*args):
        p=subprocess.run(['git','-C',str(folder),*args],capture_output=True,text=True)
        return p.stdout.strip() if p.returncode==0 else None
    return {'head':git('rev-parse','HEAD'),'branch':git('branch','--show-current')}

def discover_changes():
    found=[]
    for folder,prefix in [(ROOT,'lab/'),(ROOT/'engines/project4','engines/project4/')]:
        for command in [('diff','--name-only'),('ls-files','--others','--exclude-standard')]:
            p=subprocess.run(['git','-C',str(folder),*command],capture_output=True,text=True,encoding='utf-8',errors='replace')
            if p.returncode:found.append(prefix+'<unknown-git-state>');continue
            found.extend(prefix+line for line in p.stdout.splitlines() if line)
    return sorted(set(found))

class Suite:
    def __init__(self,args):
        self.args=args
        self.started=time.monotonic()
        stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        self.out=ROOT/'artifacts/regression'/stamp;self.out.mkdir(parents=True,exist_ok=False)
        self.env={k:v for k,v in os.environ.items() if not k.upper().startswith('PS2X_')}
        temp=self.out/'temp';temp.mkdir()
        self.env.update(TMP=str(temp),TEMP=str(temp),PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8')
        self.env['PATH']=str(ROOT/'artifacts/runs/baseline-01/guest')+os.pathsep+self.env.get('PATH','')
        self.env.update(PS2X_VU1_CLEAN_BLOCKS='1',PS2X_VU1_FUSED='1')
        if getattr(args,'vu_pipeline_index',None) is not None:self.env['PS2X_VU1_PIPELINE_INDEX']=args.vu_pipeline_index
        if getattr(args,'vu_vector_retire',None) is not None:self.env['PS2X_VU1_VECTOR_RETIRE']=args.vu_vector_retire
        if getattr(args,'vu_fmac_classify',None) is not None:self.env['PS2X_VU1_FMAC_CLASSIFY']=args.vu_fmac_classify
        if getattr(args,'vu_aot_coverage',None) is not None:self.env['PS2X_VU1_AOT_COVERAGE']=args.vu_aot_coverage
        self.report={'schema':1,'source_revision':revision(ROOT/'engines/project4'),
          'orchestrator_revision':revision(ROOT),'changed_files':args.changed,'tests':[],
          'hashes':{},'first_divergence':None,'performance':None,'real_re4_launched':False,
          'real_re4_required_for_acceptance':bool(args.changed),
          'scope':'Offline regression oracles do not independently prove PS2 hardware accuracy',
          'unverified_behavior':['Full RE4 campaign, audiovisual synchronization and saves require explicit game acceptance',
             'No general captured EE/IOP checkpoint replay engine is claimed; current offline coverage uses existing units and synthetic programs']}
        self.report['orchestrator_sha256']=sha(__file__)
        self.report['vu_pipeline_index']=getattr(args,'vu_pipeline_index',None)
        self.report['vu_vector_retire']=getattr(args,'vu_vector_retire',None)
        self.report['vu_fmac_classify']=getattr(args,'vu_fmac_classify',None)
        self.report['vu_aot_coverage']=getattr(args,'vu_aot_coverage',None)
        self.report['observed_working_tree_changes']=discover_changes()
        self.report['change_scope_note']='Inherited uncommitted reference engineering is included in observed changes. --changed explicitly scopes candidate coverage.'
        self.done=set()
    def fingerprint(self,path):
        path=Path(path)
        key=str(path)
        if key not in self.report['hashes']:self.report['hashes'][key]=sha(path)
        return self.report['hashes'][key]
    def fixture(self,folder):
        # Only explicitly selected private fixture folders, never game tree scans.
        files=sorted(p for p in Path(folder).iterdir() if p.is_file())
        return {p.name:self.fingerprint(p) for p in files}
    def note(self,name,status,scope,**details):
        row={'name':name,'status':status,'scope':scope,**details};self.report['tests'].append(row)
        print(name,status,flush=True);return row
    def run(self,name,command,cwd=None,env=None,timeout=180,scope='offline',expected=0):
        start=time.monotonic();command=list(map(str,command))
        for token in command:
            if Path(token).is_file():self.fingerprint(token)
        try:
            p=subprocess.run(command,cwd=cwd or self.out,env={**self.env,**(env or {})},
                capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
            stdout,stderr,code=p.stdout,p.stderr,p.returncode
        except subprocess.TimeoutExpired as exc:
            stdout=(exc.stdout or b'').decode('utf-8','replace');stderr='Timed out';code=124
        except OSError as exc:stdout='';stderr=str(exc);code=127
        (self.out/(name+'.stdout.txt')).write_text(stdout,encoding='utf-8')
        (self.out/(name+'.stderr.txt')).write_text(stderr,encoding='utf-8')
        row=self.note(name,'passed' if code==expected else 'failed',scope,exit_code=code,
                      seconds=round(time.monotonic()-start,3),command=command)
        plain=ANSI.sub('',stdout+'\n'+stderr)
        cases=re.search(r'Ran (\d+) tests? in',plain)
        if cases:
            skipped=re.search(r'OK \(skipped=(\d+)\)',plain)
            row['case_counts']={'total':int(cases[1]),'skipped':int(skipped[1]) if skipped else 0}
        if code!=expected and self.report['first_divergence'] is None:
            self.report['first_divergence']={'test':name,'detail':(stderr or stdout)[-2000:]}
        self.save();return row,stdout,stderr
    def bind(self,folder):
        folder=Path(folder);manifest=json.loads((folder/'identity.json').read_text())
        required=['ps2x_tests.exe']
        if 'vu' in self.report['selected_groups'] or self.args.benchmark:required.append('ps2x_vu1_bench.exe')
        for name in required:
            if name not in manifest:raise ValueError(f'Missing {name} identity in {folder}')
            if self.fingerprint(folder/name)!=manifest[name]:raise ValueError(f'Executable hash mismatch: {folder/name}')
        engineering=folder/'engineering-inputs.json'
        if engineering.exists():
            inputs=json.loads(engineering.read_text());covered={Path(p).resolve() for p in inputs['covered_source_files']}
            for name,digest in inputs['files'].items():
                if self.fingerprint(Path(name))!=digest:raise ValueError('Stale engineering compiler input: '+name)
            uncovered=[p for p in self.args.changed if Path(p).suffix in ('.cpp','.h','.inl','.inc') and
                       not ({(ROOT/Path(p)).resolve(),(ROOT/'engines/project4'/Path(p)).resolve()} & covered)]
            if uncovered:self.note('source-coverage','blocked','Engineering build does not cover these changed sources',files=uncovered)
            self.report['engineering_build']=inputs['scope'];self.report['engineering_inputs_sha256']=self.fingerprint(engineering)
            return
        trace_inputs=folder/'source-inputs.json'
        if trace_inputs.exists():
            inputs=json.loads(trace_inputs.read_text());covered=set()
            for name,digest in inputs['sources'].items():
                source=ROOT/'engines/project4/ps2xRuntime/src/lib'/name
                if self.fingerprint(source)!=digest:raise ValueError('Stale diagnostic source: '+name)
                covered.add(name)
            if self.fingerprint(ROOT/'lab/shared-link/ps2_vu1_core.cpp.obj')!=inputs['accepted_vu_object_sha256']:raise ValueError('Changed accepted VU object')
            self.report['tested_source_files']=inputs['sources']
            uncovered=[p for p in self.args.changed if Path(p).suffix in ('.cpp','.h','.inl','.inc') and Path(p).name not in covered]
            if uncovered:self.note('source-coverage','blocked','Diagnostic build does not cover other changed sources',files=uncovered)
            return
        stampfile=folder/'compile-inputs.json'
        if not stampfile.exists():
            if folder!=ROOT/'lab/shared-link':raise ValueError('Candidate has no compiler-input manifest')
            for name,digest in ACCEPTED.items():
                if self.fingerprint(folder/name)!=digest:raise ValueError('Legacy reference differs from pinned accepted artifact')
            self.report['source_binding']='Legacy accepted artifact, pinned executable identities; no historical compiler-input stamp. NOT proof of current checkout coverage.'
            if self.args.changed:self.note('source-coverage','blocked','Changed-source coverage requires a candidate build with compiler-input metadata; reference tests still run')
            return
        stamp=json.loads(stampfile.read_text())
        source=Path(self.args.vu_source) if self.args.vu_source else ROOT/'engines/project4/ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp'
        if self.fingerprint(source)!=stamp['inputs']['ps2_vu1_core.cpp']:
            raise ValueError('Stale VU binary: source hash differs. Build it or explicitly select its archived source with --vu-source.')
        vu=ROOT/'engines/project4/ps2xRuntime/src/lib/vu'
        for name,digest in stamp['inputs'].items():
            if name=='ps2_vu1_core.cpp':continue
            if self.fingerprint(vu/name)!=digest:raise ValueError(f'Stale VU dependency: {name}')
        if self.fingerprint(folder/'ps2_vu1_core.cpp.obj')!=stamp['object_sha256']:raise ValueError('VU object differs from compiler-input manifest')
        self.report['tested_vu_source']=str(source);self.report['candidate_dir']=str(folder)
        uncovered=[p for p in self.args.changed if Path(p).suffix in ('.cpp','.h','.inl','.inc') and Path(p).name not in {Path(k).name for k in stamp['inputs']}]
        if uncovered:self.note('source-coverage','blocked','VU build does not cover these other changed sources',files=uncovered)
    def unit(self):
        if 'unit' in self.done:return
        self.done.add('unit');row,text,_=self.run('cpp-unit',[self.args.candidate_dir/'ps2x_tests.exe'],ROOT/'engines/project4',scope='Candidate C++ full suite; existing binary has no subsystem filter')
        clean=ANSI.sub('',text);passed=re.search(r'Passed:\s+(\d+)',clean);failed=re.search(r'Failed:\s+(\d+)',clean)
        if not passed or not failed or int(failed[1]) or int(passed[1])<1:row['status']='failed'
        row['case_counts']={'passed':int(passed[1]) if passed else None,'failed':int(failed[1]) if failed else None}
    def fast(self):
        self.unit()
        self.run('lab-python',[sys.executable,'-m','unittest','discover','-s','tests','-p','test_*.py'],ROOT)
    def vu(self):
        self.fmac_regressions()
        self.unit();candidate=self.args.candidate_dir/'ps2x_vu1_bench.exe';base=self.args.baseline_dir/'ps2x_vu1_bench.exe'
        self.fingerprint(base)
        trace=Path('C:/Project/PS2redmption/artifacts/runs/masterpiece-command-trace-v38/vu-commands')
        jobs=[('commands-964',trace,None)]
        budgets=(1,2,4,31,256,4096,65536) if self.args.extended else (1,4,65536)
        edge=Path('C:/Project/PS2redmption/artifacts/verification/vu-clean-blocks-v41/edge-replay-v2')
        jobs.extend((f'commands-edge-{b}',edge/f'budget-{b}'/'commands',None) for b in budgets)
        folders=[edge/'snapshots']+sorted((ROOT/'artifacts/experiments/vu-shared-regions/snapshots').iterdir())
        budgets=(1,2,3,4,7,31,63,64,127,128,160,4096,65536) if self.args.extended else (1,4,64,65536)
        jobs.extend((f'snapshot-{folder.name}-{b}',folder,b) for folder in folders for b in budgets)
        for name,folder,budget in jobs:
            self.fixture(folder);values=[]
            for label,exe in [('reference',base),('candidate',candidate)]:
                if label=='candidate' and candidate.resolve()==base.resolve() and len(values)==1:
                    values.append(dict(values[0]))
                    self.note(name+'-candidate','passed','Same executable path and fixture in this invocation; reused reference execution, not independent candidate validation',reused_from=name+'-reference')
                    continue
                args=['--commands',folder,'--repeat','1'] if budget is None else [folder,'--budget',str(budget),'--resumes','64','--repeat','1','--gif-hash']
                row,text,_=self.run(name+'-'+label,[exe,*args],scope='Offline VU cross-command state/register/memory/cycle/GIF oracle')
                try:values.append(signature(text))
                except (ValueError,KeyError) as exc:row['status']='failed';row['parse_error']=str(exc)
            if len(values)==2:
                divergence=compare_signatures(*values)
                self.note(name+'-compare','failed' if divergence else 'passed','Candidate versus accepted recorded oracle',first_divergence=divergence)
                if divergence and self.report['first_divergence'] is None:self.report['first_divergence']={'test':name,**divergence}
        if self.args.benchmark:self.benchmark(trace,base,candidate)
    def benchmark(self,trace,base,candidate):
        if any(r['status']=='failed' for r in self.report['tests']):
            self.note('benchmark','blocked','Correctness gate failed; no timing or game run');return
        if self.fingerprint(base)==self.fingerprint(candidate):
            self.note('benchmark','blocked','Identical binaries are an A/A control, not an optimization comparison');return
        # Refuse timing while the RE4 runner or a compiler/linker is running.
        import psutil
        names=[(p.info['name'] or '').lower() for p in psutil.process_iter(['name'])]
        busy=[n for n in names if n in ('ps2entryrunner.exe','clang-cl.exe','lld-link.exe','cl.exe','link.exe','ps2x_tests.exe','ps2x_vu1_bench.exe','runner.exe') or n.startswith(('ps2x_hw_','ps2x_e2e_'))]
        if busy:self.note('benchmark','blocked','Timing contaminated by active game/build',processes=busy);return
        rows=[]
        for pair in range(self.args.pairs):
            for label,exe in ([('reference',base),('candidate',candidate)] if pair%2==0 else [('candidate',candidate),('reference',base)]):
                r,text,_=self.run(f'timing-{pair}-{label}',[exe,'--commands',trace,'--repeat',str(self.args.repeat),'--timing-after-verify'],scope='Controlled offline timing, NOT game FPS')
                if r['status']!='passed':return
                signature(text);rows.append({'pair':pair,'label':label,**json.loads(text.strip().splitlines()[-1])})
        changes=analyze_pairs(rows,self.args.pairs)
        decision=performance_decision(changes)
        self.report['performance']={'pairs':self.args.pairs,'repeat':self.args.repeat,'paired_cost_reduction_percent':changes,'median_cost_reduction_percent':statistics.median(changes),'decision':decision,'rows':rows,'promotion':'Never automatic; positive offline timing still requires explicit RE4 acceptance'}
    def python(self):
        self.run('ps2l-verify',[sys.executable,'-m','ps2l','verify','--out',self.out/'ps2l-verify.json'],ROOT/'reference-tools',timeout=240,scope='Existing Project4 verify: Python regressions and selftests; no --build or --canary')
    def ee(self):
        self.unit()
        command=['cmd.exe','/c',ROOT/'lab/test-dev-env.cmd',sys.executable,ROOT/'tools/lab_synthetic.py','--out',self.out/'synthetic']
        if self.args.project4_recompiler:command+=['--project4-recompiler',self.args.project4_recompiler]
        row,_,_=self.run('synthetic-pipeline',command,timeout=300,scope='Fresh synthetic ELF→Zmbor pipeline and explicitly selected Project4 canary; not RE4')
        detail=self.out/'synthetic/report.json'
        if detail.exists():row['pipeline_report']=json.loads(detail.read_text())
    def graphics(self):
        self.unit()
        for name in ('gif_image2_after.exe','image2_frontend.exe'):
            self.run(name[:-4],[ROOT/'lab/gif-clang'/name],scope='Existing focused IMAGE2/VRAM/cache fixture, separate from candidate C++ suite')
        self.vif()
    def vif(self):
        if 'vif' in self.done:return
        self.done.add('vif')
        row,_,_=self.run('vif-direct-replay',[sys.executable,ROOT/'tools/vif_replay.py','--out',self.out/'vif-replay'],timeout=90,scope='Production VIF DIRECT cross-command state, chunk boundaries, IRQ and captured image uploads; no game')
        path=self.out/'vif-replay/report.json'
        if path.exists():row['replay_report']=json.loads(path.read_text())
    def mutations(self):
        row,_,_=self.run('fault-injection',[sys.executable,ROOT/'tools/lab_mutations.py','--out',self.out/'mutations'],timeout=120,scope='Controlled private mutations; success means actual defects were detected, no game')
        path=self.out/'mutations/report.json'
        if path.exists():row['mutation_report']=json.loads(path.read_text())
    def dma(self):
        self.transport('dma')
        identity_path=ROOT/'artifacts/phase4/dma-guard-identity.json'
        if identity_path.exists():
            identity=json.loads(identity_path.read_text())
            for name,value in identity['files'].items():
                if self.fingerprint(Path(name))!=value:raise ValueError('Stale DMA guard test dependency: '+name)
            self.run('dma-chain-resource-guards',[identity['binary']],timeout=60,scope='Fresh production DMAC: repeated CALL/RET, cyclic NEXT, exact256MiB success, oversize failure without partial packets')
    def iop(self):self.transport('iop')
    def fmac_regressions(self):
        if getattr(self.args,'vu_fmac_classify',None) is None:return
        if 'fmac-regressions' in self.done:return
        self.done.add('fmac-regressions')
        record_path=ROOT/'artifacts/phase5/fmac-helper-report.json'
        record=json.loads(record_path.read_text())
        source=ROOT/'engines/project4/ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp'
        if self.fingerprint(source)!=record['source_sha256']:raise ValueError('Stale FMAC helper validation: production source changed')
        inputs=json.loads((ROOT/'artifacts/phase5/fmac-helper-inputs.json').read_text())
        for path,digest in inputs['files'].items():
            if self.fingerprint(path)!=digest:raise ValueError('Stale FMAC witness source dependency: '+path)
        stamp=json.loads((self.args.candidate_dir/'engineering-inputs.json').read_text())
        if stamp['files'].get(str(source))!=record['source_sha256']:raise ValueError('Candidate does not bind the validated FMAC source')
        self.fingerprint(record_path)
        rows={row['mode']:row for row in record['rows']}
        for mode in ('simd','scalar','mutant'):
            binary=ROOT/'lab/phase5-fmac-witness-01'/(mode+'.exe')
            if self.fingerprint(binary)!=rows[mode]['sha256']:raise ValueError('FMAC witness executable identity mismatch: '+mode)
            self.run('fmac-classify-'+mode,[binary],timeout=30,expected=2 if mode=='mutant' else 0,
                scope='Actual classifier against independent1048576-case bit oracle; compiled sign-packing mutation must fail' if mode=='mutant' else 'Actual classifier1048576 independent predicate/flag/payload cases, SIMD or forced scalar fallback')
        self.run('fmac-classify-bit-proof',[sys.executable,ROOT/'tools/prove_phase5_fmac.py'],timeout=60,
            scope='Actual source thresholds/tables; all32bit signed SIMD predicate proof, negative control and4096 lane/normal/sign combinations')
    def semantics(self):
        self.fmac_regressions()
        if 'semantics' in self.done:return
        self.done.add('semantics')
        self.run('z3-integer-models',[sys.executable,ROOT/'lab/zmbor-phase4-src/tools/semantics/z3_int_semantics.py'],env={'PYTHONPATH':str(ROOT/'lab/phase4-python')},timeout=90,scope='Upstream bit-vector formulas and negative controls; arithmetic transcription, not a proof of the full runtime')
        row,_,_=self.run('emitted-arithmetic-ubsan',['cmd.exe','/c',ROOT/'lab/test-dev-env.cmd',sys.executable,ROOT/'tools/validate_phase4_codegen.py','--out',self.out/'integer-ubsan'],timeout=120,scope='Actual old and corrected emitted arithmetic; deliberate original UB controls plus952 independent corrected-result/exception checks')
        path=self.out/'integer-ubsan/report.json'
        if path.exists():row['arithmetic_report']=json.loads(path.read_text())
    def transport(self,group):
        if group in self.done:return
        self.done.add(group)
        row,_,_=self.run(group+'-transport-replay',[sys.executable,ROOT/'tools/transport_replay.py','--group',group,'--mutations','--out',self.out/(group+'-replay')],timeout=240,scope='Fresh production DMAC/SIF TUs; normalized real-payload and synthetic scenarios, deterministic state/packet/IRQ/completion gates, no game launch or hardware timing claim')
        path=self.out/(group+'-replay')/'report.json'
        if path.exists():row['replay_report']=json.loads(path.read_text())
    def audio(self):
        self.unit()
        for exe in sorted((ROOT/'artifacts/checks/project4').glob('ps2_iop*.exe')):
            self.run('iop-'+exe.stem,[exe],ROOT/'engines/project4',scope='Existing reference IOP/SPU2/SIF binaries, not rebuilt candidate')
        self.run('audio-python',[sys.executable,'-m','unittest','discover','-s','tests','-p','test_*audio*.py'],ROOT/'reference-tools')
        self.run('pcm-python',[sys.executable,'-m','unittest','discover','-s','tests','-p','test_pcm_write_compare.py'],ROOT/'reference-tools',scope='Existing deterministic PCM memory-effect reconstruction fixtures')
        prefix=Path(self.args.audio_prefix) if self.args.audio_prefix else ROOT/'artifacts/runs/room-feedback-01/diagnostics/audio'
        if prefix.with_name(prefix.name+'-out.wav').exists():
            for suffix in ('-spu2.wav','-out.wav'):self.fingerprint(prefix.with_name(prefix.name+suffix))
            self.run('recorded-audio',[sys.executable,ROOT/'reference-tools/tools/diagnostics/audio_check.py',prefix,'--out',self.out/'audio-analysis.json'],scope='Offline recorded real PCM analysis; not independent DSP or AV-sync proof')
        else:self.note('recorded-audio','blocked','No private PCM capture available; no game is launched to manufacture a pass')
    def hardware(self):
        if self.args.hardware_baseline=='current':return self.current_hardware()
        old=json.loads((ROOT/'artifacts/hardware/summary.json').read_text());known={r['id']:r for r in old['tests']}
        pinned=json.loads((ROOT/'tests/data/hardware_reference_manifest.json').read_text())['tests']
        for name,baseline in known.items():
            source=ROOT/'artifacts/hardware'/name;work=self.out/name;work.mkdir()
            exe=next(source.glob('*.exe'));elf=next(source.glob('*.elf'));expected=next(source.glob('*.expected'))
            for filename,digest in pinned[name]['hashes'].items():
                if self.fingerprint(source/filename)!=digest:raise ValueError('Hardware reference drift: '+name+'/'+filename)
            for p in (exe,elf,expected):self.fingerprint(p);shutil.copy2(p,work/p.name)
            row,_,_=self.run(name,[sys.executable,ROOT/'engines/zmbor/tools/hwtest/hwtest.py','run','--runner',work/exe.name,'--elf',work/elf.name,'--expected',work/expected.name,'--result',work/'result.json','--timeout','15'],cwd=work,timeout=25,scope='Existing ae1c119 reference runner versus PS2 expected output, NOT candidate hardware coverage')
            result=json.loads((work/'result.json').read_text());row['hardware_result']=result
            if result['status']=='PASS':row['status']='passed'
            elif result['status']=='MISMATCH' and baseline['status']=='MISMATCH' and sha(work/'run.tty.txt')==pinned[name]['hashes']['run.tty.txt']:
                row['status']='known-mismatch';row['note']='Actual mismatch retained; never counted as a pass'
            else:row['status']='failed'
        # Child hwtest uses nonzero for known mismatches; derive first NEW divergence.
        self.report['first_divergence']=next(({'test':r['name'],'detail':r.get('hardware_result',{}).get('diff_head')} for r in self.report['tests'] if r['status']=='failed'),None)
    def current_hardware(self):
        path=ROOT/'artifacts/phase2/hardware-current/catalog.json'
        if not path.exists():self.note('hardware-current','blocked','Fresh integration baseline has not finished building');return
        catalog=json.loads(path.read_text());commit=catalog['source_identity']['source_commit']
        from hardware_profile import validate_archive,validate_dependencies
        validate_archive(catalog['source_identity'])
        validate_dependencies(json.loads((ROOT/'artifacts/phase2/hardware-current/dependencies.json').read_text()))
        current=revision(ROOT/'engines/zmbor')
        if current['head']!=commit:raise ValueError('Hardware executable source revision is stale; rebuild for active Zmbor revision')
        p=subprocess.run(['git','-C',str(ROOT/'engines/zmbor'),'diff','--name-only'],capture_output=True,text=True)
        dirty=[s for s in p.stdout.splitlines() if not s.lower().endswith('.md')]
        if p.returncode or dirty:raise ValueError('Unbuilt Zmbor code changes: '+str(dirty))
        build=ROOT/'lab/zmbor-phase2/build'
        if sha(build/'ps2xRuntime/ps2_runtime.lib')!=catalog['runtime_sha256']:raise ValueError('Current hardware runtime archive identity differs')
        if sha(build/'ps2xRecomp/ps2_recomp.exe')!=catalog['recompiler_sha256']:raise ValueError('Current hardware recompiler identity differs')
        if sha(build/'compile_commands.json')!=catalog['compile_commands_sha256']:raise ValueError('Current hardware build recipes changed')
        self.report['hardware_source_commit']=commit
        for baseline in catalog['tests']:
            name=baseline['id'];work=self.out/name;work.mkdir()
            runner=Path(baseline['runner']);elf=Path(baseline['elf']);expected=Path(baseline['expected'])
            for p,key in ((runner,'runner_sha256'),(elf,'elf_sha256'),(expected,'expected_sha256')):
                if self.fingerprint(p)!=baseline[key]:raise ValueError('Hardware input or executable identity changed: '+str(p))
            row,_,_=self.run(name,[sys.executable,ROOT/'lab/zmbor-phase2/src/tools/hwtest/hwtest.py','run','--runner',runner,'--elf',elf,'--expected',expected,'--result',work/'result.json','--timeout','15'],cwd=work,timeout=25,scope='Fresh00173a2 Zmbor recompiler/runtime binaries versus unchanged PS2 reference outputs; not Project4 candidate coverage')
            result=json.loads((work/'result.json').read_text());row['hardware_result']=result;row['source_commit']=commit
            row['status']=hardware_status(result,baseline,sha(work/'run.tty.txt'))
        self.report['first_divergence']=next(({'test':r['name'],'detail':r.get('hardware_result',{}).get('diff_head')} for r in self.report['tests'] if r['status']=='failed'),None)
    def integration(self):
        if self.args.integration_spec:
            if not self.args.allow_game:
                self.note('game-launch','blocked','Explicit --allow-game required with a validated hypothesis, identities and success criteria');return
            spec=json.loads(self.args.integration_spec.read_text())
            row,_,_=self.run('explicit-game-acceptance',[sys.executable,ROOT/'tools/lab_game_acceptance.py','--spec',self.args.integration_spec,'--out',self.out/'game-acceptance','--allow-game'],timeout=int(spec.get('seconds',0))+90,scope='Explicit real RE4 acceptance, separate from offline replay')
            detail=self.out/'game-acceptance/report.json'
            if detail.exists():
                result=json.loads(detail.read_text());row['acceptance_report']=result
                self.report['real_re4_launched']=result.get('real_re4_launched',False)
            return
        if self.args.allow_game:
            self.note('game-launch','blocked','No spec selected: provide --integration-spec; no implicit RE4 launch');return
        run=ROOT/'artifacts/runs/manual-20261024-112541-942897';summary=json.loads((run/'final-evidence/summary.json').read_text())
        for name,digest in summary['files'].items():
            p=run/'diagnostics/state.jsonl' if name=='state.jsonl' else run/name
            if self.fingerprint(p)!=digest:raise ValueError('Changed historical integration evidence: '+name)
        for frame in json.loads((run/'final-evidence/frame-manifest.json').read_text()):
            if self.fingerprint(run/'diagnostics'/frame['name'])!=frame['sha256']:raise ValueError('Changed frame evidence')
        self.note('recorded-room-transition','passed','Historical human-play evidence audit only; NOT candidate gameplay acceptance',runner_sha256=summary['runner_sha256'],frames=summary['frames'],room_transition=[256,257])
        self.report['unverified_behavior'].append('No new game run: integration command audited historical evidence only')
    def save(self):
        self.report['duration_seconds']=round(time.monotonic()-self.started,3)
        counts=collections.Counter(r['status'] for r in self.report['tests']);self.report['counts']=dict(counts)
        self.report['passed']=not any(counts[k] for k in ('failed','blocked'))
        self.report['regression_gate_passed']=self.report['passed']
        self.report['candidate_hardware_verified']=False
        self.report['hardware_all_exact']=False if counts['known-mismatch'] else None
        self.report['optimization_gate_passed']=bool(self.report['passed'] and (self.report.get('performance') or {}).get('decision')=='isolated-gain-needs-game-acceptance')
        self.report['requested_gate_exit_code']=gate_exit(self.report['passed'],self.args.benchmark,(self.report.get('performance') or {}).get('decision'))
        (self.out/'report.json').write_text(json.dumps(self.report,indent=2,ensure_ascii=False),encoding='utf-8')
        lines=['# تقرير اختبارات المختبر','',f"النتيجة: {dict(counts)}",'','لا تُشغّل اللعبة افتراضيًا. نتائج Zmbor المرجعية منفصلة عن تغطية مرشح RE4.','','| الاختبار | الحالة | النطاق |','|---|---|---|']
        lines += [f"| {r['name']} | {r['status']} | {r['scope']} |" for r in self.report['tests']]
        lines+=['','التفاصيل والبصمات وأول اختلاف والمراجعات في report.json.']
        (self.out/'report.md').write_text('\n'.join(lines),encoding='utf-8')

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('group',choices=sorted(GROUPS));parser.add_argument('--changed',action='append',default=[])
    parser.add_argument('--candidate-dir',type=Path,default=ROOT/'lab/shared-link');parser.add_argument('--baseline-dir',type=Path,default=ROOT/'lab/shared-link')
    parser.add_argument('--vu-source',type=Path);parser.add_argument('--extended',action='store_true');parser.add_argument('--benchmark',action='store_true')
    parser.add_argument('--pairs',type=int,default=7);parser.add_argument('--repeat',type=int,default=50)
    parser.add_argument('--audio-prefix',type=Path);parser.add_argument('--allow-game',action='store_true');parser.add_argument('--plan',action='store_true')
    parser.add_argument('--integration-spec',type=Path)
    parser.add_argument('--project4-recompiler',type=Path)
    parser.add_argument('--vu-pipeline-index',choices=('0','1'))
    parser.add_argument('--vu-vector-retire',choices=('0','1'))
    parser.add_argument('--vu-fmac-classify',choices=('0','1'))
    parser.add_argument('--vu-aot-coverage',choices=('0','1'))
    parser.add_argument('--hardware-baseline',choices=('current','historical'),default='current')
    args=parser.parse_args(argv)
    args.candidate_dir=(ROOT/args.candidate_dir).absolute()
    args.baseline_dir=(ROOT/args.baseline_dir).absolute()
    if args.vu_source:args.vu_source=(ROOT/args.vu_source).absolute()
    if args.integration_spec:args.integration_spec=(ROOT/args.integration_spec).absolute()
    if args.project4_recompiler:args.project4_recompiler=(ROOT/args.project4_recompiler).absolute()
    if args.group=='auto' and not args.changed:args.changed=discover_changes()
    if not 7<=args.pairs<=21 or not 1<=args.repeat<=200:parser.error('Use7..21 pairs and1..200 repeats')
    groups,unknown=impact(args.changed) if args.group=='auto' else ([args.group],[])
    if 'full' in groups:groups=['fast','vu','ee','graphics','audio','hardware','integration','python','mutations','dma','iop','semantics']
    if args.plan:print(json.dumps({'groups':groups,'unknown_changes':unknown,'launches_re4':bool(args.allow_game and args.integration_spec and 'integration' in groups)}));return 0
    suite=Suite(args);suite.report.update(selected_groups=groups,unknown_changed_files=unknown)
    try:
        if any(g in groups for g in ('fast','vu','ee','graphics','audio')):suite.bind(args.candidate_dir)
        for group in groups:getattr(suite,group)()
    except Exception as exc:
        suite.note('orchestrator','failed','Cannot silently skip required checks',error=str(exc))
        if suite.report['first_divergence'] is None:suite.report['first_divergence']={'test':'orchestrator','detail':str(exc)}
    finally:suite.save();print('REPORT',suite.out/'report.json',flush=True)
    return suite.report['requested_gate_exit_code']

if __name__=='__main__':raise SystemExit(main())
