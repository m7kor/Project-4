"""Copy current engineering sources, never saves/build trees/generated guest code."""
from pathlib import Path
import shutil, json, hashlib

ROOT = Path(__file__).resolve().parents[1]
P4 = Path('C:/Project/PS2redmption')
skip = {'.git','out','build','build-debug','deps','runner','mc0','mc1','saves','__pycache__'}
records = []
for source, dest in [(P4/'core', ROOT/'engines/project4'),
                     (Path('D:/Project/Zmbor/wt-integration'), ROOT/'engines/zmbor')]:
    pending = [source]
    while pending:
        folder = pending.pop()
        for p in folder.iterdir():
            if p.name in skip or p.is_symlink(): continue
            target = dest/p.relative_to(source)
            if p.is_dir(): pending.append(p)
            elif p.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p,target)
                records.append({'engine':dest.name,'path':p.relative_to(source).as_posix(),
                                'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
for name in ('tools/diagnostics','ps2l','tests'):
    shutil.copytree(P4/name, ROOT/'reference-tools'/name, ignore=shutil.ignore_patterns('__pycache__'), dirs_exist_ok=True)
(ROOT/'artifacts/source-snapshot.json').write_text(json.dumps(records,indent=2))
print('Source snapshot:',len(records),'files; original working changes preserved in copies')
