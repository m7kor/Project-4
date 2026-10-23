"""Publish one bounded controller command to an owned running diagnostic."""
import argparse
import json
import os
from pathlib import Path
import re
import tempfile
import time

HEADER = 'sequence,begin,end,buttons,lx,ly,rx,ry\n'


def command_text(sequence, tick, delay, duration, buttons, axes):
    values = [sequence, tick, delay, duration, buttons, *axes]
    if len(axes) != 4 or any(type(v) is not int for v in values):
        raise ValueError('Integer sequence, tick, interval, buttons and four axes required')
    if not (0 < sequence < 2**64 and 0 <= tick < 2**64 and 2 <= delay <= 120
            and 1 <= duration <= 180 and tick + delay + duration < 2**64
            and 0 <= buttons <= 65535 and all(0 <= axis <= 255 for axis in axes)):
        raise ValueError('Command outside native diagnostic bounds')
    begin = tick + delay
    return HEADER + ','.join(map(str, [sequence, begin, begin + duration, buttons, *axes])) + '\n'


def observed_tick(state_text, log_text):
    ticks = []
    for line in reversed(state_text.splitlines()):
        try:
            value = json.loads(line)['ee_vsync_tick']
            if type(value) is int and value >= 0:
                ticks.append(value)
                break
        except (ValueError, KeyError, TypeError):
            continue
    for line in log_text.splitlines():
        if line.startswith('[pad live]'):
            match = re.search(r'\btick=(\d+)', line)
            if match:
                ticks.append(int(match[1]))
        elif line.startswith('[pad trace]') and ('stage=replay ' in line or 'stage=live ' in line):
            match = re.search(r'\bee_tick=(\d+)', line)
            if match:
                ticks.append(int(match[1]))
    if not ticks:
        raise ValueError('No observed EE tick; command cannot be scheduled')
    return max(ticks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--duration', type=int, required=True)
    parser.add_argument('--delay', type=int, default=100)
    parser.add_argument('--buttons', type=int, default=65535)
    for axis in ('lx', 'ly', 'rx', 'ry'):
        parser.add_argument('--' + axis, type=int, default=128)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    run = args.run.resolve(strict=True)
    run.relative_to(root / 'artifacts/runs')
    if run.parent.name != 'captures' or (run / 'report.json').exists():
        raise ValueError('An unfinished owned diagnostic capture is required')
    owner = run.parents[1]
    identity = json.loads((owner / 'identity.json').read_text(encoding='utf-8'))
    destination = Path(identity['settings']['PS2X_NATIVE_PAD_LIVE'])
    if destination.resolve() != owner / 'live-pad.csv' or destination.is_symlink():
        raise ValueError('Unexpected live input path')
    history = owner / 'live-commands'
    history.mkdir(exist_ok=True)
    prior = [int(path.stem) for path in history.glob('*.json') if path.stem.isdecimal()]
    sequence = max(prior, default=0) + 1
    log_path = run / 'stderr.txt'
    offset = log_path.stat().st_size
    log_text = log_path.read_text(encoding='utf-8', errors='replace')
    tick = observed_tick((run / 'diagnostics/state.jsonl').read_text(encoding='utf-8'), log_text)
    text = command_text(sequence, tick, args.delay, args.duration, args.buttons,
                        [args.lx, args.ly, args.rx, args.ry])
    receipt_path = history / f'{sequence:06d}.json'
    receipt = {'sequence': sequence, 'observed_tick': tick, 'command': text, 'status': 'prepared',
               'published_unix_ns': time.time_ns(), 'scope': 'Native acceptance is not EE/gameplay response proof'}
    with receipt_path.open('x', encoding='utf-8') as stream:
        json.dump(receipt, stream, indent=2)
    # Publish a complete file in one rename; the runtime never sees our write in progress.
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n', dir=owner,
                                     prefix='.live-pad-', suffix='.tmp', delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(text)
    try:
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    deadline = time.monotonic() + 5
    receipt['status'] = 'no_acknowledgement'
    with log_path.open('rb') as stream:
        stream.seek(offset)
        pending = b''
        while time.monotonic() < deadline:
            pending += stream.read(65536)
            lines = pending.split(b'\n')
            pending = lines.pop()
            for raw in lines:
                line = raw.decode('utf-8', errors='replace')
                if line.startswith('[pad live] rejected ') or (line.startswith('[pad live] accepted ')
                        and re.search(r'\bsequence=' + str(sequence) + r'\b', line)):
                    receipt.update(status='accepted' if ' accepted ' in line else 'rejected', acknowledgement=line)
                    break
            if receipt['status'] != 'no_acknowledgement' or (run / 'report.json').exists():
                break
            time.sleep(0.05)
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps(receipt))
    if receipt['status'] != 'accepted':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
