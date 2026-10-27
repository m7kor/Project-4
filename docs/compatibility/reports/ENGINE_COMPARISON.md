# مقارنة المحركين الفعليين

Zmbor: upstream eb8688b، فرع التطوير ae1c119، وفرع integration 00173a2. تحقق ذلك بقراءة Git worktree list والسجل.
Project-4/core: c5a9d02573410a2085a4b4b831b0b68ba3515440 مع تغييرات محلية كثيرة غير ملتزم بها؛ نُقلت حالتها الحالية إلى نسخة مستقلة مع حفظ التاريخ الأصلي.
الفروع المعزولة: compat/re4-zmbor-20261024 وcompat/re4-reference.

| المكوّن | الدليل/الاختلاف | قرار التكامل |
|---|---|---|
| R5900 / EE | Project-4: إصلاحات delay slot والاستدعاء المتناثر؛ Zmbor: فروع bit63 وMOVZ/MOVN وتوسيع اكتشاف المداخل | قارن الترجمة باختبارات العتاد قبل إعادة توليد أي كود |
| MMI | Project-4: تصحيحات permutation من جولات اللعب؛ Zmbor: متجهات ضرب وتجميع/قسمة من PS2 | مرشح نقل المتجهات والاختبارات، لا استبدال المترجم |
| FPU | Zmbor: RZ وFCR31 وتشبع ومقارنات encoding؛ Project-4: مسارات EE مستقلة | اختبار نتائج hardware على المترجمين قبل الدمج |
| VU0 / VU1 | Project-4: كتل RE4 متخصصة وإعادة أوامر Continue؛ Zmbor: EFU ومتجهات hardware | حفظ الكتل المتخصصة؛ نقل FLG3 فقط في XGKICK، لا تغيير FMAC/flags |
| VIF | Project-4: UNPACK سريع مثبت في اللعبة؛ Zmbor: تجزئة الأوامر وI-bit stalls | نقل IMAGE2 ضيق؛ stalls مرشحة لاحقة بأثر محدد |
| GIF / GS | Project-4: FIFO لكل مسار، parallel-gs، traces؛ Zmbor: IMAGE2 بخمسة مواقع | دمج شروط IMAGE2 دون استبدال FIFO أو backend |
| DMAC / SPR | المشروعان يصلحان حد 4096؛ Zmbor لديه SPR/interleave/chain hardware coverage | تجنب تكرار الإصلاح؛ مطابقة MADR/SADR وD_STAT أولًا |
| IOP / SIF | Project-4: IOP فعلي وSNR2 وقراءة قرص وصوت؛ Zmbor: responder مناسب للاختبارات | الإبقاء على IOP الحقيقي للعبة؛ لا استبداله بمستجيب اصطناعي |
| IPU | Project-4: فك SFD/FFmpeg وIPU مع أدوات probes | إبقاء التنفيذ القائم؛ قياس حقول IPU في الجولة |
| SPU2 | Project-4: native SPU2 وكود صوت مدمج واختبارات الجسر | عدم استبدال الصوت؛ underruns ليست جودة سمعية مثبتة |
| Streaming | Project-4: AFS وCDVD host read؛ Zmbor: اختبارات ISO/مسارات | القراءة من الملفات الأصلية، مع ELF وحفظ محليين |
| Controllers | Project-4: native SIO2 وإعادة إدخال ومسار feedback | فصل دليل replay عن اختبار يد تحكم حقيقية |
| Memory cards | Project-4: migration وحفظ raw/file؛ Zmbor: عزل mc0 | بطاقات اختبار من fixture خاص فقط؛ لا ملف حفظ مستخدم |
| Timing / scheduling | Project-4: مؤقتات EE/IOP وعينات monotonic؛ Zmbor: kernel tests | ثبات المشهد/الإدخال؛ لا استنتاج سرعة من بقاء العملية |

المقارنة المباشرة للمصادر: {'equal': 140, 'different': 103, 'project4-only': 78}؛ التفاصيل لكل ملف في artifacts/source-comparison.json.
الأرقام لا تعني تكافؤًا وظيفيًا؛ ملفات كثيرة تطورت بطرق مختلفة.

الهندسة الموجودة: core/out/build هو Release/clang-cl/Ninja مع FFmpeg وparallel-gs وnative SPU2؛ يوجد أيضًا build-pgs/build2/build-with-runtime-libraries.
recomp/generated يحوي كود EE، وrecomp/native/SLUS_211.34/full_build يحوي وحدات SNR2 الكاملة؛ لم نعد توليدها ولم نعدل ملفاتها.
الأدوات المنقولة تشمل فحص ELF/SNR2 والـrelocations وVU replay وhost sampling وspeed/audio/input/save reports وGhidra scripts.
Ghidra 12.1.4 ومكوّن EE وGhidraMCP موجودة ضمن dependencies؛ وجود الأدوات ليس إثبات أن كل وحدة حللت في قاعدة Ghidra.
آخر حالة هندسية مقروءة: PS2_PROJECT_STATE.md المؤرخ 2026-10-19 وأول مواجهة، وHANDOFF.md الخاص بـ Zmbor المؤرخ 2026-10-24.
الجرد الموسع في artifacts/engineering-inventory.json يسجل 530 عنصرًا هندسيًا مختارًا من 187037 مدخلًا، مع استبعاد الحفظ وBIOS ومحتويات البناء والكود المولد. توجد ستة مؤشرات مشاريع Ghidra، منها artifacts/ghidra/re4.gpr وartifacts/ghidra_iop/adxdrv.gpr. وجود مؤشر المشروع لا يثبت تغطية تحليله.
