# أدوات الرسوم والأداء الإضافية — 2026-10-14

استُكملت أدوات المرجع الأساسية في الدفعة السابقة. أضافت هذه الدفعة أداتين تساعدان التحقيق المتبقي في الرسوم وكلفة التنفيذ، بنسخ محمولة داخل المشروع دون تغيير إعدادات النظام أو بناء اللعبة.

| الأداة | الموقع المحلي | تحقق التشغيل |
| --- | --- | --- |
| [RenderDoc 1.46](https://github.com/baldurk/renderdoc/releases/tag/v1.46) | `dependencies/tools/renderdoc-1.46/RenderDoc_1.46_64` | `renderdoccmd version` أكد x64 v1.46 وcommit `e4bd23b671d3d5a747ff5221dbe08a63eb6ca200`. تحميل renderdoc.dll وطلب API1.0.0 نجحا، وأعاد API1.7.0. |
| [Tracy 0.14.1](https://github.com/wolfpld/tracy/releases/tag/v0.14.1) | `dependencies/tools/tracy-0.14.1` | أدوات capture/import-chrome/csvexport اشتغلت، commit30997d5. استيراد تتبّع VU1 الفعلي ثم تصدير ثلاثة events حافظ على مددها بدقة100ns أو أفضل. |

**البصمات:** حزمة RenderDoc الرسمية `9ca4d09ecaba2cc791168660d6fc2a7e3d70fe67146e87ec05c5f8dea70772f7`، وحزمة Tracy الرسمية `f7499d74914aa3ba94a2c1ce72f36477d7b61d9d0f7c9790e05274c258c97fb5`. هذه بصمات الملفات المنزلة محليًا، وليست توقيعات مستقلة منشورة من المورد. الأصلان من renderdoc.org وGitHub/wolfpld/tracy. LICENSE.md ودليل RenderDoc داخل حزمته، ودليل Tracy الرسمي tracy.pdf بجانب أدواته. مصدر Tracy السابق وLICENSE بقيا في `dependencies/tracy`.

## تطبيق عملي للأدوات

أضيف [renderdoc_api_probe.py](../tools/diagnostics/renderdoc_api_probe.py) للفحص في عملية مستقلة؛ لم يحقن DLL في اللعبة أو يثبت Vulkan layer ولم يلتقط إطار لعبة. [نتيجة تحميل API](../artifacts/verification/review-20261014-renderdoc-api.json). API المقبولة هي نفسها المطلوبة في مصدر Granite؛ هذا لا يثبت تفعيل تكامل Granite في بناء المشغل الحالي.

أضيف تصدير Chrome trace إلى [vu1_mode_compare.py](../tools/diagnostics/vu1_mode_compare.py). يسجل مدد subprocess الحقيقية للمفسر والمترجم والعامل مع تسمية نطاقها بوضوح. تشمل بدء العملية وتجهيز benchmark وإعادة تشغيل اللقطات وحساب GIF؛ **ليست frame times أو قياس سرعة اللعبة أو زمان كل تعليمة VU1**.

أُعيدت مقارنة24 لقطة فعلية: المسارات الثلاثة متكافئة في47,949 دورة، وحالة السجلات/الذاكرة، و36 حزمة GIF. بعدها حوّل Tracy التتبّع إلى ملف قابل للعرض ثم صدّر CSV؛ طُوبقت أسماء events ومددها ضد الملف الأصلي بنجاح.

الأدلة:

- [المقارنة وملفات التشغيل](../artifacts/verification/review-20261014-extra-tools-vu1/comparison.json)
- [ملف Tracy الجاهز للعرض](../artifacts/verification/review-20261014-extra-tools-vu1/replay.tracy)
- [إحصاءات التتبّع](../artifacts/verification/review-20261014-extra-tools-vu1/replay-zones.csv)
- [قبول الاستيراد والتصدير](../artifacts/verification/review-20261014-extra-tools-vu1/tracy-roundtrip.json)

مصدر Tracy الموجود يعلن إصدار0.14.2 تجريبيًا، بينما أدوات الإصدار المستقر0.14.1. لم يُربط العميل التجريبي بالخادم المستقر داخل اللعبة؛ اختبار الاستيراد مستقل عن بروتوكول اتصال client/server.

## التحقق والحدود

نجحت285/285 اختبارات Python بعد إضافة التتبّع، وبناء المشغل والاختبارات وbenchmark انتهى `no work to do`. لم تتغير ملفات C++ أو CMake أو headers أو الملفات المولدة؛ لم نعد اختبارات C++609 السابقة دون تغيير محرك يستلزم ذلك. فحص RenderDoc API نجح بعد اكتمال التنزيل، وأدوات تنزيل الحزمتين انتهت بنجاح.

جاهزية الأدوات لا تحل بطء اللعبة تلقائيًا. المتبقي استخدامها لالتقاط إطار Vulkan من جلسة قبول محددة وإضافة مناطق Tracy أو قياس عينات بحمل المشهد الكامل مع عميل متوافق. مقارنة PCSX2 الحية وتفعيل عامل VU1 داخل اللعبة ما زالا غير مكتملين كما في [الدفعة السابقة](TOOLCHAIN_BATCH_20261014.md).
