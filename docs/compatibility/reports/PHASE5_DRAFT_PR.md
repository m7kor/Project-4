# Draft PR محلي — لا نشر

المستودع المقصود: https://github.com/m7kor/Project-4 ؛ base:`main`؛ head المحلي:`codex/re4-vu-phase5`.

العنوان: `Preserve Phase4 correctness fixes and add a disabled VU1 FMAC classification experiment`

يحافظ التغيير على إصلاحاتPhase4 للحساب المنبعث وELF وحدودDMA، ويضيف تصنيفًا اختياريًا لحالاتFMAC الطبيعية فقط، دون تغيير الحساب أو pipeline retirement. تظل التجربة معطلة افتراضيًا لأن سبعة أزواج قياس داخلRE4 لم تثبت تسريعًا: وسيط0.203193× مقابل0.203090×، رغم مكسبVU المعزول0.7869%.

التحقق المحلي:635C++،1,048,576 helper cases لكلSIMD/scalar،إثباتZ3 وmutation controls وhelper ASan/UBSan؛ تكافؤ964command و800budget workloads وكل3200snapshot و512randomqueues. بُنيت هذه الاختبارات على runtime المختبر ذيmanifest مثبت؛ لا ادعاءCI نظيف على النسخة العامة. أضيف هدفCTest procedural مستقل بلا بيانات لعبة.

الرسوم35/35 مقابلPhase4 متطابقة؛58/59 مقابلالمقبول التاريخي مع اختلاف حركة غير معزول، لذلك لا اجتياز graphics release gate كامل. PCM الخام المشترك متطابق؛AVsync وunderruns غير محسومين. حفظ بطاقة اختبار→إغلاق→عملية جديدة→تحميل نجح، ولا إثباتroom101 جديد. تفاصيلالقيود في`core/ps2xTest/PHASE5_VALIDATION.md`.

النسخة العامة محليًا:`D:/Project/compatbilty/lab/phase4-public-source`. commits المرحلة5:`0f3f69aabda56e222744655347f230f5bd2c70a5` و`9dee8de`، فوقPhase4`debcb817ad2305cd093349fbea6b5e9ea6ea6cac`؛ قاعدةowner main:`e46891ad80087f47871c3ecb90d84bad246e3be3`. الرقعة`reports/PHASE5_PUBLIC_SOURCE.patch` مصدر واختبارات اصطناعية فقط؛ لاassets أوgenerated game code أوbinaries أوsaves أوprivate traces.

النشر متعذر: فحصGit غير التفاعلي لا يستطيع الحصول على اعتماد، وGitHub create_tree أعاد403Resource not accessible by integration. لم أغيّرcredentials ولم أنشئPR/branch بعيدًا ولم أدفع إلىGitHub. تبقى هذه مسودة للمراجعة؛ لا موافقةعلى تفعيلالتجربة أوترقيةالمشغل أودمجPR.
