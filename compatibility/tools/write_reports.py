"""Generate evidence-linked Arabic lab reports; never embed game contents."""
from pathlib import Path
import json,collections,sys,importlib.util,statistics,re
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'reports'
d=json.loads((ROOT/'artifacts/discovery/discovery.json').read_text())
e=json.loads((ROOT/'artifacts/discovery/extended.json').read_text())
def write(name,text): (out/name).write_text(text.strip()+'\n',encoding='utf-8')
def table(headers,rows):return '| '+' | '.join(headers)+' |\n|'+'|'.join(['---']*len(headers))+'|\n'+'\n'.join('| '+' | '.join(str(x) for x in row)+' |' for row in rows)
seg=d['elf']['segments'][0]
write('RE4_DISCOVERY.md',f'''# اكتشاف RE4 — 2026-10-24

تم فحص مجلد game المحدد فقط، دون البحث في الأقراص الأخرى ودون فتح ملفات حفظ المستخدم.
كشف SYSTEM.CNF ملف الإقلاع `{d['boot']}`. النسخة USA / NTSC / SLUS-211.34؛ VER 1.01 هو حقل boot configuration المطابق للملف المرجعي، وليس قياسًا منفصلًا لإصدار mastering. تطابق SHA يثبت هوية الملف التنفيذي نفسه.

SHA-256: `{d['elf']['sha256']}`. يطابق profile.toml الأصلي حرفيًا؛ لا حاجة إلى ملف تعريف لنسخة مختلفة.
ELF32 little endian، ET_EXEC=2، EM_MIPS=8، e_flags=`{d['elf']['flags']:#x}`، نقطة الدخول `{d['elf']['entry']:#010x}`.
معمارية R5900 تُستدل كذلك من إصدار PS2 ومسار الأدوات؛ EM_MIPS وحده لا يميز جميع معالجات MIPS.
عدد المقاطع {len(d['elf']['segments'])}، الأقسام {len(d['elf']['sections'])}، رموز SYMTAB/DYNSYM: {d['elf']['symbols']} (مجرد من الرموز).

PT_LOAD: offset `{seg['offset']:#x}`، vaddr/paddr `{seg['vaddr']:#x}`، filesz `{seg['filesz']:#x}`، memsz `{seg['memsz']:#x}`، flags={seg['flags']}، align={seg['align']}.
المدى المحمل `[{seg['vaddr']:#x}, {seg['vaddr']+seg['memsz']:#x})`. ذيل التصفير في PT_LOAD هو {seg['memsz']-seg['filesz']} بايت؛ يتضمن قسم `.bss` بحجم 879192 بايت وفجوة محاذاة 216 بايت قبله. هذا يفسر الفرق بين حجم القسم في analysis.layout وحجم memsz−filesz، وليس اختلافًا في مراجعة اللعبة.
يوجد 93 قسم overlay بالإضافة إلى .DVP.ovlytab و.DVP.ovlystrtab (95 اسمًا يبدأ .DVP)؛ التفاصيل الفعلية لجميع الأقسام في discovery.json. لا نساوي تلقائيًا بين DVP ووحدات EE الديناميكية.

صورة ISO9660 بحجم 4435836928 بايت؛ حقل اسم المجلد في الصورة فارغ. SHA-256 `{d['images'][0]['sha256']}`؛ خريطة LBA والحجوم في discovery.json. أُعيد حساب بصمات الملفات الثمانية داخل ISO ومقارنتها بالنسخة المستخرجة؛ كلها متطابقة (iso-file-verification.json).
فحص كامل بايتات الملفات المستخرجة عدا الحفظ وجد 24 موضع ELF صالحًا: الأساسي +16 في IOPRP +7 في MODULES.DAT.
كذلك وجدت 195 وحدة SNR2 في bio4dat.afs. أسماء بعض الوحدات داخلها تنتهي .elf لكن التوقيع SNR2 وليس ELF.

الأدلة: `artifacts/discovery/discovery.json`، `extended.json`، وفهارس AFS الثلاثة. تتضمن حجومًا وبصمات وإزاحات فقط.
حدود الفحص: البيانات المضغوطة/المشفرة ليست مفكوكة بالكامل؛ غياب توقيع معروف لا يثبت غياب كود أو مورد داخلها. لم تُستخرج الأصول بالجملة.
''')
rows=[]
for r in d['files']:rows.append((Path(r['file']).name,r['bytes'],len(r['elf']),len(r['snr2'])))
write('GAME_FILE_MAP.md','''# خريطة ملفات اللعبة

'''+table(['الملف','الحجم بالبايت','ELF مضمن','SNR2'],rows)+'''

العلاقات: SYSTEM.CNF → ELF الأساسي → IOPRP/خدمات SIF وFILEIO/CDVD → MODULES.DAT → فهرس AFS → وحدات الغرف والموارد والأفلام.
فهرس 0flist.dir حجمه 43 بايت؛ ليس أرشيفًا. ملفات AFS تُقرأ على دفعات، ولا ينبغي تحميلها كاملة في الذاكرة.

'''+table(['الحاوية','المدخلات','التواقيع المثبتة'],[(k,v['entries'],v['signature_counts']) for k,v in d['archives'].items()])+'''

كل صف في `*.afs.index.json` يربط الاسم والفهرس والإزاحة والحجم والتوقيع، وكل صف ISO يحدد LBA.
التمييز مهم: `.tpl` 564 و`.bin` 252 و`.snd` 358 و`.rel` 207 و`.esl` 32 و`.dat` 965 في أرشيف البيانات، وهي تصنيفات أسماء وليست تحققًا كاملًا من الصيغة.
ثبتت تواقيع 244 ملف CRI ADX عبر الحاويات الثلاث، و169 MPEG-PS بأسماء .sfd. لا تؤيد هذه العينة تعميم ملف التعريف القديم بأن الصوت OGG فقط أو الأفلام STR/ATR فقط.
ملفات .evd موجودة مع أفلام الغرف: r100s03.evd وr100s03.sfd في bio4mov.afs؛ الارتباط الوظيفي بأول مواجهة موثق في هندسة Project-4 السابقة، وليس من تشابه الاسم وحده.
الأنيميشن والهندسة والخامات داخل BIN/TPL/DAT تحتاج محللات الموارد الموجودة؛ لم ندّع تحقق بنية كل مورد من الامتداد.

ROMDIR و183 جدول import/export إجمالًا في IOPRP/MODULES موثقة بإزاحاتها في extended.json. هذه جداول اعتماد ثابتة، وليست ترتيب تحميل حيًا مثبتًا.
المكتبات تشمل SYSMEM/LOADCORE/SIFCMD/SIFMAN/THREADMAN/IOMAN/MODLOAD/FILEIO/CDVDMAN/CDVDFSV/LOADFILE؛ وأسماء الجداول الكاملة في البيانات الوصفية.
قراءة .iopmod ربطت الاعتمادات بكل IRX منفرد في iop-dependencies.json: وحدات MODULES السبع هي sio2man وpadman وSound_Device_Library وCapcom Sound Engine وCRI_ADX_Driver وmcman وmcserv؛ لا نستنتجها من الامتدادات.
''')
matrix=[
('R5900 / EE','Project-4: إصلاحات delay slot والاستدعاء المتناثر؛ Zmbor: فروع bit63 وMOVZ/MOVN وتوسيع اكتشاف المداخل','قارن الترجمة باختبارات العتاد قبل إعادة توليد أي كود'),
('MMI','Project-4: تصحيحات permutation من جولات اللعب؛ Zmbor: متجهات ضرب وتجميع/قسمة من PS2','مرشح نقل المتجهات والاختبارات، لا استبدال المترجم'),
('FPU','Zmbor: RZ وFCR31 وتشبع ومقارنات encoding؛ Project-4: مسارات EE مستقلة','اختبار نتائج hardware على المترجمين قبل الدمج'),
('VU0 / VU1','Project-4: كتل RE4 متخصصة وإعادة أوامر Continue؛ Zmbor: EFU ومتجهات hardware','حفظ الكتل المتخصصة؛ نقل FLG3 فقط في XGKICK، لا تغيير FMAC/flags'),
('VIF','Project-4: UNPACK سريع مثبت في اللعبة؛ Zmbor: تجزئة الأوامر وI-bit stalls','نقل IMAGE2 ضيق؛ stalls مرشحة لاحقة بأثر محدد'),
('GIF / GS','Project-4: FIFO لكل مسار، parallel-gs، traces؛ Zmbor: IMAGE2 بخمسة مواقع','دمج شروط IMAGE2 دون استبدال FIFO أو backend'),
('DMAC / SPR','المشروعان يصلحان حد 4096؛ Zmbor لديه SPR/interleave/chain hardware coverage','تجنب تكرار الإصلاح؛ مطابقة MADR/SADR وD_STAT أولًا'),
('IOP / SIF','Project-4: IOP فعلي وSNR2 وقراءة قرص وصوت؛ Zmbor: responder مناسب للاختبارات','الإبقاء على IOP الحقيقي للعبة؛ لا استبداله بمستجيب اصطناعي'),
('IPU','Project-4: فك SFD/FFmpeg وIPU مع أدوات probes','إبقاء التنفيذ القائم؛ قياس حقول IPU في الجولة'),
('SPU2','Project-4: native SPU2 وكود صوت مدمج واختبارات الجسر','عدم استبدال الصوت؛ underruns ليست جودة سمعية مثبتة'),
('Streaming','Project-4: AFS وCDVD host read؛ Zmbor: اختبارات ISO/مسارات','القراءة من الملفات الأصلية، مع ELF وحفظ محليين'),
('Controllers','Project-4: native SIO2 وإعادة إدخال ومسار feedback','فصل دليل replay عن اختبار يد تحكم حقيقية'),
('Memory cards','Project-4: migration وحفظ raw/file؛ Zmbor: عزل mc0','بطاقات اختبار من fixture خاص فقط؛ لا ملف حفظ مستخدم'),
('Timing / scheduling','Project-4: مؤقتات EE/IOP وعينات monotonic؛ Zmbor: kernel tests','ثبات المشهد/الإدخال؛ لا استنتاج سرعة من بقاء العملية')]
write('ENGINE_COMPARISON.md','''# مقارنة المحركين الفعليين

Zmbor: upstream eb8688b، فرع التطوير ae1c119، وفرع integration 00173a2. تحقق ذلك بقراءة Git worktree list والسجل.
Project-4/core: c5a9d02573410a2085a4b4b831b0b68ba3515440 مع تغييرات محلية كثيرة غير ملتزم بها؛ نُقلت حالتها الحالية إلى نسخة مستقلة مع حفظ التاريخ الأصلي.
الفروع المعزولة: compat/re4-zmbor-20261024 وcompat/re4-reference.

'''+table(['المكوّن','الدليل/الاختلاف','قرار التكامل'],matrix)+f'''

المقارنة المباشرة للمصادر: {e['source_comparison_counts']}؛ التفاصيل لكل ملف في artifacts/source-comparison.json.
الأرقام لا تعني تكافؤًا وظيفيًا؛ ملفات كثيرة تطورت بطرق مختلفة.

الهندسة الموجودة: core/out/build هو Release/clang-cl/Ninja مع FFmpeg وparallel-gs وnative SPU2؛ يوجد أيضًا build-pgs/build2/build-with-runtime-libraries.
recomp/generated يحوي كود EE، وrecomp/native/SLUS_211.34/full_build يحوي وحدات SNR2 الكاملة؛ لم نعد توليدها ولم نعدل ملفاتها.
الأدوات المنقولة تشمل فحص ELF/SNR2 والـrelocations وVU replay وhost sampling وspeed/audio/input/save reports وGhidra scripts.
Ghidra 12.1.4 ومكوّن EE وGhidraMCP موجودة ضمن dependencies؛ وجود الأدوات ليس إثبات أن كل وحدة حللت في قاعدة Ghidra.
آخر حالة هندسية مقروءة: PS2_PROJECT_STATE.md المؤرخ 2026-10-19 وأول مواجهة، وHANDOFF.md الخاص بـ Zmbor المؤرخ 2026-10-24.
الجرد الموسع في artifacts/engineering-inventory.json يسجل 530 عنصرًا هندسيًا مختارًا من 187037 مدخلًا، مع استبعاد الحفظ وBIOS ومحتويات البناء والكود المولد. توجد ستة مؤشرات مشاريع Ghidra، منها artifacts/ghidra/re4.gpr وartifacts/ghidra_iop/adxdrv.gpr. وجود مؤشر المشروع لا يثبت تغطية تحليله.
''')
write('INTEGRATION_PLAN.md','''# خطة التنفيذ والتكامل

1. تحقق الهوية والفهارس: نُفذ، ELF مطابق للملف المرجعي. بيانات الحفظ مستبعدة من اكتشاف اللعبة.
2. اعزل المصادر مع تاريخ Git وحالتها المحلية الحالية: نُفذ. لا push ولا تغيير للمستودعات الأصلية.
3. أعد تشغيل مشغّل Project-4 المتقدم بحفظ اختبار مستقل: نُفذ؛ تأكد الوصول المرئي إلى الغابة، دون تعميم قبول الحملة.
4. انقل تصحيح Zmbor/upstream e563698 (IMAGE2) فقط: خمسة شروط في GS/GIF/VIF/XGKICK/packet-close. لا تغيير headers ولا مولدات RE4.
5. اختبار تراجع قبل/بعد: فشل شرط arbitration القديم مثبت باختبار WILL_FAIL؛ النسخة المصححة وVRAM واختبارات cache ناجحة. نتائج الوحدة واللعب تُحدَّث في RE4_COMPATIBILITY.
6. إعادة ربط معزولة: إعادة استخدام 8605 كائنات مشغّل موجودة للقراءة فقط مع كائنات runtime المعدلة قبل المكتبة؛ كل المخرجات وLTO/PDB داخل lab/native-link.
7. مقارنة الجولة بنفس ELF/fixture/replay/settings، ثم إعادة أوامر VU1 المسجلة. لا يُقبل تغيير رياضي بسبب رقم سرعة فقط.
8. بعد اكتمال بوابة العتاد واللعب: أولوية بحث VU1 من traces الموجودة؛ ثم SPR/VIF/FPU من Zmbor بشرط متجهات مستقلة لكل تصحيح.

تحليل مضاد للتصحيح: معنى IMAGE2 ثابت في توثيق GIFtag المحلي وبكود Zmbor؛ تغيير predicate فقط يحافظ على FIFO الخاص بـ Project-4. الخطر هو اختلاف تغطية المسارات وإعادة الربط؛ لذلك نختبر VRAM واللعب ولا نعتبر compilation قبولًا.
لا يوجد دليل أن RE4 يستعمل FLG3 في المشهد المقاس، لذا هو إصلاح صحة عام ولا يبرر نسبة تحسن FPS.
لا تنقل FPU/VU wholesale: الكتل المتخصصة وأعلام FMAC والتوقيت بحاجة إلى replay متطابق.

الحواجز تُحدّث في أقسام التحقق اللاحقة: لا تُستبدل أدلة اللعب الناقصة بعبارة «العملية حية». تبقى بوابة hardware كاملة للمرشح منفصلة عن نتائج Zmbor المرجعية.
''')
spec=importlib.util.spec_from_file_location('speed',ROOT/'reference-tools/tools/diagnostics/game_speed_report.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
results=[]
for run in sorted((ROOT/'artifacts/runs').glob('*')):
    if not (run/'report.json').exists():continue
    report=json.loads((run/'report.json').read_text());speed=mod.summarize(run)
    (run/'speed.json').write_text(json.dumps(speed,indent=2))
    states=[json.loads(line) for line in (run/'diagnostics/state.jsonl').read_text().splitlines()]
    errors=[]
    for name in ('stdout.txt','stderr.txt'):
        text=(run/name).read_text(errors='replace')
        errors += [line[:240] for line in text.splitlines() if re.search(r'guest-branch:missing-target|runtime exception|access violation|\[terminate\]|VK_ERROR',line,re.I)]
    results.append(dict(name=run.name,report=report,speed=speed,last_ee=states[-1]['ee_vsync_tick'],faults=errors))
(ROOT/'artifacts/run-summary.json').write_text(json.dumps(results,indent=2))
write('PERFORMANCE_BASELINE.md','''# خط أساس الأداء

'''+table(['الجولة','ثوانٍ','آخر EE tick','سرعة EE المقاسة ×','ذروة RSS بايت','الحفظ الخاص ثابت'],[(r['name'],round(r['report']['seconds'],3),r['last_ee'],round(r['speed']['overall']['wall_speed'],5),r['report']['peak_rss_bytes'],r['report']['test_saves_unchanged']) for r in results])+'''

المقياس من elapsed_seconds monotonic وEE vsync عند 60000/1001Hz عبر أداة Project-4 game_speed_report. متوسط الجولة يمزج الشاشات/الأفلام/القائمة/الغابة؛ ليس FPS الغابة وحدها ولا مقارنة زمن التنفيذ CPU.
host_present_tick يصف حلقة التقديم، وليس وحده عدد صور لعبة فريدة؛ display_flips القديم قد يبقى صفرًا مع backend الحالي.
state.jsonl يحفظ DMA/GIF/VIF/IPU وحقول timing وGS؛ السجلات تحفظ إحصاءات الصوت. لم نقس زمن كل تعليمة EE أو تكلفة GPU sync مستقلة أو تأخر يد التحكم الفعلية.
الأدلة التاريخية السابقة: VU1::run بلغ ~80% inclusive في v30 و~69% في v39، وكلفة FMAC/commit بارزة؛ قياسات تاريخية وليست قياسًا جديدًا هنا. كسب IOP السابق ~17.37% كلفة/تعليمة في حمل معزول، لا FPS لعبة.
تصحيح IMAGE2 لا يغير المسار الشائع للحزم الأخرى، ولا توجد نسبة تسريع لعبة مقبولة منه. يلزم مشهد وحفظ وإدخال متطابق وأزواج متناوبة بعد إغلاق الاختبارات/البناء.
''')
write('RE4_COMPATIBILITY.md','''# حالة التوافق الفعلية

الهوية مثبتة ومتطابقة مع SLUS-211.34. جولات الأساس وصلت إلى الغابة مع Leon والسلاح وHUD، ثم أضاف الاختبار اليدوي والتحميل المستقل الأدلة المفصلة أدناه. استُخدمت بطاقات مختبر خاصة؛ هذه النتائج لا تمنح قبولًا للحملة كاملة.

'''+table(['الجولة','آخر EE','أعطال واضحة من السجل','المهلة مقصودة','حفظ الاختبار ثابت'],[(r['name'],r['last_ee'],len(r['faults']),r['report']['terminated_at_planned_timeout'],r['report']['test_saves_unchanged']) for r in results])+'''

أعلى مرحلة مثبتة بالصور لهذه الدفعة: الغابة (6). إثبات الحركة والتصويب وإطلاق النار موجود في تاريخ Project-4 السابق؛ لا يعامل كإعادة تحقق جديدة ما لم نرفق صور الجولة الجديدة.
Hunnigan وتسلسل New Game الكامل غير موثقين منفصلين هنا. انتقال الغرف/تفاعل عدو/حفظ وتحميل حملة: غير مثبت. لا تعني هذه الحدود أن كل مرحلة فشلت؛ بعضها لم يختبر بعد.
تقرير العملية يسجل terminated_at_planned_timeout لتمييز قتلها المقصود عن crash؛ exit=1 بعد terminate ليس انهيارًا تلقائيًا.

اختبارات الإصلاح المعزولة: 48/48 (45 cache + arbitration قبل/بعد + مطابقة IMAGE2 VRAM).
المشغل الأصلي Project-4: 629/629 في النسخة المعزولة، واختبارات IOP الخمسة ناجحة.
Zmbor integration: المحاولة الأولى 519/520 وفشل مسار فيلم، ثم نجحت 520/520 عند رفع قيد sandbox فقط، دون تعديل الكود؛ واختبارات IOP الأربعة ناجحة.
Python: اكتملت إعادة 403 اختبارات دون أخطاء مع 7 skipped. المحاولات الأولى تكشف نقص ملفات الدعم/tmp وقيود الروابط وresolve؛ حُفظت ولم تُخفَ. السجل الكامل artifacts/checks/project4-python-complete.log.
أعدنا فعليًا مصفوفة العتاد الموجودة لـ Zmbor pre-integration: 47/55 PASS و8 MISMATCH، دون CRASH/TIMEOUT؛ واختبارا e2e في integration نجحا، بما فيه فحص كل بكسلات إطار GS. هذه ليست بوابة hardware كاملة لـ Project-4 المرشح.
اختبارات IMAGE2 النهائية: قبل التصحيح 629/633 (أربعة إخفاقات متوقعة)، وبعده 633/633؛ GS VRAM وVIF continuation وXGKICK وpacket-close تختبر أربعة مسارات، ويغطي اختبار arbitration المستقل المسار الخامس. محاولة أولى بمكدس 1MiB توقفت C00000FD في النسختين؛ أعيدت قيمة /STACK:8388608 الأصلية واكتمل الاختبار. السجلات النهائية candidate-before-final.log وcandidate-after-final.log محفوظة.
VU1 replay قبل/بعد: 964 أمرًا و128 تسلسلًا و836 Continue، والحالة a7a8b884d6fdb986 والدورات 2077288 وحزم GIF 1385 متطابقة؛ ليس قياس سرعة لأن الربط كان قائمًا.

الخصوصية والعزل: لا حفظ مستخدم فُتح أو نُقل في أدوات المختبر. الملفات التجريبية والـELF محلية؛ data junction يصل فقط إلى بيانات القرص وتستخدمه CDVD read-only. لم ينشر أي أصل أو executable أو كود مشتق من اللعبة.
توجد محاولة تجهيز baseline غير مشغلة فشلت عند إنشاء junction تحت sandbox؛ نُفذت التجربة المكتملة باسم baseline-01 بعد السماح بالأداة. الملفات غير مكتملة محفوظة دون مسح.
''')
print('Generated six Arabic evidence reports')
play=ROOT/'artifacts/runs/candidate-play'
if (play/'gameplay-evidence.json').exists():
    path=out/'RE4_COMPATIBILITY.md'
    text=path.read_text(encoding='utf-8').replace('أعلى مرحلة مثبتة بالصور لهذه الدفعة: الغابة (6). إثبات الحركة والتصويب وإطلاق النار موجود في تاريخ Project-4 السابق؛ لا يعامل كإعادة تحقق جديدة ما لم نرفق صور الجولة الجديدة.',
        'أعلى مرحلة مثبتة في الجولة المصححة الطويلة: التصويب وإطلاق النار (8)، مع الحركة والوصول إلى باب البيت. هذا لا يعني إثبات جميع المراحل السابقة بالتسلسل؛ Hunnigan وNew Game من بطاقة فارغة غير مثبتين منفصلين.')
    text+='''\n## أدلة اللعب الطويل الفعلية\n
انتهت candidate-play بعد600.282ثانية بالمهلة المقصودة، دون عطل واضح من السجل، وبحفظ اختبار ثابت. frame-23700 يظهر طلقة ومضة/ظرف وذخيرة08؛ frame-24000 يثبت07؛ frame-25500 يثبت06 مع الحركة، وframe-30900 أمام باب البيت.
دفعة120قراءة RAM مكتملة ثم10قراءات نهائية تطابق بصمة المشغل وثلاث تواقيع ELF ومؤشر اللاعب الثابت0x1789f40. فرق موضع بين دفعتين16987.48 وحدة ضيف، ومطابقة ترجمة المصفوفة0. لا يثبت ذلك مسار تصادم كاملًا.
مراقب انتظر8400على صيغة pad trace غير المفعلة وانتهت مهلته؛ لا دفعة ناجحة منه. استخدمت دفعة نهائية مستقلة بدل الادعاء بوجود عينات من تلك النافذة، ثم أصلحت دعم native replay بثلاثة اختبارات تراجع.
المرحلتان9و10والحفظ/التحميل غير مثبتة في هذه الجولة: شريطv5ينتهي بالمشي عند9000 ولا يضغط فعل الباب. هذه فجوة تغطية مدخلات، وليست تشخيص فشل لمحرك الغرف أوAI.
'''
    path.write_text(text,encoding='utf-8')

    path=out/'PERFORMANCE_BASELINE.md'
    path.write_text(path.read_text(encoding='utf-8')+'''\n## عينة لعب جديدة ومقارنة نافذة ثابتة\n
أداة Project-4 hot_thread_sampler التقطت2601عينة على GameThread خلال15ثانية ضمن نافذة EE5659..5805 (metadata الخارجي258.281..279.041ثانية). VU1::run81.05% inclusive، normalizeFmacResult9.46% self، commitReadyPipelines8.04% self، updateFmacFlags3.38% self. النسب الشاملة متداخلة ولا تجمع.
EE4600..4900بنفس ELF/حفظ الاختبار/شريط الإدخال وإعداداته:0.136708× قبل IMAGE2 و0.138784× بعده. حدود العينات متداخلة؛ فرق1.52%ليس مكسبًا مثبتًا. controlled-comparison.json يحفظ الحدود والصوت والعدادات.
الجولة الطويلة تعرضت لعينة profiling وقراءات RAM؛ هي دليل تقدم وتشخيص، وليست مقارنة سرعة مضبوطة. GS history الاختياري فارغ؛ لا يوجد census جديد يثبت استعمال FLG3 في هذا المشهد.

| المقياس | الدليل الحالي وحدوده |
|---|---|
| سرعة الضيف | monotonic + EE counters، مع نافذة ثابتة منفصلة عن متوسط الإقلاع |
| Frame pacing | لقطات كل300host tick؛ لا trace لكل frame، فلا ادعاء p99 pacing |
| كلفة EE | عينة خيط وتوزيع استدعاءات؛ لا ns لكل تعليمة EE |
| VU1 وFMAC/flags | عينة فعلية أعلاه + replay964أمرًا؛ الفروع والتوقيت محفوظة في المقارنة |
| VIF/GIF/DMA | عدادات وstacks؛ inclusive VIF يتضمن VU، وليس overhead مستقلًا |
| GPU sync | ظهور انتظار GPU في العينة؛ لا فصل زمني كامل للـGPU |
| IOP scheduling | اختبارات IOP والنتائج التاريخية؛ لا قياس overhead جديد مستقل |
| الصوت | requested/delivered/underrun/tempo/peak في stderr؛ لا قبول سمعي كامل أوAV sync |
| التحكم | replay وذاكرة اللاعب والصور؛ لا قياس تأخر يد تحكم فعلية |
| الذاكرة | peak RSS لكل جولة؛ لا attribution كامل للـallocations |
''',encoding='utf-8')
fusion=ROOT/'artifacts/experiments/vu-fusion/evaluation.json'
if fusion.exists():
    result=json.loads(fusion.read_text())
    path=out/'PERFORMANCE_BASELINE.md'
    path.write_text(path.read_text(encoding='utf-8')+f'''\n## مرشح VU موجود أُعيد تقييمه\n
اكتُشف في نسخة Claude الخاصة بالمشروع الأصلي، وليس تحسينًا أُعيد اختراعه. سبع مقارنات متناوبة×25إعادة على964أمرًا: وسيط كلفة {result['baseline_median_ns_per_cycle']}→{result['candidate_median_ns_per_cycle']}ns/cycle، انخفاض كلفة مقترن {result['median_cost_reduction_percent']:.3f}% (المدى {min(result['paired_cost_reduction_percent']):.3f}..{max(result['paired_cost_reduction_percent']):.3f}%). الحالة والدورات وحزم GIF مطابقة في كل جولة. هذا حمل معزول على ثنائيات المرشح الموجودة، وليس زيادة FPS للنسخة المدمجة.
التحسين يدمج فحوص scoreboard داخل كتل معروفة، مع fallback عند الأخطار والميزانيات والاستئناف؛ لا يعيد كتابة الحساب الرياضي. توليده أعيد حرفيًا93485b3fمع87كتلة؛ الاختبار التاريخي160ميزانية/64استئنافًا دون اختلافات روجع، ولم يعد كاملًا حتى الآن. الدمج المعزول قيد التحقق، مع إبقاء IMAGE2 والقدرة على تعطيله عبرPS2X_VU1_FUSED=0.
''',encoding='utf-8')
    plan=out/'INTEGRATION_PLAN.md'
    plan.write_text(plan.read_text(encoding='utf-8')+'''\n## دمج VU الجاري ومراجعته\n
أعيد استخدام مرشح موجود من نسخة Claude على فرع compat/re4-vu-fusion، مع إبقاء ثنائي IMAGE2 السابق محفوظًا. لا headers ولا حسابات FMAC تغيرت. فُصل جسم إصدار التعليمات وذيله إلى include مشترك يستخدمه المرجع والمسار السريع؛ جدول اللعبة المولد بقي خاصًا ولم يُضمّن في رقعة التقرير.
المرشح يوسع التخصص من17إلى87كتلة ويجمع فحوص scoreboard. رقم26.5%يقارن الحزمة المرشحة كاملة بالأصل؛ لا يعزل وحده أثر الدمج عن توسيع المناطق.
راجعت خطة الجاهزية: الحدود تقطع قبلE/D/T/reserved وقبل خطر latency، وتضم الفرع مع delay slot فقط؛ FDIV/EFU/WAITQ/WAITP/XGKICK تبقى فحوصًا ديناميكية. الدخل غير المعروف يُفحص في الأزواج الأولى، وتُكتب مواعيد الجاهزية المستقبلية قبل كل رجوع للمسار الدقيق. موارد commit وXGKICK لا تتوقف عن التقدم.
الـgenerator يرفض latencyتتجاوز الحد4لنتائج scoreboard، ويبدأ دون حقائق مستوردة حتىVF0. المسار السريع يعود للقديم عند نهاية ميزانية/فرع معلّق/حالة توقف؛ PS2X_VU1_FUSED=0يبقي الكتل النظيفة وحدها.
أعيدت633حالة C++ مع تفعيل وتعطيل التحسين، و964أمرًا، و13ميزانية×64استئنافًا بثلاثة أوضاع: الأصل، fusion-off، fusion-on. كلها متطابقة للحالة والدورات؛ الاختبارات التاريخية160ميزانية باقية كدليل منفصل. اكتمل بناء المشغّل وتشغيله فعليًا؛ نتائج اللعب والقياس مضافة أدناه.
الرقعة العامة VU_FUSION_RUNTIME.patch لا تحتوي الجدول المشتق من اللعبة؛ مولد الأدوات محفوظ في tools/vu1_fusion_codegen.py. البصمة المدخلة/المخرجة ومصدرالمناطق محفوظة في reproduction.json.
''',encoding='utf-8')

comparison=ROOT/'artifacts/comparison-house-baseline-fusion-play.json'
if comparison.exists():
    paired=json.loads(comparison.read_text())
    path=out/'PERFORMANCE_BASELINE.md'
    text=path.read_text(encoding='utf-8').replace('الدمج المعزول قيد التحقق','اكتمل تحقق الدمج المعزول')
    text+='''\n## المشغّل المدمج والنافذة المطابقة قرب المنزل\n
بُني المشغّل المدمج SHA256: 8eee239948f9e76b65e1331f52729fa2ab78fbd4a731837424a138606749b0c9. جولة fusion-01 لمدة180.531ثانية وصلتEE4987؛ fusion-play لمدة600.594ثانية وصلتEE12110. ملفات حفظ المختبر ثابتة. عينة متأخرة أظهرت تنفيذ المسار المدمج للبرنامج770ea85198e8e87f، وليست مجرد وجوده في الملف التنفيذي.
EE4600..4900 في الغابة الخاملة:0.138784× لتصحيحIMAGE2 مقابل0.138794× للدمج؛ لا تحسن مقاس عمليًا.
مقارنة house-baseline وfusion-play لها شريط إدخال كامل متطابق وحفظ وELF وإعدادات متطابقة. عندEE9800..10400:0.290927× مقابل0.348814×؛ تقدير فرق السرعة+19.897%. حدود العينات متداخلة (0.276695..0.387399 مقابل0.312910..0.610664)، وزوج واحد لا يثبت مكسب لعب. انتهت أدواتprofiling المبكرة قبل النافذة وبدأ مسح الذاكرة المتأخر بعدها. يلزم تكرار متناوب بنقاط قياس أكثر كثافة قبل اعتماد نسبة الأداء.
جولة المستخدم اليدوية تستخدم تسجيل الأزرار وقراءات RAM؛ ليست benchmark مضبوطًا.
'''
    path.write_text(text,encoding='utf-8')

manual=ROOT/'artifacts/runs/manual-play-01/post-session-observation.json'
if manual.exists():
    path=out/'RE4_COMPATIBILITY.md'
    text=path.read_text(encoding='utf-8')
    text+='''\n## تحقق المستخدم اليدوي اللاحق — أعلى مرحلة مثبتة10\n
هذه إضافة لاحقة إلى قيود الجولات الآلية أعلاه. المستخدم تحكم وحده دون replay أو أوامر تنقل آلية. المشغّل المدمج نفسه وصل إلى الغابة والتحكم والتصويب وإطلاق النار ثم مشهد دخول المنزل والمواجهة واتصالHunnigan.
أدلة محلية في artifacts/runs/manual-play-01/diagnostics: frame-9300 مشهد الرجل قرب المدفأة؛ frame-11400 العدو يرفع الفأس أمام التصويب والذخيرة08؛ frame-13200 تفاعل العدو والذخيرة03؛ frame-14400 مشهد ما بعد المواجهة؛ frame-15300 وframe-16200 اتصالHunnigan. أعلى مرحلة مرقمة مثبتة هي10، ولا يعني ذلك قبول انتقال غرفة مستقلة9 أو الحفظ/التحميل11.
دفعة قراءة فقط120عينة موضع/غرفة مكتملة، مع مطابقة المشغّل وELF وثلاثة تواقيع RAM. آخرcaptureEE8681 عند280.967ثانية. لا يوجد report خروج مكتمل، والأداة المالكة لم تعد متاحة عند الاستئناف؛ سبب الانتهاء غير معلوم، ولا يصنفcrash بلا دليل. فحص لاحق أكد بقاء جميع ملفات حفظ المختبر مطابقة لبصماتها السابقة.
إعادة المراقبة بدأت باسمmanual-play-02، من القائمة دون إعادة تشغيل مدخلات آلية؛ لا نضيف تقدمًا منها قبل مراجعته.
'''
    path.write_text(text,encoding='utf-8')

save_evidence=ROOT/'artifacts/runs/manual-play-02/save-success-evidence.json'
if save_evidence.exists():
    path=out/'RE4_COMPATIBILITY.md'
    with path.open('a',encoding='utf-8') as f:
        f.write('''\n## جلسة المستخدم الثانية والحفظ الفعلي\n
المراقبة البصرية أثبتت مواجهة المنزل مجددًا، صعود الدرج، القفز من النافذة، ووجود عدة أعداء خارج المنزل وإصابة أحدهم بطلقة مع الدم والظرف الظاهر (frame-22800). لم يرسل المراقب أي مدخلات أثناء اللعب.
frame-26700 يعرض خانات الحفظ؛ frame-27600 يعرض Save Successful للخانة01، الفصل1-1، Typewriter، Saves001. بطاقة الاختبار الخاصة تغيرت من8207bfea… إلىae9c30f7…، وحُفظ checkpoint محلي8650752بايت مع تطابق بصمة المصدر قبل النسخ وبعده وبصمة النسخة. لا يُعد تغير البطاقة عطبًا هنا؛ هذه كتابة حفظ مقصودة من المستخدم داخل المختبر.
frame-28200 يعرض التقاطHandgun Ammo(10)، ثمframe-29100 العودة للتحكم. الحفظ مثبت؛ التحميل ما زال غير مثبت، ولذلك المرحلة11 مثبتة جزئيًا فقط. بيانات هذه الجلسة مستمرة حتى تقرير خروجها، ولا تُختلق مهلة أو نتيجة خروج للجلسة الأولى.
''')

load_evidence=ROOT/'artifacts/runs/saved-load-03/load-success-evidence.json'
if load_evidence.exists():
    path=out/'RE4_COMPATIBILITY.md'
    text=path.read_text(encoding='utf-8')
    text=text.replace('الحفظ مثبت؛ التحميل ما زال غير مثبت، ولذلك المرحلة11 مثبتة جزئيًا فقط. بيانات هذه الجلسة مستمرة حتى تقرير خروجها، ولا تُختلق مهلة أو نتيجة خروج للجلسة الأولى.',
        'الحفظ والتحميل مثبتان الآن بدليل التشغيل المستقل أدناه. انتهت الجلسة اليدوية الثانية بخروج0بعد670.188ثانية؛ لا تُختلق نتيجة خروج للجلسة الأولى.')
    text+='''\n## التحميل المستقل — المرحلة11 مثبتة\n
saved-load-03 يستخدم نسخة مستقلة من بطاقة المختبر التي حفظها المستخدم، بنفس بصمةae9c30f7… . frame-2700 يعرض Load Successful؛ frame-3300 يعرض عودةLeonإلى الآلة الكاتبة مع ذخيرة05، وهي نقطة الحفظ المسجلة. بقيت نسخة البطاقة مطابقة بعد التحميل؛ أُنهيت التجربة عمدًا بعد83.125ثانية إثر تحقق الصورة، وليستcrash.
المحاولتان saved-load-01 و02 محفوظتان: الأولى اختارتOptions لأنLoadكان محددًا أصلًا؛ الثانية أكدتNo الافتراضي. صححنا شريط الأزرار، ولم نغير محرك الحفظ لتجاوز المشكلة.
أعلى مرحلة مرقمة مثبتة11(الحفظ ثم التحميل)، مع القتال وHunnigan. انتقال غرفة مستقلة9ما زال غير موثق. هذا لا يمنح شهادة لاكتمال الحملة أو سلامة كل المشاهد.
'''
    path.write_text(text,encoding='utf-8')

shared_proof=ROOT/'artifacts/experiments/vu-shared-regions/proof.json'
if shared_proof.exists():
    path=out/'INTEGRATION_PLAN.md'
    with path.open('a',encoding='utf-8') as f:
        f.write('''\n## توسعة تغطية المناطق المتطابقة\n
الفرع المعزولcompat/re4-vu-shared-regionsيعيد استخدام87جسمًا موجودًا لثلاث صور مطابقة في المناطق نفسها:261كتلة مغطاة، دون نسخ أجسام الحساب أو تغييرالتوقيت. المقارنة تشمل هويةPالكاملة (تعليمات وflagsوجدولة)، لاكلمات التعليمة وحدها. كل مدخل خارج المناطق يبقى في جدول صورته الأصلي. أدوات المولد تحوي خمسة اختبارات رفض لاختلاف زوج واحد أو الأعلام أو تطابق جزئي أو إزاحة أو حدود غير سليمة.
دليلproof.jsonيؤكد إعادة توليد المرشح القديم حرفيًا93485b3fقبل التغيير؛ المرشح الجديدf6407aaa. جداول اللعبة خاصة ومستبعدة من النشر. صور فعلية16لكل من53c46ebcaf7db574وddf26db52fc7c957أعيد استخدامها من البحث الموجود، بدل توليد مدخلات بديلة.
validation-v2:633/633معfusion0و1، و13ميزانية×64استئنافًا×3أوضاع لكل صورة. الحالة والدورات وعددGIFوبصمته متطابقة؛ ظهر2340دخولًا إلى الكتل لكل صورة في اختبار65536، فتغطية المسار فعلية. إعادة964أمرًا قديمًا متطابقة، لكنها تغطي770فقط ولا تستبدل اختبار الصورتين.
البناء الجديدlab/shared-link؛ المشغل المستقرlab/fusion-linkمحفوظ. قبول الأداء يتطلب قياسًا بعد انتهاء الربط، ثم زوجين متناوبين لنفس مشهد الحفظ وبطاقة وإدخال وإعدادات متماثلة. لم يقبل تحسين لعب من هذه التوسعة حتى اكتمال تلك الأدلة.
''')

shared_timing=ROOT/'artifacts/experiments/vu-shared-regions/timing/summary.json'
if shared_timing.exists():
    measured=json.loads(shared_timing.read_text())
    path=out/'PERFORMANCE_BASELINE.md'
    with path.open('a',encoding='utf-8') as f:
        f.write('\n## كلفة توسعة التغطية — قياس معزول جديد\n\n')
        for result in measured['results']:
            changes=result['paired_cost_reduction_percent']
            f.write(f"الصورة{result['image']}: سبعة أزواج متناوبة×25إعادة، وسيط انخفاض الكلفة{result['median_reduction_percent']:.3f}%، والمدى{min(changes):.3f}..{max(changes):.3f}%.\n")
        f.write('الحالة والدورات وعددGIFوبصمته متطابقة. القياس يشمل كلفةGIFhash، وليس كلفة الحساب وحدها أوFPSاللعبة. أُجري بعد اكتمال الربط وخروج تجارب التحميل؛ المقارنة الفعلية لنفس مشهد الحفظ محفوظة منفصلة.\n')

manual_analysis=ROOT/'artifacts/runs/manual-play-02/manual-analysis.json'
if manual_analysis.exists():
    path=out/'PERFORMANCE_BASELINE.md'
    with path.open('a',encoding='utf-8') as f:
        f.write('''\n## التحكم والصوت في جلسة المستخدم\n
1985حالة تغير مطابقة بين نشر إدخال المضيف واستهلاكه فيnativePADمن1986سجل استهلاك. الوسيط13ms،p95=121ms،الأقصى240ms. هذه أزمنة برمجية للحالات المتغيرة وليست زمن الاستجابة من اليد الفعلية إلى الشاشة؛ لم يُقَس ذلك كطرفين كاملين.
آخر عدادات الصوت:requested31920000،delivered31376573،underrun543427. تراكم النقص لا يثبت جودةسمعية كاملة، ولا يمكن فصل أثره عن سرعة الضيف البطيئة من العداد وحده. ذروةRSSللجلسة1639817216بايت، والخروج0بعد670.188ثانية.
''')

scene_comparison=ROOT/'artifacts/experiments/vu-shared-regions/game-comparison-summary.json'
if scene_comparison.exists():
    measured=json.loads(scene_comparison.read_text())
    path=out/'PERFORMANCE_BASELINE.md'
    with path.open('a',encoding='utf-8') as f:
        f.write('\n## تحسن لعب متكرر في مشهد الحفظ نفسه\n\n')
        for pair in measured['pairs']:
            f.write(f"الزوج{pair['pair']}: {pair['base_speed']:.6f}×→{pair['shared_speed']:.6f}×، زيادةسرعة{pair['speed_increase_percent']:.3f}%. حدود عدم يقين أخذ العينات لنسبة الزيادة{pair['sampling_uncertainty_percent_bounds'][0]:.3f}..{pair['sampling_uncertainty_percent_bounds'][1]:.3f}%؛ ليستconfidence intervalإحصائية.\n")
        f.write(f"الوسيط{measured['median_speed_increase_percent']:.3f}%، من{measured['median_base_speed']:.6f}×إلى{measured['median_shared_speed']:.6f}×. الترتيبbase/sharedثمshared/base، النافذةEE3300..3900، وcaptureكل60hosttick. البطاقة والشريط وELFوالإعدادات وجميعDLLمتطابقة؛ لاprofilingأوقارئRAMأثناء القياس. انتهت الجولات الأربع بالمهلة المقصودة، دون خطأواضحوبحفظ ثابت.\n")
        f.write('هذه نتيجة مشهد ساكن واحد قرب الآلة الكاتبة؛ ليست زيادةFPSعامة ولا تشغيلًا بالزمن الحقيقي. ما زالت السرعة نحو0.215×. قياسك اليدوي السابق والاختبارات المعزولة أدلة منفصلة.\n')
    path=out/'INTEGRATION_PLAN.md'
    text=path.read_text(encoding='utf-8').replace('لم يقبل تحسين لعب من هذه التوسعة حتى اكتمال تلك الأدلة.',
        'اكتمل زوجان متناوبان؛ زيادة السرعة في مشهد الحفظ نحو48.8% بحدود أخذ عينات غير متداخلة. القبول خاص بهذا المشهد، ولا يعمم على بقية اللعب.')
    path.write_text(text,encoding='utf-8')
    path=out/'RE4_COMPATIBILITY.md'
    with path.open('a',encoding='utf-8') as f:
        f.write('''\n## المشغّل الجديد ومراجعة الرسوم\n
المشغلe17998c7099f3bff2892529d7726836d9689b9af1d6cd091bfa5b29c9a88542aحُمّل في أربع جولات مقارنة؛ ملفاتحفظالاختبار لم تتغير، ولا أخطاءواضحة. راجعت اللقطات قربEE3600: نفسLeonوالآلة الكاتبة والذخيرة05والعنصر علىالطاولة. لقطة عُرضت سوداء في أداة العرض أولًا؛ إعادة قراءةPNGأظهرتالصورة الصحيحة وبصمتها مطابقة تمامًا للقطة المرشح الأخرى. فحص433PNGمن اللعب لم يجد ملفًا أسودبالكامل. هذا ليس قبولًا بصريًا شاملًا لكل frameأومشهد.
Play_RE4_Lab.batيفتح جلسةيدويةمنالمرشح الجديد مع نسخة من آخر بطاقةمختبر لجلسةيدويةأغلقتبخروج0 وبصمةمطابقة. كل جلسة لها مجلد مستقل؛ مدةالاختبار القصوى ساعة، والحفظالأصلي لا يُقرأأويُكتب.
''')

navigation=ROOT/'artifacts/runs/regions-route/navigation-evidence.json'
if navigation.exists():
    path=out/'RE4_COMPATIBILITY.md'
    text=path.read_text(encoding='utf-8')
    lead='''الحالة الأخيرة: تم التحقق من القتال، واتصال Hunnigan بعد المنزل، والحفظ ثم التحميل في عملية مستقلة. أعلى مرحلة مرقمة مثبتة هي 11؛ انتقال غرفة مستقلة في المرحلة 9 ما زال غير مثبت. مرشح VU الجديد أسرع بنحو 48.8% في مشهد الحفظ المحدد، لكنه ما زال نحو 0.215× من الزمن الحقيقي. الاختبارات والقياسات المعزولة واللعب الفعلي مفصولة في هذا التقرير وتقرير الأداء.

'''
    text=text.replace('# حالة التوافق الفعلية\n\n','# حالة التوافق الفعلية\n\n'+lead,1)
    text+='''\n## اختبار الحركة اللاحق على المرشح الجديد\n
استمرت regions-route مدة 900.344 ثانية وانتهت بالمهلة المقصودة، مع بقاء بطاقة الاختبار مطابقة. نجح التحميل والحركة داخل الكوخ ثم الخروج منه والمشي على الطريق. سُجلت 82 قراءة موضع وغرفة للقراءة فقط؛ بقي معرّف المنطقة 0x100.
المسار الأول توقف عند جدار الكوخ بعد نقطتين. المسار الأدق، المأخوذ من مواضع المستخدم المتقاربة، اجتاز المدخل ووصل إلى 13 نقطة قبل حد الأوامر. الموصل التجريبي التالي توقف عند شجرة وسياج. هذا قيد في تغطية مسار التحكم، ولا يثبت خللًا في التصادم أو فشل تحميل وحدة غرفة. لم نغيّر إحداثيات اللاعب أو أعلام العدو أو حالة الحملة لتجاوز العوائق.
إعادة الاختبارات النهائية: 403 اختبار Python للمشروع دون أخطاء، مع 7 اختبارات متخطاة، و12 اختبارًا لأدوات المختبر ناجحة. السجلات final-project4-python.log وfinal-lab-python.log. لم تعد كل مشاهد القتال على المرشح الأخير؛ دليل القتال اليدوي يعود إلى النسخة المدمجة السابقة، بينما المرشح الأخير له تحقق VU مباشر وتحميل وحركة ومشهد مقارنة مطابق.
'''
    path.write_text(text,encoding='utf-8')
    path=out/'INTEGRATION_PLAN.md'
    with path.open('a',encoding='utf-8') as f:
        f.write('''\n## الحالة النهائية لهذه الدفعة وما بقي\n
اكتمل تصحيح IMAGE2 العام المأخوذ من Zmbor، مع الإبقاء على بنية Project-4 العاملة. أُعيد استخدام مرشح VU الموجود ثم وُسعت تغطيته بالمناطق المتطابقة، دون تغيير الحسابات أو استبدال المحرك. تحسن مشهد الحفظ تكرر في زوجين متناوبين، مع اختبارات حالة ودورات وحزم GIF ومراجعة صور مستقلة.
يبقى عبور حد غرفة مستقل غير موثق؛ محاولة التنقل وصلت إلى عوائق على المسار قبل بلوغ الحد، فلا توجد علة محرك مثبتة تستحق تعديل التصادم. يلزم تسجيل مسار كامل عبر البوابة أو اجتيازه يدويًا مع المراقبة.
الأولوية التالية للأداء هي قياس مشاهد الحركة والقتال الأخرى والصور غير المغطاة، ثم معالجة أكبر كلفة مثبتة. لا يُقبل تعميم 48.8% على الحملة، ولا نسبة الاختبار المعزول على FPS. ما زالت مشاكل underrun وجودة التزامن السمعي تحتاج قبولًا مستقلًا، ولم يُقَس تأخر الشاشة أو p99 لكل إطار أو كلفة GPU المستقلة.
اختبارات عتاد Zmbor المرجعية فيها 8 حالات عدم تطابق موجودة قبل هذه الدفعة؛ لم تُصلح ولم تُخفَ، ولم تُنسب إلى المرشح. لا توجد شهادة باجتياز كل اختبارات العتاد على مشغّل RE4 الجديد.
كل التطوير والبطاقات والمخرجات داخل المختبر. أعيد فحص 713 ملف مصدر أصلي دون تغييرات مرصودة. لا نشر ولا push ولا تعديل لحفظ المستخدم الأصلي. Play_RE4_Lab.bat جاهز لجلسة خاصة جديدة؛ تحفظ كل جلسة بياناتها في مجلد مستقل.
''')
