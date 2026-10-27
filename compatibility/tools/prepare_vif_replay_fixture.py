"""Reproduce the narrow private fixture from four existing DIRECT captures."""
from pathlib import Path
import argparse,hashlib,json,struct
ROOT=Path(__file__).resolve().parents[1]
ORIGIN=Path('C:/Project/PS2redmption/artifacts/verification/review-20261013-vif-direct-source-audio-v27-vif')
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    out=args.out.resolve()
    if not out.is_relative_to((ROOT/'artifacts').resolve()):raise ValueError('Output must stay in lab artifacts')
    # The existing provenance manifest pins the complete original capture bytes.
    manifest=json.loads((ROOT/'artifacts/phase2/vif-direct/manifest.json').read_text())
    data=bytearray(struct.pack('<4Q',0x31594c5052464956,1,4,0))
    for i,event in enumerate(manifest['events']):
        raw=(ORIGIN/f'source-direct-{i}.viftrace').read_bytes()
        if hashlib.sha256(raw).hexdigest()!=event['source_sha256']:raise ValueError('Original capture identity changed')
        h=struct.unpack_from('<16Q',raw)
        if h[0]!=0x3143524944464956 or h[1]!=1 or h[2]!=i or len(raw)!=128+h[3]+h[4]:raise ValueError('Invalid source capture')
        payload=raw[128+h[3]:]
        if hashlib.sha256(payload).hexdigest()!=event['payload_sha256']:raise ValueError('DIRECT payload identity changed')
        data+=struct.pack('<6Q',i,h[9],h[4],h[6],h[15],h[8])+payload
    if hashlib.sha256(data).hexdigest()!=manifest['fixture_sha256']:raise ValueError('Normalized fixture differs')
    out.mkdir(parents=True,exist_ok=False)
    (out/'fixture.bin').write_bytes(data)
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2))
    print('Reproduced four captured DIRECT events; no game launch or golden overwrite')
if __name__=='__main__':main()
