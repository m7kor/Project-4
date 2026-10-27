from pathlib import Path
import json,struct,collections,hashlib
ROOT=Path(__file__).resolve().parents[1]
P4=Path('C:/Project/PS2redmption')
game=P4/'game/Resident Evil 4 (USA)'
result={}
for name in ('ioprp.img','modules.dat'):
    data=(game/name).read_bytes();entries=[]
    if name=='ioprp.img':
        at=data.find(b'RESET\0');cursor=0
        while data[at:at+10].strip(b'\0'):
            label,ext,size=struct.unpack_from('<10sHI',data,at);label=label.split(b'\0')[0].decode('ascii')
            entries.append(dict(name=label,offset=cursor,size=size,extinfo_bytes=ext))
            cursor+=(size+15)&~15;at+=16
    # IRX IOP import/export table magics; each has a 20-byte header and a
    # sequence of 8-byte import stubs or 4-byte export pointers.
    tables=[]
    for i in range(0,len(data)-20,4):
        magic=struct.unpack_from('<I',data,i)[0]
        if magic not in (0x41e00000,0x41c00000):continue
        label=data[i+12:i+20].split(b'\0')[0]
        if not label or any(c<32 or c>126 for c in label):continue
        tables.append(dict(offset=i,kind='import' if magic==0x41e00000 else 'export',library=label.decode('ascii'),version=struct.unpack_from('<H',data,i+8)[0]))
    result[name]=dict(romdir=entries,library_tables=tables)
formats={}
for index in (ROOT/'artifacts/discovery').glob('*.afs.index.json'):
    rows=json.loads(index.read_text())['entries'];path=game/'data'/index.name.replace('.index.json','')
    with path.open('rb') as f:
        for r in rows:
            f.seek(r['offset']);b=f.read(min(r['size'],4096));detected=r['format']
            if b[:2]==b'\x80\x00' and len(b)>=6:
                marker=int.from_bytes(b[2:4],'big')
                if marker>=2 and marker+4<=r['size']:
                    f.seek(r['offset']+marker-2)
                    if f.read(6)==b'(c)CRI':detected='CRI ADX'
            if b[:4]==b'\x00\x20\xaf\x30':detected='Nintendo TPL signature'
            if b[:4]==b'\x30\xaf\x20\x00':detected='TPL little-endian signature'
            r['signature_format']=detected
    formats[path.name]=dict(extensions=dict(collections.Counter(Path(r['name']).suffix for r in rows)),signatures=dict(collections.Counter(r['signature_format'] for r in rows)))
    (ROOT/'artifacts/discovery'/index.name).write_text(json.dumps(dict(entries=rows,summary=formats[path.name]),indent=2))
result['afs_formats']=formats
# Compare actual current working source snapshots, not just Git commits.
a=ROOT/'engines/project4';b=ROOT/'engines/zmbor'
comparison=[]
for base in ('ps2xRecomp','ps2xRuntime','ps2xIOP','ps2xTest'):
    for p in (a/base).rglob('*'):
        if not p.is_file() or p.suffix not in ('.cpp','.h','.inl','.inc','.cmake'):continue
        rel=p.relative_to(a);other=b/rel
        comparison.append(dict(path=rel.as_posix(),status='project4-only' if not other.is_file() else 'equal' if p.read_bytes()==other.read_bytes() else 'different'))
result['source_comparison_counts']=dict(collections.Counter(r['status'] for r in comparison))
(ROOT/'artifacts/source-comparison.json').write_text(json.dumps(comparison,indent=2))
(ROOT/'artifacts/discovery/extended.json').write_text(json.dumps(result,indent=2))
print(json.dumps(dict(formats=formats,source_comparison=result['source_comparison_counts'],iop_tables={k:len(v['library_tables']) for k,v in result.items() if k in ('ioprp.img','modules.dat')}),indent=2))
