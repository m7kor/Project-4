import json,csv,collections
from pathlib import Path
root=Path.cwd();out=root/'artifacts/project-audit/20261010';inv=json.loads((out/'inventory.json').read_text());dup=json.loads((out/'exact-duplicates.json').read_text())
rows=list(csv.DictReader((out/'files.csv').open(encoding='utf-8-sig')));dups={}
for i,g in enumerate(dup['groups'],1):
 for f in g['files']:dups[f['path']]=(i,len(g['files']))
def classify(p):
 parts=Path(p).parts;top=parts[0];name=parts[-1];low=name.lower()
 if '__pycache__' in parts or low.endswith(('.pyc','.pyo')):return 'cache','تنظيف مباشر','ذاكرة Python مؤقتة يعيد Python إنشاءها'
 if '.git' in parts:
  if low.startswith('tmp_pack_'):return 'fetch-temporary','مراجعة قبل تنظيف','ملف pack مؤقت كبير؛ تحقق من اكتمال Git وعدم وجود جلب جارٍ قبل حذفه'
  return 'git-metadata','احتفاظ','تاريخ المستودع أو الاعتماد؛ لا يُحذف كملف زائد'
 if low in ('license','license.md','license.txt','copying','copying.gplv3') or 'license' in low:return 'license','احتفاظ','ترخيص أو إشعار مصدر؛ تكراره لا يلغي الحاجة إليه'
 if top=='Resident Evil 4':return 'game-package','احتفاظ','ملفات نسخة التشغيل أو الحفظ المطلوبة'
 if top in ('mc0','mc1','saves') or low.endswith('.ps2') or '/saves/' in p or '/mc0/' in p or '/mc1/' in p:return 'save-data','احتفاظ','بطاقة حفظ أو نسخة احتياطية؛ لا يصنف التكرار مبررًا لحذفها'
 if top in ('game','bios'):return 'original-input','احتفاظ','مدخلات أصلية للاستنساخ والتحليل أو التشغيل'
 if p.startswith('core/out/build2/'):return 'secondary-build','أرشفة مرشحة','مجلد بناء ثانوي؛ المسار الافتراضي الحالي يستخدم core/out/build؛ راجع أي تعديلات داخل اعتماداته أولًا'
 if p.startswith('core/out/build/'):return 'active-build','احتفاظ الآن','البناء الحالي وأدواته واعتماداته؛ يمكن إعادة توليد أجزاء بعد حفظ مصدرها والتحقق'
 if p.startswith('core/deps/'):return 'third-party','احتفاظ','اعتمادات النواة؛ لا يستدل من عدم استدعاء الملف مباشرة أنه زائد'
 if top=='core':return 'core-source','احتفاظ','مصدر النواة والمحول والمحلل والاختبارات والمنصات؛ عدم استخدام منصة حاليًا لا يلغي فائدتها'
 if top in ('dependencies','integrations'):return 'audio-dependency','احتفاظ','مصادر SPU2 المحفوظة وتجهيز دمجها؛ موثقة في NATIVE_SPU2_INTEGRATION.md'
 if top in ('ps2l','tools','tests','profiles'):return 'project-source','احتفاظ','أداة أو اختبار أو تعريف لعبة؛ قد يستخدم مباشرة من الطرفية دون مرجع برمجي آخر'
 if top=='recomp':return 'generated-and-config','احتفاظ','إعداد التحويل ومخرجات C++ المستخدمة في البناء الحالي'
 if top=='resources':return 'reference','احتفاظ','مراجع المستخدم ونصوصه وصوره وPDF؛ المعرفة لا تحتاج مرجعًا في CMake لتكون مفيدة'
 if top in ('docs','knowledge'):return 'documentation','احتفاظ','التصميم والأدلة وسجل المعرفة؛ بعض الأقسام تاريخية وتتطلب قراءة تاريخها'
 if top in ('research','_research','.research'):return 'historical-research','أرشفة مرشحة','مصادر وأبحاث تاريخية خارج التشغيل المباشر؛ احتفظ بالتراخيص والبصمات والتقارير'
 if top=='tmp':return 'scratch','مراجعة قبل تنظيف','تجارب محلية صغيرة؛ بعض ELF والنصوص قد تحفظ حالة إعادة إنتاج'
 if top=='analysis':return 'analysis-evidence','أرشفة مرشحة','خرائط وتحليل وسجلات؛ نسخ السجل المتطابقة قابلة للتوحيد بعد تحديث المراجع'
 if top=='artifacts':
  if p=='artifacts/research/20261009/re4-native-modules.cpp':return 'active-build-source','احتفاظ','ملف C++ ظاهر صراحة ضمن build.ninja الحالي؛ حذف artifacts كاملًا يكسر البناء'
  if p.startswith(('artifacts/research/20261008/native-async-game/','artifacts/research/20261008/native-async-generated/','artifacts/research/20261010/')):return 'active-investigation','احتفاظ الآن','مدخلات أو مصادر أو أدلة التحقيق الجاري في الفيديو'
  if p.startswith('artifacts/runs/'):return 'run-evidence','أرشفة مرشحة','تقارير وصور وتتبعات تجارب؛ حفظ الأدلة أولًا وعدم كسر روابط report.json أو بصمات السجل'
  return 'generated-artifact','أرشفة مرشحة','نتيجة توليد أو اختبار أو بحث؛ تحقق من الوصفة والمراجع قبل تنظيفها'
 if '/' not in p:
  if name in ('run_stdout.txt','run_stderr.txt'):return 'root-run-log','أرشفة مرشحة','سجل تجربة قديم في الجذر؛ ليس من مسار التشغيل'
  if name=='__file_list.csv':return 'old-inventory','أرشفة مرشحة','فهرس قديم؛ التقرير الحالي يوفر فهرسًا أحدث'
  return 'project-entry','احتفاظ','مدخل تشغيل أو وصف المشروع أو إعداد استبعاد الملفات'
 return 'unclassified','مراجعة','لم يُحسم دور الملف من مساره أو مراجع البناء؛ لا يحذف تلقائيًا'
counts=collections.defaultdict(lambda:{'files':0,'bytes':0}); classified=[]
for f in rows:
 category,action,reason=classify(f['path']); group,count=dups.get(f['path'],('',1))
 x={**f,'category':category,'action':action,'reason':reason,'duplicate_group':group,'identical_paths':count};classified.append(x);counts[action]['files']+=1;counts[action]['bytes']+=int(f['bytes'])
with (out/'classified-files.csv').open('w',newline='',encoding='utf-8-sig') as s:
 w=csv.DictWriter(s,fieldnames=list(classified[0]));w.writeheader();w.writerows(classified)
with (out/'cleanup-candidates.csv').open('w',newline='',encoding='utf-8-sig') as s:
 w=csv.DictWriter(s,fieldnames=list(classified[0]));w.writeheader();w.writerows(x for x in classified if x['action'] not in ('احتفاظ','احتفاظ الآن'))
# Directory totals and a complete actual hierarchy.
nodes={}
for d in (out/'directories.txt').read_text().splitlines():nodes.setdefault(d,{'dirs':set(),'files':[],'bytes':0,'count':0})
for f in classified:
 p=Path(f['path']);parent=p.parent.as_posix();nodes[parent]['files'].append(f)
 for d in [p.parent,*p.parent.parents]:
  key=d.as_posix()
  if key in nodes:nodes[key]['bytes']+=int(f['bytes']);nodes[key]['count']+=1
for d in list(nodes):
 if d!='.':nodes[Path(d).parent.as_posix()]['dirs'].add(d)
def gib(n):return f'{n/1024**3:.3f} GiB'
full=['PS2redmption/'];compact=['PS2redmption/']
def emit(d,indent='',depth=0):
 n=nodes[d]
 for child in sorted(n['dirs'],key=str.lower):
  v=nodes[child];line=indent+'+-- '+Path(child).name+f'/ [{v["count"]:,} files; {gib(v["bytes"])}]';full.append(line)
  if depth<3:compact.append(line)
  emit(child,indent+'|   ',depth+1)
 for f in sorted(n['files'],key=lambda x:x['path'].lower()):
  line=indent+'+-- '+Path(f['path']).name+f' [{int(f["bytes"]):,} bytes; {f["category"]}]';full.append(line)
  if depth<2:compact.append(line)
emit('.')
(out/'PROJECT_TREE_FULL.txt').write_text('\n'.join(full)+'\n',encoding='utf-8')
(out/'PROJECT_TREE.txt').write_text('\n'.join(compact)+'\n',encoding='utf-8')
summary={'scope':'All inventory files classified by role/path and inspected build/launcher references; not a claim of line-by-line semantic verification. Git metadata not content hashed. Empty files and duplicates are not automatically useless.','decisions':dict(counts),'classified_files':len(classified),'duplicate_groups':len(dup['groups']),'duplicate_files':sum(len(g['files']) for g in dup['groups']),'duplicate_logical_excess_bytes':sum(g['bytes']*(len(g['files'])-1) for g in dup['groups']),'direct_cleanup_bytes':counts['تنظيف مباشر']['bytes'],'direct_cleanup_files':counts['تنظيف مباشر']['files'],'full_tree_lines':len(full),'compact_tree_lines':len(compact),'errors':inv['errors']+dup['errors'],'audit_deleted_files':0,'game_and_save_files_unchanged':True}
(out/'classification-summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
print(json.dumps(summary,ensure_ascii=True))
