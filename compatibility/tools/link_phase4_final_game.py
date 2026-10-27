"""Link the fixed EE/default-SNR2 generation without replacing any prior package."""
from pathlib import Path
import hashlib,json,re,subprocess,time
ROOT=Path(__file__).resolve().parents[1]
def main():
    native=ROOT/'lab/phase4-native-01';meta=json.loads((native/'identity.json').read_text());sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
    assert all(sha(r['source'])==r['source_sha256'] and sha(r['object'])==r['object_sha256'] for r in meta['compiled'])
    parent=ROOT/'lab/phase4-game-02';identity=json.loads((parent/'identity.json').read_text());assert sha(parent/'ps2EntryRunner.exe')==identity['binaries']['ps2EntryRunner.exe']
    out=ROOT/'lab/phase4-game-03';out.mkdir(exist_ok=False);start=time.monotonic();lines=(parent/'ps2EntryRunner.exe.rsp').read_text().splitlines();kept=[];removed=[]
    for line in lines:
        if '\\recomp\\native\\SLUS_211.34\\full_build\\' in line and line.endswith('.obj"'):removed.append(line)
        else:kept.append(line)
    assert len(removed)==142,'Unexpected native object set; refuse partial replacement'
    rsp='\n'.join('"'+r['object']+'"' for r in meta['compiled'])+'\n'+'\n'.join(kept)
    for option,suffix in [('out',''),('pdb','.pdb'),('implib','.lib')]:rsp=re.sub('/'+option+r':"[^"]+"',lambda _: '/'+option+':"'+str(out/('ps2EntryRunner.exe'+suffix))+'"',rsp)
    path=out/'link.rsp';path.write_text(rsp);subprocess.run(['C:/Program Files/LLVM/bin/lld-link.exe','@'+str(path)],cwd=out,check=True)
    result={'binaries':{'ps2EntryRunner.exe':sha(out/'ps2EntryRunner.exe')},'parent_sha256':identity['binaries']['ps2EntryRunner.exe'],'ee_regenerated_changed_units':127,'native_modules':len(meta['modules']),'native_compiled_units':len(meta['compiled']),'native_identity_sha256':sha(native/'identity.json'),'seconds':time.monotonic()-start,'scope':'Experimental only. Default full native path regenerated; optional legacy hybrid partial mode not accepted. No replacement or promotion.'}
    (out/'identity.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
if __name__=='__main__':main()
