"""Execute real emitted arithmetic with UBSan and independent integer oracles."""
from pathlib import Path
import argparse,hashlib,json,random,re,subprocess,time
ROOT=Path(__file__).resolve().parents[1]
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=(ROOT/a.out).resolve();assert out.is_relative_to(ROOT/'artifacts');out.mkdir(parents=True,exist_ok=False)
    report={'passed':False,'runs':[],'scope':'Actual production emitter strings compiled under UBSan; integer and exception oracle independent of C++ formulas, no game launch'}
    start=time.monotonic();rng=random.Random(104729)
    try:
        header=(ROOT/'engines/project4/ps2xRuntime/include/ps2_runtime_macros.h').read_text()
        legacy=header[header.index('#define ADD32_OV'):header.index('#define MUL32')]
        pre='#include <cstdint>\n#include <climits>\n#include <iostream>\n#include <string>\nstruct Ctx{uint64_t r[32]{};int exceptions=0;};struct Runtime{void SignalException(Ctx*c,int){++c->exceptions;}};\n#define EXCEPTION_INTEGER_OVERFLOW 12\n#define GPR_U32(c,i) ((uint32_t)(c)->r[i])\n#define GPR_S32(c,i) ((int32_t)(c)->r[i])\n#define GPR_U64(c,i) ((c)->r[i])\n#define GPR_S64(c,i) ((int64_t)(c)->r[i])\n#define SET_GPR_S32(c,i,v) do{if(i)(c)->r[i]=(uint64_t)(int64_t)(int32_t)(v);}while(0)\n#define SET_GPR_S64(c,i,v) do{if(i)(c)->r[i]=(uint64_t)(v);}while(0)\n#define SET_GPR_U64(c,i,v) do{if(i)(c)->r[i]=(uint64_t)(v);}while(0)\n'+legacy+'\n'
        cases={};checks=0
        for op in ['add','sub','dadd','dsub','addi','daddi','daddiu']:
            width=32 if op in ('add','sub','addi') else 64;mask=(1<<width)-1;bits=[0,1,(1<<(width-1))-1,1<<(width-1),mask,mask-1]
            pairs=[(x,y) for x in bits for y in bits]+[(rng.getrandbits(width),rng.getrandbits(width)) for _ in range(100)]
            body=[];dest=2 if op in ('addi','daddi','daddiu') else 3
            for x,y in pairs:
                signed=lambda z:z-(1<<width) if z&(1<<(width-1)) else z
                b=1 if dest==2 else y;exact=signed(x)-signed(b) if op in ('sub','dsub') else signed(x)+signed(b)
                overflow=int(op!='daddiu' and not -(1<<(width-1))<=exact<(1<<(width-1)))
                value=(exact&mask);value=value|(~mask&((1<<64)-1)) if width==32 and value&(1<<31) else value
                expected=y if dest==2 and overflow else 0x12345678 if overflow else value
                body.append(f'{{Ctx c;Runtime rt;c.r[1]={x}ull;c.r[2]={y}ull;c.r[3]=0x12345678;f_{op}(&c,&rt);if(c.exceptions!={overflow}||c.r[{dest}]!={expected}ull){{std::cerr<<"oracle mismatch {op}";return 2;}}}}')
            cases[op]='\n'.join(body);checks+=len(pairs)
        for label,folder in [('before','phase4-base'),('after','phase4-fixed-01')]:
            build=ROOT/'lab'/folder;identity=json.loads((build/'identity.json').read_text())
            digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
            for name,value in identity['sources'].items():
                if digest(name)!=value:raise ValueError('Stale emitter source: '+name)
            for name,value in identity['binaries'].items():
                if digest(build/name)!=value:raise ValueError('Changed emitter executable: '+name)
            probe=build/'probe.exe';text=subprocess.check_output([probe],text=True);(out/(label+'-emitted.txt')).write_text(text)
            funcs='\n'.join('void f_'+name+'(Ctx*ctx,Runtime*runtime)'+('{' if not code.startswith('{') else '')+code+('}' if not code.startswith('{') else '') for name,code in [line.split('\t',1) for line in text.splitlines()])
            main='int main(int argc,char**argv){std::string op=argc>1?argv[1]:"";'+''.join('if(op=="'+k+'"){' +v+'return 0;}' for k,v in cases.items())+'return 3;}'
            src=out/(label+'.cpp');src.write_text(pre+funcs+'\n'+main);exe=out/(label+'.exe')
            cmd=['C:/Program Files/LLVM/bin/clang++.exe','-std=c++20','-O2','-fsanitize=undefined','-fno-sanitize-recover=all',str(src),'-o',str(exe)]
            subprocess.run(cmd,cwd=out,check=True)
            for op in cases:
                r=subprocess.run([exe,op],capture_output=True,text=True);(out/(label+'-'+op+'.stderr.txt')).write_text(r.stderr)
                report['runs'].append({'version':label,'operation':op,'returncode':r.returncode,'ubsan_detected':'runtime error:' in r.stderr})
        report['checks_per_version']=checks;report['passed']=all(r['returncode']==0 for r in report['runs'] if r['version']=='after') and any(r['ubsan_detected'] for r in report['runs'] if r['version']=='before')
        if not report['passed']:raise ValueError('Expected original UB and a clean corrected emission')
    except Exception as exc:report['error']=str(exc)
    report['seconds']=time.monotonic()-start;(out/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report));return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
