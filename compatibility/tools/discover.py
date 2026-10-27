"""Read-only ISO/ELF/AFS discovery. Output contains metadata, no game payloads."""
from pathlib import Path
import sys, json, struct, hashlib, collections, re
ROOT=Path(__file__).resolve().parents[1]
GAME=Path('C:/Project/PS2redmption/game')
sys.path.insert(0,str(ROOT/'reference-tools/tools/diagnostics'))
from game_binary_inventory import scan

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''): h.update(b)
    return h.hexdigest()

def elf(path):
    data=path.read_bytes()
    h=struct.unpack_from('<HHIIIIIHHHHHH',data,16)
    typ,machine,version,entry,phoff,shoff,flags,ehsize,phsize,phnum,shsize,shnum,shstr=h
    raw=[struct.unpack_from('<10I',data,shoff+i*shsize) for i in range(shnum)]
    names=data[raw[shstr][4]:raw[shstr][4]+raw[shstr][5]]
    sections=[]
    for s in raw:
        name=names[s[0]:].split(b'\0')[0].decode('ascii','replace')
        sections.append(dict(name=name,type=s[1],flags=s[2],address=s[3],offset=s[4],size=s[5],link=s[6],entsize=s[9]))
    segments=[]
    for i in range(phnum):
        p=struct.unpack_from('<8I',data,phoff+i*phsize)
        segments.append(dict(type=p[0],offset=p[1],vaddr=p[2],paddr=p[3],filesz=p[4],memsz=p[5],flags=p[6],align=p[7]))
    return dict(sha256=sha(path),type=typ,machine=machine,entry=entry,flags=flags,sections=sections,segments=segments,
                symbols=sum(s['size']//s['entsize'] for s in sections if s['type'] in (2,11) and s['entsize']))

def classify(b):
    for magic,name in [(b'\x7fELF','ELF'),(b'SNR2','SNR2'),(b'AFS\0','AFS'),(b'GCA','GCA'),(b'OggS','Ogg'),(b'VAGp','VAG'),(b'TIM2','TIM2'),(b'\x00\x00\x01\xba','MPEG-PS'),(b'\x00\x00\x01\xb3','MPEG-video')]:
        if b.startswith(magic):return name
    return 'unknown'

def afs(path):
    rows=[];total=path.stat().st_size
    with path.open('rb') as f:
        magic,count=struct.unpack('<4sI',f.read(8));assert magic==b'AFS\0'
        assert count <= (total-8)//8
        table=f.read(count*8)
        nameoff,namesize=struct.unpack('<II',f.read(8))
        names=b''
        if nameoff+namesize<=total and namesize>=count*48:
            f.seek(nameoff);names=f.read(count*48)
        for i in range(count):
            offset,size=struct.unpack_from('<II',table,i*8)
            assert offset+size<=total
            f.seek(offset);b=f.read(min(size,64))
            name=names[i*48:i*48+32].split(b'\0')[0].decode('ascii','replace') if names else ''
            rows.append(dict(index=i,offset=offset,size=size,name=name,format=classify(b)))
    return dict(entries=rows,signature_counts=dict(collections.Counter(r['format'] for r in rows)),filename_table=bool(names))

def iso(path):
    with path.open('rb') as f:
        f.seek(16*2048);p=f.read(2048);assert p[1:6]==b'CD001'
        rows=[];visited=set()
        def walk(record,prefix):
            extent=struct.unpack_from('<I',record,2)[0];length=struct.unpack_from('<I',record,10)[0]
            if extent in visited:return
            visited.add(extent);f.seek(extent*2048);data=f.read(length);pos=0
            while pos<len(data):
                n=data[pos]
                if not n:pos=(pos//2048+1)*2048;continue
                r=data[pos:pos+n];pos+=n;name=r[33:33+r[32]]
                if name in (b'\0',b'\1'):continue
                name=name.decode('ascii','replace').split(';')[0]
                row=dict(path=prefix+name,lba=struct.unpack_from('<I',r,2)[0],size=struct.unpack_from('<I',r,10)[0],directory=bool(r[25]&2))
                rows.append(row)
                if row['directory']:walk(r,prefix+name+'/')
        walk(p[156:190],'')
    return dict(format='ISO9660',volume=p[40:72].decode('ascii','replace').strip(),files=rows,sha256=sha(path))

def main():
    out=ROOT/'artifacts/discovery';out.mkdir(exist_ok=False)
    cnfs=list(GAME.rglob('SYSTEM.CNF'));assert len(cnfs)==1
    cnf=cnfs[0];text=cnf.read_text();boot=re.search(r'BOOT2\s*=\s*cdrom0:\\([^;\s]+)',text,re.I).group(1)
    executable=cnf.parent/boot;identity=elf(executable)
    profile=Path('C:/Project/PS2redmption/profiles/SLUS-211.34/profile.toml').read_text()
    expected=re.search(r'sha256\s*=\s*"([a-f0-9]+)"',profile).group(1)
    summary=dict(boot=boot,configuration=text,elf=identity,profile_sha256_match=identity['sha256']==expected,files=[],archives={},images=[])
    for path in sorted(GAME.rglob('*')):
        if not path.is_file() or any(part.lower() in ('saves','mc0','mc1') for part in path.relative_to(GAME).parts):continue
        rel=path.relative_to(GAME).as_posix()
        if path.suffix.lower()=='.iso':summary['images'].append(iso(path));continue
        row=scan(path);summary['files'].append(row)
        if path.suffix.lower()=='.afs':
            index=afs(path);summary['archives'][rel]=dict(entries=len(index['entries']),signature_counts=index['signature_counts'],filename_table=index['filename_table'])
            (out/(path.name+'.index.json')).write_text(json.dumps(index,indent=2))
    (out/'discovery.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(dict(boot=boot,sha256=identity['sha256'],profile_match=summary['profile_sha256_match'],entry=hex(identity['entry']),sections=len(identity['sections']),archives=summary['archives'],elf_occurrences=sum(len(r['elf']) for r in summary['files']),snr2=sum(len(r['snr2']) for r in summary['files'])),indent=2))
if __name__=='__main__':main()
