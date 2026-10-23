"""Report captured pixel facts without claiming gameplay or reference accuracy."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path

try:
    from .diffview import load_image
except ImportError:
    from diffview import load_image


def frame_index(path: Path) -> int | None:
    match = re.fullmatch(r'frame-(\d+)', path.stem)
    return int(match[1]) if match else None


def frame_sort_key(path: Path) -> tuple:
    index = frame_index(path)
    return (0, index, path.name) if index is not None else (1, 0, path.name)


def audit_frames(directory: Path) -> dict:
    frames, errors = [], []
    for path in sorted(directory.glob('frame-*'), key=frame_sort_key):
        if path.suffix.lower() not in ('.png', '.ppm'):
            continue
        try:
            frame = load_image(path)
            if frame.width <= 0 or frame.height <= 0 or not frame.rgb:
                raise ValueError('empty frame')
            frames.append({'file':path.name, 'width':frame.width, 'height':frame.height,
                           'all_black':not any(frame.rgb),
                           'rgb_sha256':hashlib.sha256(frame.rgb).hexdigest()})
        except (OSError, ValueError) as exc:
            errors.append({'file':path.name, 'error':str(exc)})
    fingerprints = {(f['width'], f['height'], f['rgb_sha256']) for f in frames}
    return {'game_compatibility':'unverified', 'frames':frames, 'errors':errors,
            'decoded_frames':len(frames), 'unique_pixel_frames':len(fingerprints),
            'all_black':bool(frames) and all(f['all_black'] for f in frames),
            'all_identical':bool(frames) and len(fingerprints) == 1,
            'complete':bool(frames) and not errors}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args(argv)
    if not args.directory.is_dir():
        parser.error(f'capture directory missing: {args.directory}')
    report = audit_frames(args.directory)
    out = args.out or args.directory / 'frame-audit.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f"Decoded {report['decoded_frames']} frames; all black={report['all_black']}; "
          f"unique pixel frames={report['unique_pixel_frames']}; errors={len(report['errors'])}")
    print(f'Report: {out.resolve()}\nThese facts do not certify gameplay.')
    return 0 if report['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
