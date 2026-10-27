import struct
import unittest
from tools.diagnostics.snr2_native_plan import build_plan
from tools.diagnostics.snr2_sdk_lifecycle import prepare


class StrictSdkLifecycleTests(unittest.TestCase):
    def fixture(self, shift=0, alias_node=False):
        data = bytearray(2048)
        code = [0x40+shift+i*16 for i in range(6)]
        ctors, dtors = 0x600+shift, 0x60c+shift
        frame, cursor, head, node = 0x61c+shift, 0x640+shift, 0x650+shift, 0x658+shift
        variables = [cursor, ctors, head, head, head if alias_node else node, frame]
        struct.pack_into('<15I', data, 0, 0x32524e53,0,0,512,6,640,code[1],code[0],0,0,128,2048,0,1024,1024)
        data[640:652] = b'fixture.elf\0'
        names = ['__register_frame_info_table','__deregister_frame_info','sn_reg_frame',
                 'sn_dereg_frame','__CTOR_LIST__','__DTOR_LIST__']
        values = code[2:] + [ctors,dtors]
        string_at = 652
        for i, (name, value) in enumerate(zip(names,values)):
            encoded = name.encode()+b'\0'
            data[string_at:string_at+len(encoded)] = encoded
            struct.pack_into('<IIHBB',data,512+i*12,string_at,value,i,2,0)
            string_at += len(encoded)
        relocation = bytearray()
        previous = 0
        for at, variable in zip(code,variables):
            struct.pack_into('<4I',data,at,0x3c080000,0x25080000|variable,0x03e00008,0)
            for offset, kind in ((at,1),(at+4,0)):
                delta = offset-previous
                if 0 < delta <= 252 and delta%4 == 0:
                    relocation.append(delta|kind)
                else:
                    relocation.append(kind)
                    relocation.extend(struct.pack('<I',offset))
                previous = offset
        relocation.extend(b'\0\0\0\0\0')
        data[1024:1024+len(relocation)] = relocation
        struct.pack_into('<3I',data,ctors,1,code[4],0)
        struct.pack_into('<3I',data,dtors,1,code[5],0)
        struct.pack_into('<I',data,cursor,dtors+4)
        roles = dict(frame_head_offset=head,frame_node_offset=node,
                     frame_table_offset=frame,destructor_cursor_offset=cursor)
        plan = build_plan(data,[(at,at+16) for at in code],'sdk_fixture')
        return data, plan, roles

    def test_shifted_code_and_data_preserve_signature_and_expected_roles(self):
        template, plan, roles = self.fixture()
        candidate, expected, mapped = self.fixture(0x100)
        result, report = prepare(template,plan,candidate,'sdk_fixture',roles)
        self.assertEqual(result,expected)
        for key, value in mapped.items(): self.assertEqual(report['roles'][key],value)
        self.assertEqual(len(report['bodies']),6)
        self.assertFalse(report['execution_verified'])

    def test_instruction_relocation_and_template_identity_corruption_reject(self):
        template, plan, roles = self.fixture()
        for variant in range(3):
            candidate, _, _ = self.fixture(0x100)
            changed_plan = dict(plan)
            if variant == 0: candidate[0x160+3] ^= 0x40
            elif variant == 1: candidate[1024:1029] = b'\0'*5
            else: changed_plan['identity'] = 'wrong-original'
            with self.assertRaises(ValueError):
                prepare(template,changed_plan,candidate,'sdk_fixture',roles)

    def test_extra_ctor_callback_and_nonempty_frame_state_reject(self):
        template, plan, roles = self.fixture()
        for offset in (0x700,0x750,0x758):
            candidate, _, _ = self.fixture(0x100)
            struct.pack_into('<I',candidate,offset,2)
            with self.assertRaises(ValueError): prepare(template,plan,candidate,'sdk_fixture',roles)

    def test_aliased_data_and_unreviewed_data_role_reject(self):
        template, plan, roles = self.fixture()
        candidate, _, _ = self.fixture(0x100,alias_node=True)
        with self.assertRaises(ValueError): prepare(template,plan,candidate,'sdk_fixture',roles)
        candidate, _, _ = self.fixture(0x100)
        for changed in ({**roles,'frame_node_offset':0x123}, {**roles,'extra_offset':0x400}):
            with self.assertRaises(ValueError): prepare(template,plan,candidate,'sdk_fixture',changed)


if __name__ == '__main__':
    unittest.main()
