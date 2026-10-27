"""Validate an existing private test guest without replacing its assets or saves."""
import json
from pathlib import Path


def checked_private_guest(root, candidate, manifest, digest):
    candidate = Path(candidate)
    info = candidate.lstat()
    if candidate.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError('Linked guest roots are not allowed')
    guest = candidate.resolve()
    allowed = (root / 'artifacts/runs').resolve()
    if guest.name != 'guest' or not guest.is_relative_to(allowed):
        raise ValueError('Reuse requires a private artifacts/runs/.../guest directory')
    pending = [guest]
    while pending:
        path = pending.pop()
        info = path.lstat()
        if path.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Linked entries are not allowed in a reused guest')
        if not path.resolve().is_relative_to(guest):
            raise ValueError('Guest entry escapes its private directory')
        if path.is_dir():
            pending.extend(path.iterdir())
    previous = json.loads((guest.parent / 'identity.json').read_text(encoding='utf-8'))
    report = Path(previous['run']).resolve() / 'report.json'
    if not report.is_relative_to((guest.parent / 'captures').resolve()) or not report.is_file():
        raise ValueError('Original guest run has no local terminal report')
    terminal = json.loads(report.read_text(encoding='utf-8'))
    if not isinstance(terminal.get('process_exit_observed_unix_ns'), int) or not isinstance(terminal.get('exit_code'), int):
        raise ValueError('Original report does not record a process exit')
    # The caller must separately check live process state before reuse.
    records = {str(Path(row['path'])): row for row in manifest['files']
               if Path(row['path']).parts[0] == 'data' or row['path'] in
               ('SLUS_211.34', 'SYSTEM.CNF', 'ioprp.img', 'modules.dat')}
    assets = {str(p.relative_to(guest)) for p in (guest / 'data').rglob('*') if p.is_file()}
    expected_assets = {name for name in records if Path(name).parts[0] == 'data'}
    if not expected_assets or assets != expected_assets:
        raise ValueError('Private data file set differs from the verified package')
    for name in ('SLUS_211.34', 'SYSTEM.CNF', 'ioprp.img', 'modules.dat'):
        if name not in records:
            raise ValueError('Verified package lacks required guest input')
    hashes = {}
    for name, row in records.items():
        path = guest / name
        if not path.is_file() or digest(path) != row['sha256']:
            raise ValueError('Private input differs from verified bytes: ' + name)
        hashes[name] = row['sha256']
    if not (guest / 'saves').is_dir():
        raise ValueError('Private guest has no save directory')
    return guest, hashes
