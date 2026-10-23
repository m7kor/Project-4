import json,struct,sys,tempfile,unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch
from tools.diagnostics import reemit_ee_fpu_roots as tool

class ReemitRootGuards(unittest.TestCase):
    def fixture(self,root):
        elf=bytearray(512);elf[:7]=b'\x7fELF\x01\x01\x01'
        struct.pack_into('<H',elf,18,8);struct.pack_into('<I',elf,28,52)
        struct.pack_into('<HH',elf,42,32,1)
        struct.pack_into('<8I',elf,52,1,256,64,64,12,12,5,4)
        struct.pack_into('<3I',elf,256,0x460c0004,0x03e00008,0)
        path=root/'original.elf';path.write_bytes(elf)
        sources=root/'generated';sources.mkdir()
        source=sources/'probe.cpp'
        old='''// Function: probe
// Address: 0x40 - 0x4c
void probe(uint8_t* rdram, R5900Context* ctx, PS2Runtime *runtime) {
    // 0x40: 0x460c0004 sqrt
    ctx->f[0] = FPU_SQRT_S(ctx->f[0]);
    // 0x44: 0x03e00008 jr
    // 0x48: 0x00000000 nop
    ctx->pc = 0x4c;
}
'''
        source.write_text(old)
        return path,sources,source,old

    def execute(self,root,change=None):
        elf,sources,source,old=self.fixture(root)
        out=root/'out'
        def run(command,**kwargs):
            if command[0]=='rg':return CompletedProcess(command,0,str(source)+'\n','')
            generated=old.replace('FPU_SQRT_S(ctx->f[0])','FPU_SQRT_S(ctx->f[12])')
            if change=='unrelated':generated=generated.replace('ctx->pc = 0x4c','ctx->pc = 0x48')
            Path(command[2]).write_text(generated)
            if change=='concurrent':source.write_text(old+'// user edit\n')
            return CompletedProcess(command,0,'','')
        argv=['tool','--elf',str(elf),'--generated',str(sources),'--emitter',str(root/'emitter.exe'),'--out',str(out),'--apply']
        with patch.object(sys,'argv',argv),patch.object(tool.subprocess,'run',side_effect=run):
            tool.main()
        return source,old,out

    def test_reemit_preserves_original_backup_and_reports_exact_operand(self):
        with tempfile.TemporaryDirectory() as temp:
            source,old,out=self.execute(Path(temp))
            self.assertIn('FPU_SQRT_S(ctx->f[12])',source.read_text())
            self.assertEqual((out/'before'/'probe.cpp').read_text(),old)
            report=json.loads((out/'report.json').read_text())
            self.assertTrue(report['applied'])
            self.assertEqual(report['functions'][0]['sites'][0]['word'],0x460c0004)

    def test_unrelated_emitter_change_cannot_replace_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with self.assertRaisesRegex(ValueError,'outside root'):self.execute(root,'unrelated')
            self.assertIn('FPU_SQRT_S(ctx->f[0])',(root/'generated'/'probe.cpp').read_text())

    def test_concurrent_source_edit_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with self.assertRaisesRegex(ValueError,'changed during'):self.execute(root,'concurrent')
            self.assertTrue((root/'generated'/'probe.cpp').read_text().endswith('// user edit\n'))

if __name__=='__main__':unittest.main()
