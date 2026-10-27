"""Prepare immutable SPU2 source inputs, without executing downloaded files."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
REVISION = '646df006a4688063e56c0826e7ea4b8bb0c112c4'
SOURCE = ROOT / 'dependencies' / 'pcsx2-spu2' / REVISION
ADAPTER = ROOT / 'integrations' / 'kzspu2'


def wanted(name: str) -> bool:
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or any(':' in p for p in path.parts) or '\\' in name:
        raise ValueError('unsafe archive path')
    return (name.startswith(('common/', 'pcsx2/SPU2/', '3rdparty/include/',
                             '3rdparty/fmt/include/', '3rdparty/fast_float/include/'))
            or name in {'pcsx2/GS/MultiISA.h', 'pcsx2/GS/GSVector.h'}
            or name.startswith('pcsx2/GS/GSVector') and path.suffix == '.h'
            or name in {'3rdparty/fmt/LICENSE', '3rdparty/fast_float/LICENSE-APACHE',
                        '3rdparty/fast_float/LICENSE-BOOST', '3rdparty/fast_float/LICENSE-MIT'}
            or len(path.parts) == 1 and path.name.upper().startswith(('LICENSE', 'COPYING')))


def main():
    SOURCE.mkdir(parents=True, exist_ok=True)
    archive = SOURCE / 'source.tar.gz'
    previous_manifest = SOURCE / 'source-manifest.json'
    if archive.is_file() and previous_manifest.is_file():
        previous = json.loads(previous_manifest.read_text())
        if previous['revision'] != REVISION or hashlib.sha256(archive.read_bytes()).hexdigest() != previous['archive_sha256']:
            raise ValueError('cached source archive identity mismatch')
    if not archive.is_file():
        partial = archive.with_suffix('.partial')
        url = 'https://codeload.github.com/PCSX2/pcsx2/tar.gz/' + REVISION
        request = urllib.request.Request(url, headers={'User-Agent': 'PS2redmption-SPU2-source'})
        with urllib.request.urlopen(request, timeout=60) as response, partial.open('wb') as output:
            size = 0
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > 200 * 1024 * 1024:
                    raise ValueError('source archive exceeds 200 MiB')
                output.write(chunk)
        partial.replace(archive)
    files = []
    with tarfile.open(archive, 'r:gz') as source:
        for entry in source:
            root, separator, name = entry.name.partition('/')
            if root != 'pcsx2-' + REVISION:
                raise ValueError('archive revision prefix mismatch')
            if not separator or not entry.isfile() or not wanted(name):
                continue
            if entry.size > 8 * 1024 * 1024 or len(files) >= 2000:
                raise ValueError('source extraction limit exceeded')
            destination = SOURCE / Path(*PurePosixPath(name).parts)
            if not destination.resolve().is_relative_to(SOURCE.resolve()):
                raise ValueError('source path escapes dependency root')
            with source.extractfile(entry) as stream:
                data = stream.read(entry.size + 1)
            if len(data) != entry.size:
                raise ValueError('truncated source entry')
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.is_file() and destination.read_bytes() != data:
                raise ValueError('refusing to overwrite a modified dependency source')
            if not destination.is_file():
                destination.write_bytes(data)
            files.append({'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    reference = ROOT / 'research/spu2-review/20261007/killzone'
    manifest = json.loads((reference / 'manifest.json').read_text())
    if manifest['errors'] or len(manifest['files']) != 17:
        raise ValueError('incomplete adapter source snapshot')
    if manifest['repository'] != 'drakolordx7/KillzoneRecomp' or manifest['revision'] != '5f0700079f9ac4e14799d66d01747dbcdcec55f6':
        raise ValueError('adapter identity or immutable revision mismatch')
    for entry in manifest['files']:
        data = (reference / 'sources' / entry['path']).read_bytes()
        if hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ValueError('adapter source hash mismatch')
        relative = PurePosixPath(entry['path']).relative_to('ext/kzspu2')
        if '..' in relative.parts or any(':' in part or '\\' in part for part in relative.parts):
            raise ValueError('unsafe adapter source path')
        destination = ADAPTER / Path(*relative.parts)
        if not destination.resolve().is_relative_to(ADAPTER.resolve()):
            raise ValueError('adapter source path escapes integration root')
        if destination.is_file() and destination.read_bytes() != data:
            raise ValueError('refusing to overwrite a locally modified adapter source')
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.is_file():
            destination.write_bytes(data)
    report = {'schema': 1, 'repository': 'PCSX2/pcsx2', 'revision': REVISION,
              'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
              'adapter_repository': manifest['repository'], 'adapter_revision': manifest['revision'],
              'adapter_files': manifest['files'], 'files': files,
              'scope': 'SPU2 build sources and provenance; no game assets, no execution'}
    (SOURCE / 'source-manifest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'revision': REVISION, 'pcsx2_files': len(files), 'adapter_files': 17}))


if __name__ == '__main__':
    main()
