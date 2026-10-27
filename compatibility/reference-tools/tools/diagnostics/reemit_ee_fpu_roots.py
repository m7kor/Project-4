"""Re-emit existing reviewed EE bodies containing SQRT/RSQRT from original ELF words."""
import argparse
from collections import Counter
import hashlib,json,re,struct,subprocess
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--elf',type=Path,required=True)
    parser.add_argument('--generated',type=Path,required=True)
    parser.add_argument('--emitter',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    elf=args.elf.read_bytes()
    if elf[:7]!=b'\x7fELF\x01\x01\x01' or struct.unpack_from('<H',elf,18)[0]!=8:
        raise ValueError('Expected original little endian MIPS32 ELF')
    ram=bytearray(32*1024*1024);segments=[]
    ph=struct.unpack_from('<I',elf,28)[0];ents,count=struct.unpack_from('<HH',elf,42)
    if ents<32 or ph+ents*count>len(elf):raise ValueError('Invalid ELF header table')
    for i in range(count):
        kind,at,va,_,fs,ms,flags,align=struct.unpack_from('<8I',elf,ph+ents*i)
        if kind!=1:continue
        if va+ms>len(ram) or fs>ms or at+fs>len(elf):raise ValueError('Invalid ELF segment')
        ram[va:va+fs]=elf[at:at+fs];segments.append((va,va+fs,flags))
    found=subprocess.run(['rg','-l','FPU_SQRT_S|1.0f / sqrtf',str(args.generated),'-g','*.cpp'],capture_output=True,text=True)
    if found.returncode not in (0,1):raise RuntimeError(found.stderr)
    out=args.out.absolute();out.mkdir(parents=True,exist_ok=True)
    if out==args.generated.absolute():raise ValueError('Output must be separate from generated source tree')
    raw=out/'original-elf-ram.bin'
    if raw==args.elf.absolute():raise ValueError('Cannot replace original ELF')
    raw.write_bytes(ram)
    report={'schema':1,'elf_sha256':hashlib.sha256(elf).hexdigest(),'applied':False,'functions':[],'non_cop1_text_matches':[],
            'scope':'Original instruction words and prior explicit body bounds/resume entries; operand fix only, EE exceptional FPU behavior remains unverified.'}
    prepared=[]
    for filename in found.stdout.splitlines():
        source=Path(filename).absolute();original_bytes=source.read_bytes();old=original_bytes.decode('utf-8')
        old_sha=hashlib.sha256(original_bytes).hexdigest()
        bounds=re.search(r'// Address: (0x[\da-fA-F]+) - (0x[\da-fA-F]+)',old)
        signature=re.search(r'void (\w+)\(uint8_t\* rdram, R5900Context\* ctx, PS2Runtime \*runtime\)',old)
        if not bounds or not signature:raise ValueError('Unreviewed source format '+str(source))
        start,end=[int(v,16) for v in bounds.groups()]
        if start%4 or end%4 or end<=start or sum(a<=start and end<=b and flags&1!=0 for a,b,flags in segments)!=1:
            raise ValueError('Body is not uniquely mapped executable original bytes')
        words={};nops=[]
        for address,value in re.findall(r'// (0x[\da-fA-F]+): (0x[\da-fA-F]+)',old):
            at,word=int(address,16),int(value,16)
            if not start<=at<end or at%4 or at in words and words[at]!=word:raise ValueError('Invalid original source word map')
            words[at]=word
        expressions=Counter();sites=[]
        for at in range(start,end,4):
            word=struct.unpack_from('<I',ram,at)[0]
            if at not in words and word==0:nops.append(at)
            elif words.get(at)!=word:raise ValueError(f'Original word mismatch at {at:x}')
            if word>>26==17 and word>>21&31==16 and word&63 in (4,22):
                ft,fs,fd=(word>>16)&31,(word>>11)&31,(word>>6)&31
                expression=f'ctx->f[{fd}] = FPU_SQRT_S(ctx->f[{ft}]);' if word&63==4 else f'ctx->f[{fd}] = ctx->f[{fs}] / FPU_SQRT_S(ctx->f[{ft}]);'
                expressions[expression]+=1;sites.append({'address':at,'word':word,'expected_expression':expression})
        if not sites:
            report['non_cop1_text_matches'].append(str(source))
            continue
        entries=sorted(set(int(v,16) for v in re.findall(r'case (0x[\da-fA-F]+)u: goto label_',old)))
        plan=out/(source.stem+'.toml');new=out/source.name
        plan.write_text(f'schema = 1\nimage = {json.dumps(raw.as_posix())}\nstart = {start}\nend = {end}\nname = {json.dumps(signature[1])}\nentries = {json.dumps(entries)}\n')
        result=subprocess.run([str(args.emitter.absolute()),str(plan),str(new)],capture_output=True,text=True)
        if result.returncode:raise RuntimeError(result.stderr)
        emitted=new.read_text()
        def unrelated_lines(text):
            result=[]
            for line in text.splitlines():
                line=line.strip()
                if not line or line.startswith('// Function:'):continue
                if line.startswith('ctx->f[') and ('FPU_SQRT_S(' in line or '1.0f / sqrtf(' in line):continue
                result.append(line)
            return result
        if unrelated_lines(old)!=unrelated_lines(emitted):
            raise ValueError('Re-emission changed code outside root operand expressions')
        for expression,count in expressions.items():
            if emitted.count(expression)!=count:raise ValueError('Emitter did not apply original operand semantics')
        for entry in entries:
            if f'case 0x{entry:x}u:' not in emitted:raise ValueError('Lost preexisting resume entry')
        report['functions'].append({'source':str(source),'start':start,'end':end,'original_words_verified':(end-start)//4,
            'original_nops_omitted_by_emitter':nops,'resume_entries':entries,'sites':sites,'before_sha256':old_sha,
            'after_sha256':hashlib.sha256(new.read_bytes()).hexdigest()})
        prepared.append((source,new,old_sha))
    # Complete preparation and all guards before any mutation of the generated tree.
    if args.apply:
        for source,new,old_sha in prepared:
            if hashlib.sha256(source.read_bytes()).hexdigest()!=old_sha:raise ValueError('Source changed during preparation')
        backup=out/'before';backup.mkdir(exist_ok=True)
        for source,new,old_sha in prepared:
            saved=backup/source.name
            if saved.exists() and saved.read_bytes()!=source.read_bytes():raise ValueError('Different existing backup')
        for source,new,old_sha in prepared:
            (backup/source.name).write_bytes(source.read_bytes());source.write_bytes(new.read_bytes())
        report['applied']=True
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(f'Re-emitted {len(prepared)} original bodies; applied={report["applied"]}')

if __name__=='__main__':main()
