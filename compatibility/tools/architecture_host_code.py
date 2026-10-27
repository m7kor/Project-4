"""Inspect one actually linked hot VU function; raw assembly stays private."""
from pathlib import Path
import collections,hashlib,json,re,struct,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'artifacts/architecture'/('host-code-01' if len(sys.argv)==1 else sys.argv[1]);assert out.parent==ROOT/'artifacts/architecture';out.mkdir(exist_ok=False)
exe=ROOT/'lab/shared-link/ps2x_vu1_bench.exe';pdb=exe.with_suffix(exe.suffix+'.pdb');baseline=ROOT/'lab/phase4-suite-02/ps2x_vu1_bench.exe';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(exe)==sha(baseline)=='75f8c403b362f87403714d4d1808b9549b767302f896e1d73de51cb50b49dfd5'
tool=Path('C:/Program Files/LLVM/bin');p=subprocess.run([str(tool/'llvm-pdbutil.exe'),'pretty','--module-syms','--globals',str(pdb)],capture_output=True,text=True,timeout=60);assert p.returncode==0,p.stderr
(out/'pdb-symbols.txt').write_text(p.stdout);(out/'pdb-stderr.txt').write_text(p.stderr)
name='VU1CompiledPrograms::fused_770ea85198e8e87f_12b8';symbols=[]
for line in p.stdout.splitlines():
 m=re.search(r'func \[0x([0-9a-fA-F]+)\+.*?sizeof=\s*(\d+)\].*?__cdecl (.+)',line)
 if m:symbols.append((int(m[1],16),int(m[2]),m[3]))
symbols=list(dict.fromkeys(symbols));matches=[x for x in symbols if name+'(' in x[2]];assert len(matches)==1,matches
rva,size,signature=matches[0];data=exe.read_bytes();pe=struct.unpack_from('<I',data,0x3c)[0];assert data[pe:pe+4]==b'PE\0\0' and struct.unpack_from('<H',data,pe+24)[0]==0x20b
base=struct.unpack_from('<Q',data,pe+24+24)[0]
p=subprocess.run([str(tool/'llvm-objdump.exe'),'--disassemble','--no-show-raw-insn','--start-address='+hex(base+rva),'--stop-address='+hex(base+rva+size),str(exe)],capture_output=True,text=True,timeout=30);assert p.returncode==0,p.stderr
(out/'hot-block.s').write_text(p.stdout);instructions=[(int(a,16),op,args) for a,op,args in re.findall(r'^\s*([0-9a-f]+):\s+(\w+)\s*(.*)$',p.stdout,re.M)]
calls=[]
for address,op,args in instructions:
 if not op.startswith('call'):continue
 target=re.search(r'0x([0-9a-f]+)',args);label='indirect/unresolved'
 if target:
  dest=int(target[1],16)-base;hit=next((n for a,s,n in symbols if a<=dest<a+s),None);label=hit or 'unresolved direct target'
 calls.append({'offset':address-(base+rva),'target':label})
report={'binary_sha256':sha(exe),'pdb_sha256':sha(pdb),'function':name,'rva':hex(rva),'machine_code_bytes':size,'static_instructions':len(instructions),'static_opcode_counts':dict(collections.Counter(x[1] for x in instructions)),'static_call_sites':calls,'stack_memory_operand_count':sum(bool(re.search(r'%(?:rsp|rbp)\b',x[2])) for x in instructions),'scope':'Actual linked baseline machine code, not source-only speculation. Static counts are NOT dynamic cost or proof of spills. Raw disassembly is private game-derived material and must not be published.'}
(out/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k not in ('static_opcode_counts','static_call_sites')},indent=2));print('Call targets',collections.Counter(x['target'] for x in calls).most_common(8))
