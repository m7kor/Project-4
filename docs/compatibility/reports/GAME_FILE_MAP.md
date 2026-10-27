# خريطة ملفات اللعبة

| الملف | الحجم بالبايت | ELF مضمن | SNR2 |
|---|---|---|---|
| 0flist.dir | 43 | 0 | 0 |
| bio4dat.afs | 1537845248 | 0 | 195 |
| bio4mov.afs | 1963034624 | 0 | 0 |
| bio4mov2.afs | 909705216 | 0 | 0 |
| ioprp.img | 275345 | 16 | 0 |
| modules.dat | 313704 | 7 | 0 |
| SLUS_211.34 | 3096892 | 1 | 0 |
| SYSTEM.CNF | 57 | 0 | 0 |

العلاقات: SYSTEM.CNF → ELF الأساسي → IOPRP/خدمات SIF وFILEIO/CDVD → MODULES.DAT → فهرس AFS → وحدات الغرف والموارد والأفلام.
فهرس 0flist.dir حجمه 43 بايت؛ ليس أرشيفًا. ملفات AFS تُقرأ على دفعات، ولا ينبغي تحميلها كاملة في الذاكرة.

| الحاوية | المدخلات | التواقيع المثبتة |
|---|---|---|
| Resident Evil 4 (USA)/data/bio4dat.afs | 2628 | {'unknown': 2433, 'SNR2': 195} |
| Resident Evil 4 (USA)/data/bio4mov.afs | 515 | {'unknown': 386, 'MPEG-PS': 129} |
| Resident Evil 4 (USA)/data/bio4mov2.afs | 153 | {'unknown': 113, 'MPEG-PS': 40} |

كل صف في `*.afs.index.json` يربط الاسم والفهرس والإزاحة والحجم والتوقيع، وكل صف ISO يحدد LBA.
التمييز مهم: `.tpl` 564 و`.bin` 252 و`.snd` 358 و`.rel` 207 و`.esl` 32 و`.dat` 965 في أرشيف البيانات، وهي تصنيفات أسماء وليست تحققًا كاملًا من الصيغة.
ثبتت تواقيع 244 ملف CRI ADX عبر الحاويات الثلاث، و169 MPEG-PS بأسماء .sfd. لا تؤيد هذه العينة تعميم ملف التعريف القديم بأن الصوت OGG فقط أو الأفلام STR/ATR فقط.
ملفات .evd موجودة مع أفلام الغرف: r100s03.evd وr100s03.sfd في bio4mov.afs؛ الارتباط الوظيفي بأول مواجهة موثق في هندسة Project-4 السابقة، وليس من تشابه الاسم وحده.
الأنيميشن والهندسة والخامات داخل BIN/TPL/DAT تحتاج محللات الموارد الموجودة؛ لم ندّع تحقق بنية كل مورد من الامتداد.

ROMDIR و183 جدول import/export إجمالًا في IOPRP/MODULES موثقة بإزاحاتها في extended.json. هذه جداول اعتماد ثابتة، وليست ترتيب تحميل حيًا مثبتًا.
المكتبات تشمل SYSMEM/LOADCORE/SIFCMD/SIFMAN/THREADMAN/IOMAN/MODLOAD/FILEIO/CDVDMAN/CDVDFSV/LOADFILE؛ وأسماء الجداول الكاملة في البيانات الوصفية.
قراءة .iopmod ربطت الاعتمادات بكل IRX منفرد في iop-dependencies.json: وحدات MODULES السبع هي sio2man وpadman وSound_Device_Library وCapcom Sound Engine وCRI_ADX_Driver وmcman وmcserv؛ لا نستنتجها من الامتدادات.
