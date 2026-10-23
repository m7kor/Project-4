# تتبع أجزاء الشخصية من تعليمات اللعبة

استخرجت أداة `tools/diagnostics/snr2_import_lookup.py` الأسماء التالية من imports وحدة sscrn وطابقتها مع جدول exports للملف الرئيسي، ببصمتيهما المثبتتين في [تقرير المطابقة](../artifacts/verification/review-20261013-model-import-targets.json):

| الدالة | عنوان EE |
| --- | --- |
| AppendModelOt | 0x257A68 |
| MotionMove | 0x230270 |
| getPartsPtr | 0x22F1F0 |
| modelInit | 0x22C580 |
| partsMatCalc | 0x22C970 |
| partsWorldCalc | 0x22CF28 |

نجح GhidraMCP في فك حساب المصفوفات المحلية والعالمية واختيار الجزء. دالة getPartsPtr تبدأ من المؤشر root+0x110؛ عند علم root&0x2000 تختار عنصرًا متصلًا بحجم 0x270 بايت، وإلا تتبع next عند part+0x110. فهرس سالب يعيد root. هذا يحدد بنية التنقل، لكنه لا يحدد فهرس الرأس أو أن root المرصود يعود إلى ليون. [اختيار الجزء](../artifacts/verification/review-20261013-model-get-parts-decompile.log).

partsWorldCalc تقرأ parent عند part+0x100 والأعلام عند +0x114؛ علم 2 يتجاوز حساب المصفوفة. تقرأ المصفوفة المحلية +0x50..0x80 والعالمية للأب +0x10..0x40 والمقياس +0xE0/+0xF0. تفاصيل تعليمات VU لا تُستنتج بدقة من pseudocode الذي يحمل سجلات متجهات غير معرّفة. [الحساب المحلي](../artifacts/verification/review-20261013-model-parts-matrix-decompile.log)، [الحساب العالمي](../artifacts/verification/review-20261013-model-parts-world-decompile.log).

فُكت أيضًا modelInit وAppendModelOt. التهيئة تعتمد على موردين وتعود بفشل عند غيابهما؛ لا نزيّف النجاح. مسار إرسال الرسم يختار من نوع عند root+0x157 وجدول قفز في 0x3C10A0 أو callbacks مختلفة، مع حساب عمق/حجم؛ Ghidra لم يستعد جدول القفز كاملًا في pseudocode. العمل التالي ربط root المرصود بالمورد والنوع الفعلي، ثم تتبع مسار الرسم المختار وأجزاء الرأس بين المشي والتصويب. [التهيئة](../artifacts/verification/review-20261013-model-init-decompile.log)، [إرسال الرسم](../artifacts/verification/review-20261013-model-append-ot-decompile.log).

أضيف `--snapshot-target` لأداة الجولة المعزولة، مع تحقق العنوان والمحاذاة؛ يستخدم التقاط RAM القائم عند دخول دالة محددة بعد عتبة EE. لا يلتقط VF أو scratchpad أو أجهزة المحاكي ولا يعد save state. أكملت v14 مدة 300 ثانية دون أعطال مرصودة أو تغير بطاقتي الحفظ. التقط أول دخول partsWorldCalc عند EE 6651 من المستدعي 0x1D0F500، مع root=0x1798C40. [هوية الجولة](../artifacts/verification/review-20261013-vu1-missing-model-v14.json).

أضيف `tools/diagnostics/model_parts_inspect.py` لفحص سلسلة الأجزاء ومصفوفاتها بحدود قراءة وعدد محدد ودون كتابة RAM. اجتازت خمس حالات: سلسلة صحيحة، دورة، مؤشر تالف، قيمة NaN، وalias RAM. اللقطة الفعلية تضم 24 جزءًا، بلا مشكلة روابط أو قيمة غير محدودة في الصفوف والمقاييس المفحوصة. ليست هذه مقارنة مع PCSX2 أو دليل صحة اختيار الجزء/القص أو أن الموديل ليون؛ لا تلتقط نتيجة الحساب بعد الدالة. [فحص الأداة](../artifacts/verification/review-20261013-model-parts-inspect-selftest.json)، [الذاكرة الفعلية](../artifacts/verification/review-20261013-vu1-missing-model-v14-parts.json).

جرد 400 لقطة VU1 من EE 6201..6207 وجدها جميعًا للصورة 53c46ebcaf7db574 المغطاة أصلًا. برنامج 3113a8f8d199f6fe ظهر لاحقًا، لذلك لا تُنسب إليه هذه اللقطات ولا يُعلن اختباره بها. يجري التقاط مستقل بعد EE 6300 للتحقق من البرنامج غير المغطى. [جرد اللقطات](../artifacts/verification/review-20261013-vu1-missing-model-v14-vu1-manifest.json). لم يثبت سبب نقص الرأس بعد.
