import csv,collections,hashlib,json,concurrent.futures,time
from pathlib import Path
root=Path.cwd();out=root/'artifacts/project-audit/20261010'
rows=list(csv.DictReader((out/'files.csv').open(encoding='utf-8-sig'))); sizes=collections.defaultdict(list)
for f in rows:
 if '.git' not in Path(f['path']).parts and int(f['bytes'])>0:sizes[int(f['bytes'])].append(f)
candidates=[f for v in sizes.values() if len(v)>1 for f in v]
def hashed(f):
 p=root/f['path'];before=p.stat();h=hashlib.sha256()
 with p.open('rb') as s:
  for b in iter(lambda:s.read(2*1024**2),b''):h.update(b)
 after=p.stat()
 return {'path':f['path'],'bytes':int(f['bytes']),'sha256':h.hexdigest() if before.st_size==after.st_size and before.st_mtime_ns==after.st_mtime_ns else None,'changed_during_hash':before.st_size!=after.st_size or before.st_mtime_ns!=after.st_mtime_ns,'file_id':str(after.st_ino),'device':str(after.st_dev),'links':after.st_nlink}
groups=collections.defaultdict(list);errors=[];count=0
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
 jobs={pool.submit(hashed,f):f for f in candidates}
 for future in concurrent.futures.as_completed(jobs):
  f=jobs[future]
  try:
   x=future.result()
   if x['sha256']:groups[(x['bytes'],x['sha256'])].append(x)
   else:errors.append({'path':f['path'],'error':'changed during hash'})
  except OSError as e:errors.append({'path':f['path'],'error':str(e)})
  count+=1
  if count%10000==0:print('hashed',count,flush=True)
result={'schema':1,'scope':'Exact SHA256 comparison for every nonempty regular file with a colliding size, excluding Git metadata. Content equality is not proof that one path can be removed. Unique-size files cannot have an exact duplicate within this inventory. Changed files excluded.','candidate_files':len(candidates),'hashed_bytes':sum(int(f['bytes']) for f in candidates),'groups':[{'bytes':n,'sha256':h,'files':sorted(v,key=lambda x:x['path'].lower())} for (n,h),v in groups.items() if len(v)>1],'errors':errors}
result['groups'].sort(key=lambda g:-g['bytes']*(len(g['files'])-1))
(out/'exact-duplicates.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
print(json.dumps({'candidate_files':len(candidates),'duplicate_groups':len(result['groups']),'errors':len(errors),'hashed_gib':round(result['hashed_bytes']/1024**3,2)}),flush=True)
