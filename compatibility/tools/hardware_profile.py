"""Content-checked provenance for reusable, freshly built hardware runners."""
from pathlib import Path
import hashlib,json,tarfile
ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'lab/zmbor-phase2'
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()
def validate_archive(identity):
    archive=WORK/'source.tar'
    if sha(archive)!=identity['archive_sha256']:raise ValueError('Zmbor source archive changed')
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            if not member.isfile():continue
            expected=hashlib.sha256(tar.extractfile(member).read()).hexdigest()
            if sha(WORK/'src'/member.name)!=expected:raise ValueError('Unbuilt archived Zmbor source change: '+member.name)
def capture_dependencies():
    return {str(p.relative_to(WORK)):sha(p) for p in (WORK/'deps').rglob('*')
            if p.is_file() and (p.suffix.lower() in ('.h','.hpp','.c','.cpp','.inl','.cmake') or p.name=='CMakeLists.txt')}
def validate_dependencies(manifest):
    for name,digest in manifest.items():
        if sha(WORK/name)!=digest:raise ValueError('Unbuilt hardware dependency change: '+name)
