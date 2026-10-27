"""Recognize the original capture layout or this lab's explicit flat owned runs."""
from pathlib import Path

def owned_layout(run, tool_root, explicit_owner=None):
    run=Path(run).resolve(strict=True)
    tool_root=Path(tool_root).resolve()
    if explicit_owner is None:
        run.relative_to(tool_root/'artifacts/runs')
        if run.parent.name!='captures' or (run/'report.json').exists():
            raise ValueError('An unfinished owned diagnostic capture is required')
        return run.parents[1]
    if tool_root.name!='reference-tools':
        raise ValueError('Explicit lab layout requires isolated reference-tools')
    owner=Path(explicit_owner)
    info=owner.lstat()
    if owner.is_symlink() or getattr(info,'st_file_attributes',0)&0x400:
        raise ValueError('Linked run owners are forbidden')
    owner=owner.resolve(strict=True)
    allowed=(tool_root.parent/'artifacts/runs').resolve(strict=True)
    if owner!=run or run.parent!=allowed or (run/'report.json').exists():
        raise ValueError('An unfinished flat owned lab run is required')
    if not (owner/'identity.json').is_file():
        raise ValueError('Owned run identity is missing')
    return owner
