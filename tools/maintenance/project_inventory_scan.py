import os,json,csv,collections,time
from pathlib import Path
root=Path.cwd(); out=root/'artifacts/project-audit/20261010'; out.mkdir(parents=True,exist_ok=True)
files=[]; dirs=[]; errors=[]; links=[]; top=collections.defaultdict(lambda:{'files':0,'bytes':0,'directories':0}); ext=collections.defaultdict(lambda:{'files':0,'bytes':0})
def failed(e): errors.append(str(e))
for folder,sub,names in os.walk(root,followlinks=False,onerror=failed):
 p=Path(folder)
 if p==out: sub[:]=[];continue
 rel=p.relative_to(root).as_posix(); dirs.append(rel)
 for name in list(sub):
  q=p/name
  try:
   if q.is_symlink() or getattr(q.stat(),'st_file_attributes',0)&0x400:
    links.append(q.relative_to(root).as_posix());sub.remove(name)
  except OSError as e:errors.append(str(e));sub.remove(name)
 if rel!='.': top[rel.split('/')[0]]['directories']+=1
 for name in names:
  q=p/name
  try:
   if q.is_symlink():links.append(q.relative_to(root).as_posix());continue
   st=q.stat(); r=q.relative_to(root).as_posix()
   files.append({'path':r,'bytes':st.st_size,'mtime':st.st_mtime})
   k=r.split('/')[0] if '/' in r else '(root)';top[k]['files']+=1;top[k]['bytes']+=st.st_size
   e=q.suffix.lower() or '(none)';ext[e]['files']+=1;ext[e]['bytes']+=st.st_size
  except OSError as e:errors.append(str(e))
files.sort(key=lambda x:x['path'].lower())
with (out/'files.csv').open('w',newline='',encoding='utf-8-sig') as s:
 w=csv.DictWriter(s,fieldnames=['path','bytes','mtime']);w.writeheader();w.writerows(files)
report={'root':str(root),'scanned_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'files':len(files),'directories':len(dirs),'bytes':sum(f['bytes'] for f in files),'top':dict(top),'extensions':dict(ext),'largest_files':sorted(files,key=lambda x:x['bytes'],reverse=True)[:45],'zero_byte_files':[f['path'] for f in files if f['bytes']==0],'links_not_followed':links,'errors':errors,'scope':'All regular files enumerated including hidden and Git data; audit output excluded. Links/junctions not followed. Live run files may grow during scan.'}
(out/'inventory.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
(out/'directories.txt').write_text('\n'.join(sorted(dirs,key=str.lower))+'\n',encoding='utf-8')
print(json.dumps({k:report[k] for k in ['files','directories','bytes','top','errors']},ensure_ascii=False))
