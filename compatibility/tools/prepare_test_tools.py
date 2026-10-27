"""Idempotent setup of the existing LOCAL canary's runtime-root option."""
from pathlib import Path
import hashlib
ROOT=Path(__file__).resolve().parents[1]
path=(ROOT/'reference-tools/ps2l/canary.py').resolve(strict=True)
assert path.is_relative_to(ROOT.resolve()), 'Never patch an original reference through a junction'
data=path.read_bytes();text=data.decode().replace('\r\n','\n')
if "parser.add_argument('--runtime-root'" in text:
    print('Local canary already supports explicit read-only runtime headers')
else:
    anchor="    parser.add_argument('--out', type=Path, default=ROOT / 'artifacts/canary')\n"
    before="""        includes = [ROOT / 'core/ps2xRuntime/include', ROOT / 'core/ps2xRuntime/src/lib/Kernel',
                    ROOT / 'core/ps2xIOP/include', generated]"""
    after="""        includes = [args.runtime_root / 'ps2xRuntime/include', args.runtime_root / 'ps2xRuntime/src/lib/Kernel',
                    args.runtime_root / 'ps2xIOP/include', generated]"""
    assert text.count(anchor)==1 and text.count(before)==1, 'Unrecognized canary version; do not guess'
    backup=ROOT/'artifacts/tool-preparation'/('canary-before-'+hashlib.sha256(data).hexdigest()+'.py')
    backup.parent.mkdir(parents=True,exist_ok=True)
    if backup.exists():assert backup.read_bytes()==data
    else:backup.write_bytes(data)
    text=text.replace(anchor,anchor+"    parser.add_argument('--runtime-root', type=Path, default=ROOT / 'core',\n                        help='Existing read-only core headers; output stays under --out')\n").replace(before,after)
    path.write_bytes(text.replace('\n','\r\n' if b'\r\n' in data else '\n').encode())
    print('Prepared local canary; original projects untouched')
