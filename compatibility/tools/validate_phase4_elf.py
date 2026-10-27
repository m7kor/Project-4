"""Minimal ELF32 table regressions; preserve the pre-fix access violation evidence."""
from pathlib import Path
import argparse,hashlib,json,struct,subprocess,time
ROOT=Path(__file__).resolve().parents[1]
def fixture(kind):
    ident=b'\x7fELF'+bytes([1,1,1])+bytes(9);data=bytearray(512)
    data[:52]=struct.pack('<16sHHIIIIIHHHHHH',ident,2,8,1,0x100000,0,256,0,52,32,0,40,5,0)
    data[64:72]=struct.pack('<2I',0x03e00008,0);data[80:88]=b'\0target\0'
    data[96:128]=bytes(16)+struct.pack('<IIIBBH',1,0x100000,8,0x12,0,1)
    data[144:152]=struct.pack('<II',0x100000,0x104)
    sections=[(0,0,0,0,0,0,0,0,0,0),(0,1,6,0x100000,64,8,0,0,4,0),(0,3,0,0,80,8,0,0,1,0),(0,2,0,0,96,32,2,1,4,16),(0,9,0,0,144,8,3,1,4,8)]
    if kind=='short-symbol':sections[3]=(*sections[3][:-1],1)
    if kind=='short-rel':sections[4]=(*sections[4][:-1],1)
    if kind=='null-rel':sections[4]=(0,9,0,0,0x10000,8,3,1,4,8)
    if kind=='null-symbol':sections[3]=(0,2,0,0,0x10000,32,2,1,4,16)
    if kind=='bad-rel-symbol-type':sections[4]=(0,9,0,0,144,8,1,1,4,8)
    if kind=='empty-rel':sections[4]=(0,9,0,0,144,0,3,1,4,0)
    for i,s in enumerate(sections):struct.pack_into('<10I',data,256+i*40,*s)
    return data[:456]
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=(ROOT/a.out).resolve();assert out.is_relative_to(ROOT/'artifacts');out.mkdir(parents=True,exist_ok=False)
    start=time.monotonic();rows=[]
    for kind in ['valid','short-symbol','short-rel','null-rel','null-symbol','bad-rel-symbol-type','empty-rel','upstream-null-rel']:
        path=out/(kind+'.elf');path.write_bytes((ROOT/'lab/zmbor-phase4-src/tools/fuzz/regressions/elf/null_reloc_data.bin').read_bytes() if kind=='upstream-null-rel' else fixture(kind))
        row={'case':kind,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        for label,folder in [('before','phase4-base'),('after','phase4-fixed-01')]:
            r=subprocess.run([ROOT/'lab'/folder/'probe.exe','elf',path],capture_output=True,text=True,timeout=10);row[label]={'exit_code':r.returncode,'stdout':r.stdout,'stderr':r.stderr}
        rows.append(row)
    passed=all(r['after']['exit_code'] in (0,2) for r in rows) and rows[0]['after']['exit_code']==0 and 'symbols=1' in rows[0]['after']['stdout'] and rows[-1]['before']['exit_code'] not in (0,2)
    result={'passed':passed,'tests':rows,'seconds':time.monotonic()-start,'scope':'Public minimal ELF table corpus; actual old and new parser execution. Valid symbol retained, malformed tables never crash; no game launch'};(out/'report.json').write_text(json.dumps(result,indent=2));print(json.dumps({'passed':passed,'cases':len(rows),'old_crashes':[r['case'] for r in rows if r['before']['exit_code'] not in (0,2)]}));return 0 if passed else 1
if __name__=='__main__':raise SystemExit(main())
