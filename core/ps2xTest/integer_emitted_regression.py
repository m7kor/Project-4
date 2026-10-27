"""Compile actual emitter output; integer oracle uses Python arbitrary precision.

The context shim checks result/exception suppression, not EPC/BD or full EE state.
Run from CTest on Clang/GCC, or manually with clang++ in a Windows developer shell.
Only procedural instruction words and values are used; no game data is required.
"""
from pathlib import Path
import argparse,json,random,subprocess,tempfile

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--probe',type=Path,required=True)
    p.add_argument('--runtime-header',type=Path,required=True)
    p.add_argument('--cxx',required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    emitted=subprocess.check_output([str(a.probe.resolve())],text=True)
    header=a.runtime_header.read_text(encoding='utf-8')
    legacy=header[header.index('#define ADD32_OV'):header.index('#define MUL32')]
    prefix='''#include <cstdint>
#include <climits>
#include <iostream>
struct Ctx { uint64_t r[32]{}; int exceptions=0; };
struct Runtime { void SignalException(Ctx*c,int){++c->exceptions;} };
#define EXCEPTION_INTEGER_OVERFLOW 12
#define GPR_U32(c,i) ((uint32_t)(c)->r[i])
#define GPR_S32(c,i) ((int32_t)(c)->r[i])
#define GPR_U64(c,i) ((c)->r[i])
#define GPR_S64(c,i) ((int64_t)(c)->r[i])
#define SET_GPR_S32(c,i,v) do{if(i)(c)->r[i]=(uint64_t)(int64_t)(int32_t)(v);}while(0)
#define SET_GPR_S64(c,i,v) do{if(i)(c)->r[i]=(uint64_t)(v);}while(0)
#define SET_GPR_U64(c,i,v) do{if(i)(c)->r[i]=(uint64_t)(v);}while(0)
'''+legacy+'\n'
    functions=[];tests=[];rng=random.Random(104729)
    for line in emitted.splitlines():
        op,body=line.split('\t',1)
        if op not in ('add','sub','dadd','dsub','addi','daddi','daddiu'):raise ValueError('Unsupported emitted operation')
        functions.append('void f_'+op+'(Ctx*ctx,Runtime*runtime){'+body+'}')
        width=32 if op in ('add','sub','addi') else 64;mask=(1<<width)-1
        edges=[0,1,(1<<(width-1))-1,1<<(width-1),mask,mask-1]
        values=[(x,y) for x in edges for y in edges]+[(rng.getrandbits(width),rng.getrandbits(width)) for _ in range(100)]
        dest=2 if op in ('addi','daddi','daddiu') else 3
        signed=lambda n:n-(1<<width) if n&(1<<(width-1)) else n
        for x,y in values:
            operand=1 if dest==2 else y
            exact=signed(x)-signed(operand) if op in ('sub','dsub') else signed(x)+signed(operand)
            overflow=int(op!='daddiu' and not -(1<<(width-1))<=exact<(1<<(width-1)))
            result=exact&mask
            if width==32 and result&(1<<31):result|=((1<<64)-1)^mask
            expected=(y if dest==2 else 0x12345678) if overflow else result
            tests.append('{Ctx c;Runtime r;c.r[1]='+str(x)+'ull;c.r[2]='+str(y)+'ull;c.r[3]=0x12345678;f_'+op+'(&c,&r);if(c.exceptions!='+str(overflow)+'||c.r['+str(dest)+']!='+str(expected)+'ull){std::cerr<<"'+op+' result/exception mismatch";return 2;}}')
    if len(functions)!=7:raise ValueError('Incomplete emitter capture')
    with tempfile.TemporaryDirectory(prefix='integer-',dir=a.output) as directory:
        work=Path(directory).resolve();src=work/'emitted.cpp';exe=work/('emitted.exe' if __import__('os').name=='nt' else 'emitted')
        src.write_text(prefix+'\n'.join(functions)+'\nint main(){'+'\n'.join(tests)+'return 0;}')
        subprocess.run([a.cxx,'-std=c++20','-O2','-fsanitize=undefined','-fno-sanitize-recover=all',str(src),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)
    print(json.dumps({'passed':True,'checks':len(tests),'ubsan':True,'scope':'emitted integer values and exception suppression, not full EE hardware'}))
    return 0
if __name__=='__main__':raise SystemExit(main())
