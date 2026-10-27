"""Compare real Vulkan readback probe images, metadata, resize and bounded delay."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np


def check(reference, candidate):
    refs = [json.loads(s) for s in (reference / 'frames.jsonl').read_text().splitlines()]
    actual = [json.loads(s) for s in (candidate / 'frames.jsonl').read_text().splitlines()]
    by_tick = {r['presented_tick']: r for r in refs}
    issues, frames, hashes, sizes = [], [], set(), set()
    if len(refs) != 16 or len(actual) != 16 or len(by_tick) != 16:
        issues.append('Expected 16 uniquely tagged reference images and 16 candidate images')
    for row in refs:
        image = reference / f"frame-{row['index']}.rgba"
        data = image.read_bytes()
        hashes.add(hashlib.sha256(data).hexdigest())
        sizes.add((row['width'], row['height']))
        if len(data) != row['width'] * row['height'] * 4:
            issues.append(f"Reference byte size is invalid: {row['index']}")
        elif np.ptp(np.frombuffer(data, dtype=np.uint8).reshape(-1, 4)[:, :3]) <= 20:
            issues.append(f"Reference image is empty or insufficiently varied: {row['index']}")
    if len(hashes) < 8 or len(sizes) < 2:
        issues.append('Probe must exercise distinct visible images and actual output resizing')
    for row in actual:
        ref = by_tick.get(row['presented_tick'])
        if ref is None or row['index'] >= len(refs):
            issues.append('Candidate returned an unknown frame tag/index')
            continue
        source = reference / f"frame-{ref['index']}.rgba"
        output = candidate / f"frame-{row['index']}.rgba"
        same = source.read_bytes() == output.read_bytes()
        metadata = all(row[k] == ref[k] for k in ('width', 'height', 'dispfb1', 'display1'))
        delay = refs[row['index']]['presented_tick'] - row['presented_tick']
        valid = same and metadata and delay in (0, 1)
        if not valid:
            issues.append(f"Pixel, metadata or ordering mismatch: {row['index']}")
        frames.append({'index': row['index'], 'presented_tick': row['presented_tick'],
                       'identical_pixels': same, 'identical_metadata': metadata,
                       'presentation_calls_delayed': delay, 'bytes': output.stat().st_size})
    return {'scope': '16 procedural Vulkan scanouts with source changes, output resizing and reinitialization; not full gameplay',
            'reference': str(reference.resolve()), 'candidate': str(candidate.resolve()),
            'success': not issues, 'issues': issues, 'distinct_reference_images': len(hashes),
            'output_sizes': sorted(sizes), 'frames': frames}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = check(args.reference, args.candidate)
    args.out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'frames'}, indent=2))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
