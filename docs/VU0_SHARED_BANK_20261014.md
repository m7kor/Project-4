# مشاركة بنك VU0 عند تبديل سياقات EE

## الخلل والتغيير

كان GuestInvocation يبدأ بسياق R5900Context جديد، ويحفظ كل خيط بنك VF/VI مستقلًا. بذلك يرى callback قيمًا صفرية بدل القيم الحالية، ثم تعود القيم القديمة عند استئناف الخيط. تعديل FBRST/VPU_STAT السابق حمى تحكم الجهاز فقط، ولم يحمِ بقية البنك.

أصبح `runtime.cpu()` صاحب بنك VF/VI وQ/P/I وR وACC وSTATUS/MAC/CLIP وCMSAR0/1 وTPC في منفّذ EE. ينقل `EeScheduler.cpp` البنك إلى عرض السياق قبل تنفيذ الدالة، وينشر نتيجة العرض بعد العودة أو EeDispatcherTransfer. يشمل ذلك resumeCompletion وonComplete، ويُبقي GPR وCOP1 وPC والمكدس في سياق كل خيط.

النشر يحل الإطار الأصلي بواسطة معرّف الخيط وعمق الاستدعاء ورقمه التسلسلي؛ لا يحتفظ بمرجع إلى عنصر vector عبر invokeCurrent، لأن النمو قد ينقل العناصر. ExitDeleteThread ينشر البنك قبل مسح الاستدعاءات وحذف الخيط. نسخ main إلى runtime يحفظ البنك والتحكم المشترك بدل استعادة نسخة قديمة. reset يبدأ البنك من سياق main الجديد، ولا يستبدل FBRST/VPU_STAT بهذا النسخ.

هذا نقل عند حدود التنفيذ، وليس تشغيل VU0 أو VU1 على عامل جديد. لا يغير ترتيب تعليمات VU أو جداول VU1 أو تعليمات اللعبة أو سياقات COP1/GPR. حقول VU الإضافية غير المدعومة في R5900Context لم تصبح تعريفًا جديدًا لسجلات العتاد.

## المرجع وحدوده

أُعيد فحص [Play! PS2OS.cpp — ThreadSaveContext/ThreadLoadContext](https://github.com/jpd002/Play-/blob/master/Source/ee/PS2OS.cpp) في 2026-10-14: ينقل GPR وCOP1 وHI/LO وSA وFCSR، ولا يحفظ بنك VU0 ضمن إطار الخيط أو المقاطعة. هذا مرجع تنفيذ HLE، وليس قياسًا من PS2 حقيقيًا. لم يُنقل كود منه. الاختبارات الجديدة تثبت عقد مشروعنا للملكية المشتركة، ولا تثبت سبب نقص الرأس في RE4.

## التحقق المنجز

- قبل الإصلاح: 580 اختبارًا، 577 ناجحة وثلاث حالات فاشلة تخص البنك. [البناء](../artifacts/verification/review-20261014-vu0-bank-before-build.log)، [الاختبارات](../artifacts/verification/review-20261014-vu0-bank-before-tests.log).
- بعد الإصلاح: 580/580، تشمل دخول callback والعودة، 16 استدعاءً متداخلًا مع نمو vector وكل عمليات العودة، وخيطًا يوقظ main ثم يحذف نفسه. تقارن VF بأربع حارات وVI وQ/I/P وACC وبتات R وSTATUS/MAC/CLIP وCMSAR0 وTPC، وتتحقق من استقلال COP1/GPR. [الاختبارات](../artifacts/verification/review-20261014-vu0-bank-after-tests.log).
- أضيفت حالة INTC فعلية عبر postEvent وaddIrqHandler، وليست مجرد تغيير نوع invocation: ترى المقاطعة بنك main، وتنشر تغييره عند العودة مع صحة وسيط IRQ واستقلال COP1. اكتملت المجموعة الموسعة **581/581**. [البناء](../artifacts/verification/review-20261014-vu0-bank-irq-build.log)، [الاختبارات](../artifacts/verification/review-20261014-vu0-bank-irq-tests.log).

النسخ السابقة محفوظة في `artifacts/tool-audit/20261014/vu0-bank-before/`. مشغل ما قبل التغيير SHA256: `3c9326a4f9240c97b56164255646a094fa83bb6c8b07d54f903334c894ee97d7`.

## ما لم يثبت بعد

اكتمل بناء مشغل اللعبة برمز خروج صفر وبصمة `0ce22b2424f93b524edd26a2c72c2154c1e9b12e7fd6acfbd177d9d3b1525548`؛ أعاد فحص Ninja «no work to do». [البناء](../artifacts/verification/review-20261014-vu0-bank-runner-build.log)، [فحص الاتساق](../artifacts/verification/review-20261014-vu0-bank-runner-consistency.log).

## نتيجة اللعبة v19

اكتملت الجولة المعزولة 320 ثانية بمهلة مقصودة (124)، دون أعطال مرصودة، وبصمة المشغل ثابتة، وبطاقتا الحفظ دون تغيير وفحصهما سليم. [هوية الجولة](../artifacts/verification/review-20261013-vu0-shared-audio-v19.json). توجد 13 صورة مختلفة بعد EE6130 على مدى 122.299 ثانية، دون صورة سوداء أو streak متطابق في العينات؛ ليست قياس كل إطار. [فحص الصور](../artifacts/verification/review-20261014-vu0-shared-audio-v19-frames.json).

فُحصت صورة المشي `frame-12000.png` عند EE6796 وزمن 205.580 ثانية: الرأس ناقص. فُحصت صورة التصويب `frame-13200.png` عند EE7390 وزمن 225.930 ثانية: الرأس ظاهر. إصلاح البنك لم يحل العيب المرئي؛ التالي تحديد الجزء ومدخلاته وتحويله وحزمة رسمه.

السرعة الإجمالية **0.4828766×** ونافذة الذيل الأخيرة **0.3075269×**. المقارنة مع v17 في EE6400–7800 تعطي تقديرًا −0.237% وحدودًا واسعة −33.29% إلى +49.83% بسبب العينات المتباعدة؛ لا يثبت تسريعًا أو تراجعًا منفردًا للتغيير. الجولة سجلت الصوت ورصدت الجلسات، فلا تستعمل كقياس أداء هادئ. عداد display_flips ما زال صفرًا رغم الصور المتغيرة، ولا يثبت 0 FPS. [السرعة](../artifacts/verification/review-20261014-vu0-shared-audio-v19-speed.json)، [مقارنة المشهد](../artifacts/verification/review-20261014-vu0-shared-audio-v19-compare-v17.json).

تسجيل السماعة اكتمل 160 ثانية و7,680,000 إطار، دون overflow أو null input، وبدون مرشحات نقر أو قص في الفحص. هذه نتيجة الكشف الآلي للنطاق المسجل، لا إدراك سمعي أو قبول للحملة. خرج SPU2 الخام 152.93 ثانية، وخرج التمديد الداخلي 316.76 ثانية؛ مرشح واحد وثلاثة على الترتيب، وصفر قص. زيادة underruns في الجولة 136836 إطارًا. [التقاط المخرج](../artifacts/verification/review-20261014-vu0-shared-audio-v19-loopback.log)، [فحص السماعة](../artifacts/verification/review-20261014-vu0-shared-audio-v19-heard-audio.json)، [فحص الداخل](../artifacts/verification/review-20261014-vu0-shared-audio-v19-internal-audio.json).

مطابقة SPU2 الخام مع v17 بلا تصحيح توقيت: **7,340,654 إطارًا متطابقًا في القناتين، صفر اختلاف**؛ v17 يحتوي تسعة إطارات إضافية في النهاية، لذلك الملفان كاملان ليسا متطابقين. لا نعمم هذا على الخرج الممدد أو السماعة. [المقارنة](../artifacts/verification/review-20261014-vu0-shared-audio-v19-spu2-compare-v17.json).

المطابقة العالمية الأصلية تقبل 4/6 نوافذ. إعادة الفحص حول إزاحة موحدة 165.6814 ثانية تقبل **6/6** وفق شرط PCM المحلي، بترابط 0.9046–0.9823. هذا شرط مختلف موثق في الأداة، لا إسقاط لمعيار المطابقة العالمي ولا قبول لجودة الصوت كله. التسجيل يتضمن ذيلًا بعد إنهاء اللعبة؛ لا ننسب الصمت اللاحق إلى underrun من اللعبة. [المطابقة وحدودها](../artifacts/verification/review-20261014-vu0-shared-audio-v19-endpoint.json).

رصد الجلسات اكتمل بـ2540 عينة خلال 280 ثانية، لكنه **لا يثبت أن Discord يصدر صوتًا مستقلًا**: ظهرت جلسة مسجل loopback نفسه، وتطابقت ذروة Discord بعد تحجيم مستواه مع اللعبة ضمن دقة الطباعة في 1611/2451 عينة مشتركة. جلسات loopback تعامل كالتقاط وفق [توثيق Microsoft](https://learn.microsoft.com/en-us/windows/win32/coreaudio/audio-sessions). عدّل محلل الرصد ليصرح بعدم ثبوت استقلال المصدر؛ التقرير القديم الذي يسمي الملاحظة other_source_observed محفوظ لكنه متجاوز بالتقرير الجديد. يلزم تسجيل خاص بعملية اللعبة ومقارنته بالتقاط المخرج كله؛ [عينة Microsoft الرسمية](https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/) تتيح ذلك دون كتم التطبيقات. [القياس الجديد](../artifacts/verification/review-20261014-vu0-shared-audio-v19-session-observations.json)، [فحص استقلال الذروات](../artifacts/verification/review-20261014-vu0-shared-audio-v19-meter-independence.json).

نسخ البنك عند كل حد تنفيذ له كلفة؛ يجب قياسها داخل المشاهد نفسها. إعادة ترتيب حدود التنفيذ أو تفعيل عامل VU يتطلب مزامنة إضافية، ولا يكفي نجاح هذه الاختبارات لتمكين العمل المتوازي. الحملة والحفظ الفعلي والصوت الطبيعي ما زالت غير مقبولة.
