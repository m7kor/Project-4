"""Prepare ONLY a strict match of a caller-reviewed six-body SDK lifecycle."""
import argparse
import json
from pathlib import Path
import struct

from tools.diagnostics.snr2_inventory import parse_snr2
from tools.diagnostics.snr2_native_plan import build_plan, write_plan
from tools.diagnostics.snr2_relocations import compact_relocations

FUNCTIONS = ('__register_frame_info_table', '__deregister_frame_info',
             'sn_reg_frame', 'sn_dereg_frame')
DATA_ROLES = ('frame_head_offset', 'frame_node_offset',
              'frame_table_offset', 'destructor_cursor_offset')


def definition(metadata, name):
    values = [s['value'] for s in metadata['symbols']
              if s['name'] == name and s['raw_type'] in (2, 3)]
    if len(values) != 1 or not 60 <= values[0] < metadata['bytes']:
        raise ValueError('Missing or ambiguous SDK definition: ' + name)
    return values[0]


def roots(metadata):
    return {'constructor': metadata['constructor_offset'],
            'destructor': metadata['destructor_offset'],
            **{name: definition(metadata, name) for name in FUNCTIONS}}


def prepare(template, template_plan, candidate, identifier, data_roles):
    if set(data_roles) != set(DATA_ROLES) or any(type(v) is not int or v < 60 for v in data_roles.values()):
        raise ValueError('Template data roles must be four explicit reviewed integer offsets')
    tm, cm = parse_snr2(template), parse_snr2(candidate)
    tr, cr = roots(tm), roots(cm)
    reviewed = {b['start']: b for b in template_plan['bodies']}
    if len(reviewed) != 6 or set(reviewed) != set(tr.values()):
        raise ValueError('Template must contain exactly the six reviewed SDK bodies')
    expected = build_plan(template, [(b['start'], b['end']) for b in reviewed.values()],
                          template_plan['identifier'])
    for key in ('identity', 'bytes', 'instruction_relocations'):
        if expected[key] != template_plan[key]:
            raise ValueError('Template plan does not describe this original image: ' + key)
    candidate_bodies = [(cr[role], cr[role] + reviewed[at]['end'] - at) for role, at in tr.items()]
    plan = build_plan(candidate, candidate_bodies, identifier)
    ta = {r['offset']: r['type'] for r in expected['instruction_relocations']}
    ca = {r['offset']: r['type'] for r in plan['instruction_relocations']}
    tl = {r['offset']: r for r in compact_relocations(template)}
    cl = {r['offset']: r for r in compact_relocations(candidate)}
    te = {r['offset']: r for r in tm['relocations']}
    ce = {r['offset']: r for r in cm['relocations']}
    address_map = {tr[role]: cr[role] for role in tr}
    checked = []
    for role, start in tr.items():
        body, other = reviewed[start], cr[role]
        for delta in range(0, body['end'] - start, 4):
            at, bt = start + delta, other + delta
            kind = ta.get(at)
            if kind != ca.get(bt):
                raise ValueError(f'SDK relocation type/position mismatch in {role}+{delta:#x}')
            mask = 0x3ffffff if kind == 4 else 0xffff if kind else 0
            aw, bw = struct.unpack_from('<I', template, at)[0], struct.unpack_from('<I', candidate, bt)[0]
            if (aw & ~mask) != (bw & ~mask):
                raise ValueError(f'SDK instruction shape mismatch in {role}+{delta:#x}')
            if kind:
                if (at in tl) != (bt in cl):
                    raise ValueError('SDK local/external relocation mismatch')
                if at in tl:
                    a, b = tl[at], cl[bt]
                    if kind in (4, 5):
                        old, new = a['target_offset'], b['target_offset']
                        if old in address_map and address_map[old] != new:
                            raise ValueError('Inconsistent SDK function/data relocation target')
                        address_map[old] = new
                    if kind == 5:
                        if ([x-at for x in a['pair_scan_offsets']] !=
                                [x-bt for x in b['pair_scan_offsets']]):
                            raise ValueError('SDK HI16/LO16 pairing topology mismatch')
                else:
                    a, b = te[at], ce[bt]
                    sa, sb = tm['symbols'][a['symbol_index']], cm['symbols'][b['symbol_index']]
                    if (sa['name'], sa['raw_type'], sa['raw_auxiliary'], a['addend']) != (
                            sb['name'], sb['raw_type'], sb['raw_auxiliary'], b['addend']):
                        raise ValueError('Different SDK external import semantics')
        checked.append(dict(role=role, template_start=start, candidate_start=other,
                            bytes=body['end']-start, shape_verified=True))
    # LO16 words must also agree with each corresponding complete HI16 target.
    for role, start in tr.items():
        for delta in range(0, reviewed[start]['end']-start, 4):
            a, b = tl.get(start+delta), cl.get(cr[role]+delta)
            if a and a['type'] == 6 and a['target_offset'] in address_map:
                if b['target_offset'] != address_map[a['target_offset']] & 0xffff:
                    raise ValueError('SDK LO16 disagrees with matched address role')
    def table(data, metadata, name, entry):
        at = definition(metadata, name)
        if at + 12 > len(data) or struct.unpack_from('<3I', data, at) != (1, entry, 0):
            raise ValueError('SDK template requires exactly one original frame callback: ' + name)
        return at
    for data, metadata, entries in ((template, tm, tr), (candidate, cm, cr)):
        table(data, metadata, '__CTOR_LIST__', entries['sn_reg_frame'])
        table(data, metadata, '__DTOR_LIST__', entries['sn_dereg_frame'])
    if any(value not in address_map for value in data_roles.values()):
        raise ValueError('A reviewed template data role has no matching complete relocation target')
    roles = {name: address_map[data_roles[name]] for name in DATA_ROLES}
    roles.update(constructor_offset=cr['constructor'], destructor_offset=cr['destructor'],
                 sn_reg_frame_offset=cr['sn_reg_frame'], sn_dereg_frame_offset=cr['sn_dereg_frame'],
                 constructor_table_offset=definition(cm, '__CTOR_LIST__'),
                 destructor_table_offset=definition(cm, '__DTOR_LIST__'))
    for name in DATA_ROLES:
        at = roles[name]
        length = 24 if name == 'frame_node_offset' else 4
        if at & 3 or at < 60 or at + length > len(candidate) or any(
                at < end and start < at + length for start, end in candidate_bodies):
            raise ValueError('SDK data role overlaps code or exceeds image: ' + name)
    spans = [(roles[name], roles[name] + (24 if name == 'frame_node_offset' else 4)) for name in DATA_ROLES]
    if any(a < d and c < b for i, (a, b) in enumerate(spans) for c, d in spans[i+1:]):
        raise ValueError('SDK data roles unexpectedly alias one another')
    for name in ('frame_head_offset', 'frame_node_offset'):
        at, length = roles[name], 24 if name == 'frame_node_offset' else 4
        if any(candidate[at:at+length]):
            raise ValueError('SDK frame state is not the reviewed empty initial state')
    cursor = struct.unpack_from('<I', candidate, roles['destructor_cursor_offset'])[0]
    if cursor != roles['destructor_table_offset'] + 4:
        raise ValueError('SDK destructor cursor does not point at the original first entry')
    verification = dict(schema=1, template_identity=tm['sha256'], candidate_identity=cm['sha256'],
                        bodies=checked, roles=roles, address_role_map=address_map,
                        execution_verified=False,
                        scope='Strict reviewed SDK body shape and original single-frame tables only; '
                              'compile/canary/loader validation required. No game functions classified.')
    return plan, verification


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('template-image', 'template-plan', 'template-roles', 'module', 'out-prefix'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--identifier', required=True)
    args = parser.parse_args()
    inputs = {getattr(args, n).resolve() for n in ('template_image','template_plan','template_roles','module')}
    outputs = [Path(str(args.out_prefix)+suffix) for suffix in ('.toml','.json','.sdk-verification.json')]
    if any(p.resolve() in inputs for p in outputs):
        parser.error('Outputs must not replace original inputs')
    plan, verified = prepare(args.template_image.read_bytes(),
                             json.loads(args.template_plan.read_text(encoding='utf-8-sig')),
                             args.module.read_bytes(), args.identifier,
                             json.loads(args.template_roles.read_text(encoding='utf-8-sig')))
    write_plan(args.module, [(b['start'],b['end']) for b in plan['bodies']], args.identifier, outputs[0])
    outputs[1].write_text(json.dumps(plan,indent=2)+'\n',encoding='utf-8')
    outputs[2].write_text(json.dumps(verified,indent=2)+'\n',encoding='utf-8')
    print(f"Strict SDK match: {len(plan['bodies'])} bodies; execution still requires verification")


if __name__ == '__main__':
    main()
