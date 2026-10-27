"""Refresh only six verified EE MMI statements in existing generated bodies.

Every edit requires a decoded instruction comment and the exact old emitter
statement with matching rt/rd. Main ELF words are independently checked;
overlay words are checked against generated comments and opcode/register
encoding (not an independent overlay-binary certificate). Everything outside
the statement is preserved byte for byte, including PC and resume entries.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct

OPS = {(9,26): 'PEXEH', (9,27): 'PREVH', (9,30): 'PEXEW',
       (9,31): 'PROT3W', (41,26): 'PEXCH', (41,30): 'PEXCW'}
COMMENT = re.compile(r'// (0x[\da-fA-F]+): (0x[\da-fA-F]+)\s+(pexeh|prevh|pexew|prot3w|pexch|pexcw)\b')


def old_statement(op, rd, rt):
    if op in ('PEXEH', 'PEXCH'):
        expression = f'_mm_shufflelo_epi16(_mm_shufflehi_epi16(GPR_VEC(ctx, {rt}), _MM_SHUFFLE(2,3,0,1)), _MM_SHUFFLE(2,3,0,1))'
    elif op == 'PROT3W':
        expression = f'_mm_shuffle_epi32(GPR_VEC(ctx, {rt}), _MM_SHUFFLE(0,3,2,1))'
    elif op == 'PEXCW':
        expression = f'_mm_shuffle_epi32(GPR_VEC(ctx, {rt}), _MM_SHUFFLE(1,0,3,2))'
    elif op == 'PEXEW':
        expression = f'PS2_PEXEW(GPR_VEC(ctx, {rt}))'
    else:
        return ('{ __m128i mask = _mm_setr_epi8(14,15, 12,13, 10,11, 8,9, 6,7, 4,5, 2,3, 0,1); '
                f'SET_GPR_VEC(ctx, {rd}, PS2_SHUFFLE_EPI8(GPR_VEC(ctx, {rt}), mask)); }}')
    return f'SET_GPR_VEC(ctx, {rd}, {expression});'


def refresh(text, ram=None):
    edits, observations = [], []
    for match in COMMENT.finditer(text):
        address, word = int(match[1],16), int(match[2],16)
        op = OPS.get((word & 63, (word >> 6) & 31))
        if word >> 26 != 28 or op != match[3].upper():
            raise ValueError(f'Instruction mnemonic/encoding mismatch at {address:#x}')
        if ram is not None and (address + 4 > len(ram) or struct.unpack_from('<I', ram, address)[0] != word):
            raise ValueError(f'Original ELF word mismatch at {address:#x}')
        rd, rt = (word >> 11) & 31, (word >> 16) & 31
        new = f'SET_GPR_VEC(ctx, {rd}, PS2_{op}(GPR_VEC(ctx, {rt})));'
        # Bound the search to this instruction, including delay-slot comments.
        end_match = re.search(r'// 0x[\da-fA-F]+:', text[match.end():])
        end = match.end() + end_match.start() if end_match else len(text)
        block = text[match.end():end]
        old = old_statement(op, rd, rt)
        pattern = re.compile(r'\s*'.join(re.escape(part) for part in old.split()))
        hits = list(pattern.finditer(block))
        if len(hits) == 1:
            hit = hits[0]
            if old != new:
                edits.append((match.end()+hit.start(), match.end()+hit.end(), new))
        elif len(hits) == 0 and new in block:
            pass  # Idempotent, or PEXEW already calls the corrected macro.
        elif rd == 0 and not re.search(r'SET_GPR_VEC\(ctx,\s*0\s*,', block):
            pass  # Some emitter versions omit writes to zero entirely.
        else:
            raise ValueError(f'Expected one exact old/current {op} statement at {address:#x}, got {len(hits)}')
        observations.append({'address': address, 'word': word, 'op': op, 'rd': rd, 'rt': rt})
    for start,end,replacement in reversed(edits):
        text = text[:start]+replacement+text[end:]
    return text, observations, len(edits)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--elf', type=Path, required=True)
    parser.add_argument('--generated', type=Path, required=True)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args=parser.parse_args()
    from tools.diagnostics.reemit_ee_float_semantics import load_ram
    elf=args.elf.read_bytes()
    ram,_=load_ram(elf)
    args.out.mkdir(exist_ok=False,parents=True)
    prepared=[]
    counts=Counter()
    report={'scope':__doc__, 'elf_sha256':hashlib.sha256(elf).hexdigest(), 'applied':False,'files':[]}
    for kind,root in (('elf',args.generated),('overlay',args.native)):
        for source in sorted(root.glob('*.cpp')):
            before=source.read_bytes()
            text=before.decode('utf-8')
            if not COMMENT.search(text): continue
            updated,seen,edits=refresh(text,ram if kind=='elf' else None)
            for row in seen: counts[row['op']]+=1
            after=updated.encode('utf-8')
            if not edits:
                report['files'].append({'source':str(source.resolve()),'kind':kind,'edits':0,'instructions':seen})
                continue
            destination=args.out/kind/source.name
            destination.parent.mkdir(exist_ok=True)
            destination.write_bytes(after)
            report['files'].append({'source':str(source.resolve()),'kind':kind,'edits':edits,'instructions':seen,
                'before_sha256':hashlib.sha256(before).hexdigest(),'after_sha256':hashlib.sha256(after).hexdigest()})
            prepared.append((source,destination,before))
    if args.apply:
        for source,_,before in prepared:
            if source.read_bytes()!=before: raise ValueError('Source changed during preparation')
        for source,destination,before in prepared:
            backup=args.out/'before'/destination.parent.name/source.name
            backup.parent.mkdir(parents=True,exist_ok=True)
            backup.write_bytes(before)
            source.write_bytes(destination.read_bytes())
        report['applied']=True
    report['instruction_counts']=dict(counts)
    report['modified_files']=len(prepared)
    with (args.out/'report.json').open('x') as out:json.dump(report,out,indent=2)
    print(json.dumps({'applied':report['applied'],'modified_files':len(prepared),'instruction_counts':dict(counts)}))

if __name__=='__main__':main()
