# RE4 — بحث معماري مبني على المصدر

27 أكتوبر 2026. النطاق الفعلي:33 ملف مصدر/وثيقة/ترخيص من9 مستودعات، وليس مراجعة كل مشاريع إعادة الترجمة أو كل ملفاتها. الهويات والمسارات والروابط المثبتة محفوظة في `artifacts/architecture/research/manifest-complete.json`. ملفات المصدر المرجعية محفوظة محليًا فقط؛ لا أصول ألعاب ولا BIOS أو اعتماديات جديدة نُزّلت.

## المراجع المثبتة

| المشروع | المراجعة المفحوصة | أمثلة المصدر المقروء |
|---|---|---|
| [God of War](https://github.com/Waffle565/God-Of-War-Native-Port) main | `514f89186f1926edaf4807696a59557679c7d517` | `tools/vu1/vu1n_gen.py`،`tools/iop/iopn_gen.py`،`docs/runtime-changes.md`،`docs/vu1-native-flags.md` |
| God of War runtime | `ba16c8d70eb5ae73267732e3c0e36cb3b6e90ebc` | `ps2xRuntime/src/lib/vu/ps2_vu1_{native,compiled}.inl`،`ps2xIOP/src/native/iop_native_overrides.cpp`،`ps2xRuntime/src/lib/gs/gpu/gs_hw_backend.cpp` |
| [PCSX2](https://github.com/PCSX2/pcsx2) | `f0523f8acb1d3a765ee73b74cffec63093569199` | `pcsx2/x86/microVU_{Compile,Execute}.inl`،`pcsx2/MTVU.cpp` |
| [BT3-Recomp](https://github.com/z3xox/BT3-Recomp) | `e22a34beb564e2d0f32bd60b02f0a95d9645ddcc` | `tools/orchestrator/coverage.py`،`ps2xRecomp/src/lib/function_table_emitter.cpp`،`ps2xRuntime/src/lib/ps2_iop_module.cpp` |
| [N64Recomp](https://github.com/N64Recomp/N64Recomp) | `ffb39cdad1da5de07eaaa48bd1db4a89a7986771` | `src/recompilation.cpp`،`RSPRecomp/src/rsp_recomp.cpp` |
| [Zelda64Recomp](https://github.com/Zelda64Recomp/Zelda64Recomp) | `b65c482ed672258eb684ab94a4e8c8aa662615ee` | `src/main/register_overlays.cpp`،`src/main/rt64_render_context.cpp`،`src/game/recomp_api.cpp` |
| [OpenGOAL](https://github.com/open-goal/jak-project) | `e4aa2b260c06b61f9bf42ad80fc64b51978158a8` | `goalc/compiler/CodeGenerator.cpp`؛ فهرسcompiler؛ recursive tree كان أكبر من حد الاتصال، فلم أَدَّعِ جرد المستودع كله |
| [ReXGlue](https://github.com/rexglue/rexglue-sdk) | `c94f5ebdcb3c9d1a460ca48e04f9758448f8d518` | `src/codegen/project_recompiler.cpp` |
| [Xenon-Recomp](https://github.com/nimauria/Xenon-Recomp) | `f674eefd9e394a872be6f7f6764fccecde3d1547` | `src/recomp/caching/artifact_cache.cpp`،`src/cpu/codegen/fallback/dynamic_fallback.cpp` |
| [Zmbor](https://github.com/m7kor/Zmbor) | `ec4a32de4d77b41990591d87a36f475e7725099b` | `ps2xRuntime/src/lib/vu/ps2_vu1_core.cpp`؛ الرأس نفسه الذي راجعتهPhase4، فلا تطور جديد بعدPhase7 مثبت هنا |

المراجع المحلية: Phase4/Phase5 والـintegration matrix وmanifest03، والمصدر الفعلي الحالي. `docs/CURRENT.md` و`docs/MASTERPIECE_EXECUTION_PLAN.md` غير موجودين في جذر المختبر؛ عُثر عليهما في المشروع الأصلي `C:/Project/PS2redmption/docs` وقُرئا للمرجعية. حالتهما أقدم من تقارير المختبر، فلا يستبدلانها. `core/ps2xTest/PHASE5_VALIDATION.md` موجود في النسخة العامة المحلية `lab/phase4-public-source`.

## 1. كتل VU أصلية مع عقد تقاعد واضح

مولّد GoW يبني كتلًا من PC وكلمات التعليمات، مع الفروع وdelay slots وE/D/T. يستعمل runtime آليات nativeTiming وblockTiming، ومفاتيح slotFor، وفحص كلمات الشيفرة، وإظهار الكتابات المعلقة عبر syncInflight. توثيق flags نفسه يبين أن ظهور الأعلام قبل موعدها قد يزيل ظلالًا؛ لذلك لا يجوز نسخ نموذج أعلام مبسط إلى RE4.

Project-4 يحتوي بالفعل مولّدًا وكتلًا متخصصة تشترك مع المرجع في أجسام دلالات التعليمات. فُحصت هذه الآلية عمليًا، ولم يُفترض أن compiled table تعني native كاملًا. نُفذ توسيع AOT للصورة الساخنة في وضع منفصل. فشلت النسخة الأولى في حالة pipeline الكاملة؛ توقفت النسخة المصححة عند رؤوس الكتل القديمة ونجحت. رُفضت بعد ذلك للأداء، ولم تُدمج في runtime. كلفة هذا التبني متوسطة: توليد وبناء مستقلان، وعقد حدود كتلة يجب اختباره بميزانيات صغيرة وMSCNT وGIF. الرخصة المرجعية GPLv3؛ لم تُنسخ شيفرة GoW إلى التنفيذ.

## 2. MTVU ومزامنة السلاسل

مصدر PCSX2 في microVU_Compile وmicroVU_Execute وMTVU يعالج حدود التشغيل وحالة الخيط وطوابير العمل والمزامنة عند النتائج. فائدته الهندسية هي جعل نقاط انتقال الملكية والانتظار صريحة، وليست إضافة خيط دون تعريف الذاكرة المشتركة.

في Project-4 يوجد رسم GS على خيط مستقل؛ أما ps2_mtvu.h فوجود تصريحات فيه لا يثبت عامل VU فعالًا. العينات الحالية غير متزامنة ولا تقيس overlap أو كلفة كل حاجز. لذلك لم يُضاف علم يوهم بتفعيل MTVU، ولم تُنسخ بنية PCSX2. يلزم قياس تدفق VIF/DMA وقراءات EE لنتائج VU وXGKICK، ثم side-exits وعقود ملكية محدودة. المخاطر عالية: deadlocks، ترتيب الحزم، والحالة المرئية. كلفة هذا المسار عالية، وقبوله يحتاج trace ومقارنة لعبة. PCSX2 GPLv3.

## 3. خدمات IOP أصلية

مولّد IOP في GoW يربط الصور المعروفة بمعالجات أصلية. overrides والخدمات المرتبطة بـDMA والساعة والأفلام تتضمن افتراضات خاصة بالعنوان؛ لا تُنقل إلى RE4 كحلول عامة. المصدر المقابل في BT3 يوضح مسار تسجيل الوحدات والتعامل مع حدود الاستدعاءات.

Project-4 يحتوي بالفعل مسارات IOP أصلية وHLE وSIF/FILEIO وSPU2/SIO2، واختبارات replay موروثة من المرحلتين 2 و3. لم يُبنَ إطار بديل، ولم يُفترض أن كل IOP يُفسّر. القرار هو قياس fallback وترتيب الإكمال والاستيقاظ قبل استبدال خدمة أخرى. المخاطر: إسقاط wakeup، إكمال disc-read مبكر، أو تغيير ترتيب RPC والصوت. التحقق يحتاج payload وهوية الوحدة والذاكرة والمقاطعات والتوقيت المعروف. كلفة خدمة ضيقة متوسطة؛ native IOP شامل مرتفع. مرجعا GoW وBT3 GPLv3.

## 4. سجلات الوحدات والصور والتغطية

N64Recomp يعيد ترجمة الوظائف وRSP؛ Zelda يسجل overlays بحدود تحميلها وواجهات runtime، وBT3 يستعمل emitter لجدول الوظائف وأداة coverage. الدرس القابل للنقل هو ربط الكود الأصلي بهوية الصورة ونطاق تحميلها وتسجيل ما وقع فعليًا، بدل مساواة وجود عنوان في جدول بالتنفيذ الأصلي الكامل.

أُضيف عد مباشر إلى بناء تشخيصي مستقل. في الأثر الحديث بلغت تغطية أزواج VU المتخصصة 99.873319% قبل التوسيع، فرفض القياس فرضية أن نقص التغطية هو أصل البطء في هذا المشهد. هذا لا يثبت تغطية حملة كاملة أو كل الوحدات الديناميكية. التحقق يجمع عدادات التنفيذ مع هوية الصورة وآثار النتائج. كلفة العد منخفضة هندسيًا، لكنه يبقى خارج نافذة الأداء. N64Recomp MIT، وZelda وBT3 GPLv3.

## 5. IR وإقامة السجلات على المضيف

OpenGOAL CodeGenerator يستهلك IR وتوزيع سجلات وخطط spill ويصدر تعليمات المضيف. ليس أداة تلقائية لفك ELF الخاص بـRE4. Xenon يقيد fallback بأسباب وحدود واضحة بدل نجاح مفتوح. الاستفادة هنا هي تعريف الحالة التي يجب إظهارها عند كل خروج، لا نقل دلالات GOAL أو PPC إلى PS2.

فُحصت الشيفرة المرتبطة فعلًا لكتلة VU ساخنة: 13,471 بايت و2608 تعليمات ثابتة، و31 موضع نداء للتقاعد و31 لـXGKICK. لا تعني الأعداد الثابتة كلفة ديناميكية. بعد إثبات أن التغطية الأصلية مرتفعة، صار عقد register-residency مع الحالة المعلقة مرشحًا منطقيًا للتحقيق التالي، لكنه غير منفذ أو مقبول بعد. يلزم نموذج dual-issue والكمون والأعلام وside-exits، ثم مطابقة كاملة قبل قياس اللعبة. الكلفة عالية؛ تجربة كتلة واحدة أقل خطرًا من إعادة كتابة runtime. OpenGOAL ISC وXenon MIT.

## 6. هوية البناء والكاش

ReXGlue يربط fingerprint بالمصدر وإصدار SDK والخيارات والقوالب؛ Xenon يفحص digest وهوية المكتبة وABI قبل اعتبار نتيجة الكاش حديثة. توجد بالفعل في المختبر بوابات freshness وبصمات المصدر والتنفيذيات. جرى تثبيت 42 هوية سابقة و277 ملف محرك، وتسجيل المدخلات المولدة وأوامر التجميع والربط والبصمات في بناء مستقل.

لم يُنشأ كاش عام آخر. التبني الفعلي هو التحقق قبل الاختبار وبعده، وربط النتائج بالتنفيذية الصحيحة والوضع الاختياري الصحيح. المخاطر هي dependency غير مسجلة أو ربط object قديم. التحقق يرفض اختلاف المدخلات بدل إعادة تسمية تنفيذية قديمة بأنها مبنية حديثًا. كلفة manifest محدودة. ReXGlue BSD-3-Clause وXenon MIT.

## 7. الرسوم والصوت والتوقيت

مصدر GoW للـGS يعالج إعادة تفسير ذاكرة texture/render-target وعناوين GS؛ لا يثبت أن renderer عالي المستوى يستطيع تجاهل aliasing وCLUT. بقي paraLLEl-GS والمسارات المقبولة لـVIF/DMA. لا توجد GPU timestamps تبرر استبداله.

أعيد استعمال إصلاح ساعة pad الموجود في المصدر وبُني ربط Phase4 مستقل لإثباته داخل اللعبة. سجل الموفر الفعلي EE fields غير صفرية وأنتج fixture مطابقًا بتًا للأصل. لا يزال توقيت EE/IOP/DMA/SPU2 الموحد والضغط التناظري الكامل غير مسجلين. عدادات الصوت تثبت underruns فعلية، لكنها لا تفصل decoder عن الجدولة أو تثبت AV sync. لا زيادة buffers ولا تجاوز لصحة العتاد. كلفة renderer بديل عالية وغير مبررة؛ توسيع التسجيل الموجه أقل كلفة ويحتاج قياس أثره.

## الأدوات وحدود البحث

جرت مراجعة 33 ملفًا من تسعة مستودعات مع مراجعتين منفصلتين لـGoW. هذا ليس جردًا لكل مصدر في كل مشروع. الروابط الدقيقة لكل ملف وblob موجودة في manifest-complete.json. المصادر المرجعية والكود المشتق من اللعبة بقيت خاصة؛ لم تدخل patch النشر.

استُخدمت الأدوات المثبتة: clang 23.1.1 وأدوات LLVM وCMake/Ninja/sccache، والمراقب الحالي وreplay، وZ3 الموجود سابقًا. نجح تعداد WPR دون التقاط ETW جديد. فُتحت نسخة مستقلة من قاعدة Ghidra القائمة، بلا auto-analysis وبوضع discard، واستُخرجت عناوين صادرات الذخيرة وارتباطها بحقل مضغوط. تطابقت هوية ELF وعدد وظائف قاعدة التحليل 7315. قاعدة Ghidra الأصلية لم تتغير.

لم تُدمج Tracy أو RenderDoc أو GFXReconstruct أو AFL++ أو Google Benchmark في هذه الدفعة، ولا يُحسب مجرد ذكرها إنجازًا. لا حزم أو Docker جديدة ولا تنزيل للعبة أو BIOS. تفاصيل القياس والقرارات السلبية في RE4_PERFORMANCE_ROOT_CAUSES.md وRE4_ARCHITECTURE_DECISIONS.md.
