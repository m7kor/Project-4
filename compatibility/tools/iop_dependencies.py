"""Read IRX module names and import/export library relationships from local containers."""
from pathlib import Path
import json,struct
ROOT=Path(__file__).resolve().parents[1]
d=json.loads((ROOT/'artifacts/discovery/discovery.json').read_text())
extended=json.loads((ROOT/'artifacts/discovery/extended.json').read_text())
rows=[]
for source in d['files']:
    path=Path(source['file'])
    if path.name not in ('ioprp.img','modules.dat'):continue
    container=path.read_bytes()
    for record in source['elf']:
        start=record['offset'];size=record['minimum_extent_bytes'];data=container[start:start+size]
        shoff=struct.unpack_from('<I',data,32)[0]
        shsize,shnum,shstr=struct.unpack_from('<HHH',data,46)
        sections=[struct.unpack_from('<10I',data,shoff+i*shsize) for i in range(shnum)]
        s=sections[shstr];strings=data[s[4]:s[4]+s[5]];name='unidentified';version=None
        for s in sections:
            section_name=strings[s[0]:].split(b'\0')[0]
            if section_name==b'.iopmod' or s[1]==0x70000080:
                info=data[s[4]:s[4]+s[5]]
                if len(info)>=27:
                    version=struct.unpack_from('<H',info,24)[0]
                    name=info[26:].split(b'\0')[0].decode('ascii','replace')
        tables=[r for r in extended[path.name]['library_tables'] if start<=r['offset']<start+size]
        rows.append(dict(container=path.name,offset=start,size=size,module=name,version=version,
                         elf_type=record['type'],entry=record['entry'],sha256=record['sha256'],
                         imports=sorted(set(r['library'] for r in tables if r['kind']=='import')),
                         exports=sorted(set(r['library'] for r in tables if r['kind']=='export'))))
(ROOT/'artifacts/discovery/iop-dependencies.json').write_text(json.dumps(rows,indent=2))
print(json.dumps([dict(module=r['module'],container=r['container'],imports=len(r['imports'])) for r in rows],indent=2))
