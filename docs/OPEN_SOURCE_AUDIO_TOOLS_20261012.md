# أدوات مفتوحة المصدر للصوت والأداء — 2026-10-12

هدف البحث: إصلاح صوت الكتسينات والتكرار والتشويش من المصدر، ثم الوصول لسرعة لعب طبيعية. وجود أداة أو نجاح فك ملف لا يثبت إصلاح تشغيل اللعبة.

| الأداة | كيف تساعد المشروع | الحالة الفعلية |
|---|---|---|
| [vgmstream](https://github.com/vgmstream/vgmstream) | فك صيغ صوت الألعاب، ومنها CRI ADX، بمرجع ثانٍ لمقارنة البيانات التي تنتجها اللعبة | النسخة الرسمية Windows x64 **r2117** مجهزة ومختبرة داخل `dependencies/vgmstream/r2117/bin` |
| [FFmpeg](https://ffmpeg.org/) | فصل صوت SFD عن الفيديو وفكه، مع إمكانية نسخ ADX المضغوط دون إعادة ترميز | موجود فعليًا، إصدار **8.0.1**؛ استُخدم في التجربة أدناه |
| [miniaudio](https://github.com/mackron/miniaudio) | مكتبة تشغيل والتقاط الصوت؛ تستخدمها أداة تسجيلنا لالتقاط مخرج السماعات رقميًا عبر WASAPI loopback | مدمجة في `tools/audio/capture_speakers.cpp`؛ يُشغلها `Record-Game-Audio.cmd`. يلتقط المخرج المحدد، ولذلك قد يدخل في التسجيل صوت برامج أخرى تستخدمه |
| [Audacity](https://www.audacityteam.org/) | الاستماع للقناتين، مشاهدة الموجة والطيف، وتسجيل مخرج ويندوز عبر WASAPI loopback | اختير للتحليل اليدوي؛ لم يُثبت أو يُختبر هنا. الأداة المحلية `Record-Game-Audio.cmd` تؤدي الالتقاط الحالي |
| [Sonic Visualiser](https://github.com/sonic-visualiser/sonic-visualiser) | عرض الطيف وتعليم مواضع التشويش وتشغيل المقاطع المحددة؛ يدعم إضافات تحليل Vamp | بديل متخصص للتحليل البصري؛ لم يُثبت أو يُختبر هنا |
| [Tracy](https://github.com/wolfpld/tracy) | تحديد تكلفة IOP وIPU وGS وVU، انتظار الخيوط والأقفال، وربطها بالإطارات | المصدر موجود في `dependencies/tracy` (BSD-3-Clause)؛ لا يوجد ربط فعال أو برنامج profiler مبني ثبت تشغيله في هذه المراجعة |
| [PCSX2](https://github.com/PCSX2/pcsx2) | مرجع مفتوح المصدر لمراجعة SPU2 ومعالجة تدفق الصوت، ومقارنة تشغيل المشهد نفسه | مصدره موجود في المشروع، وتكامل `kzspu2` يستخدم نسخة مثبتة من SPU2. وجود المصدر لا يثبت تطابق الصوت النهائي مع المحاكي |

## الأداة الجديدة اختُبرت، لا مجرد اقتراح

حُمّلت `vgmstream-win64.zip` من [الإصدار الرسمي r2117](https://github.com/vgmstream/vgmstream/releases/tag/r2117). تطابق SHA-256 مع digest المنشور من GitHub:

`6c4a8a3813864fefed081bbd337dbc0ad93bf88e0b92f5db98d7ab258b22dc6c`

تفاصيل المصدر محفوظة في `dependencies/vgmstream/r2117/UPSTREAM.json`، وإشعار الترخيص الأصلي في `bin/COPYING`. رخصة مشروع vgmstream سماحية مع الاحتفاظ بالإشعار؛ الحزمة تتضمن مكتبات خارجية لها تراخيصها. الأداة مستقلة عن ملف اللعبة التنفيذي.

اختبار `r120s00.sfd` المستخرج محليًا من أرشيف المستخدم:

1. لا تفتح هذه النسخة ملف SFD مباشرة؛ سجل المحاولة محفوظ. فصلنا مسار ADX بعملية نسخ بواسطة FFmpeg، دون إعادة ترميز.
2. فك vgmstream المسار: ADX type 04، قناتان، 48000Hz، 3194496 إطارًا، مدة 66.552 ثانية.
3. فحص الصوت أعطى مرشح نقرة واحدًا، بلا قص. FFmpeg أعطى كذلك مرشحًا واحدًا.
4. مقارنة 3194272 إطارًا مشتركًا أعطت ترابط **0.9997648/0.9997653** للقناتين؛ فرق RMS نحو 120.70 وأقصى فرق عينة 960. الناتجان ليسا متطابقين بتًّا، وvgmstream أطول بـ224 إطارًا. اختلاف فك ADX يجب أن يُراعى عند المقارنة، فلا يُشترط التطابق البتّي مع اللعبة.

الأدلة:

- [سجل فك ADX](../artifacts/verification/review-20261012-vgmstream-adx.log)
- [فحص الصوت](../artifacts/verification/review-20261012-vgmstream-audio-check.json)
- [مقارنة المرجعين](../artifacts/verification/review-20261012-independent-adx-decoders.json)

## تشغيل المقارنة نفسها

من جذر المشروع، مع ملف SFD محلي ومخرجات جديدة:

```powershell
ffmpeg -v error -i scene.sfd -map 0:a:0 -c:a copy -f adx scene.adx
dependencies/vgmstream/r2117/bin/vgmstream-cli.exe -i -o scene-vgmstream.wav scene.adx
python tools/diagnostics/audio_check.py scene-vgmstream.wav --out scene-report.json
```

يجب التحقق من نجاح كل خطوة قبل التالية. `-i` يمنع التكرار في vgmstream، فلا تُقارن مدة ملف مُكرر مع مدة الكتسين.

الأولوية الهندسية: مرجعا FFmpeg/vgmstream لدخل ADX وخرجه، ثم مقارنة قطع PCM في EE/IOP. الأدلة الحالية تستبعد القراءة أثناء ملء مخزن ADMA في النطاق المفحوص. أداة تسجيل السماعات تبقى مرجع ما يصل للمستخدم، وTracy مطلوب لتحديد أسباب البطء بعد ربطه بمراحل التشغيل. أدوات تحرير الصوت لا تعالج خلل المحاكاة بمجرد تنقية التسجيل.

مراجع القدرات: [قائمة صيغ vgmstream](https://github.com/vgmstream/vgmstream/blob/master/doc/FORMATS.md)، [تعليمات Audacity لتسجيل مخرج ويندوز](https://manual.audacityteam.org/man/tutorial_recording_computer_playback_on_windows.html)، [قدرات Sonic Visualiser](https://github.com/sonic-visualiser/sonic-visualiser#readme)، [Tracy](https://github.com/wolfpld/tracy#readme).
