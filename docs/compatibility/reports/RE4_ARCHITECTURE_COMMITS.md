# RE4 — التثبيتات المحلية وحزمة المراجعة

27 أكتوبر 2026. الفرع `codex/re4-architecture-recovery`.

- تثبيت المصدر والاختبارات والتقارير: `315036bce7dd8eac5aa462eaa9ca061b075be3a6`.
- أساسه المحفوظ: `4c0e7a49cbf0cf521c17872532bae36cc2db174e`؛ تثبيت Phase5 السابق `fc7dcfeb3b1d1773d75766b2203f51c73bbe7556` محفوظ.
- البصمات والمدخلات وأوامر البناء: `artifacts/architecture/final-01/manifest.json` وملفات build_witnesses المشار إليها فيه.
- ربط manifest بالتثبيت: `artifacts/architecture/final-01/commit.json`.
- patch مصدر فقط: `artifacts/architecture/final-01/RE4_ARCHITECTURE_SOURCE_ONLY.patch`، SHA-256 `71f85ee490d9ebbf4cf78a660305237b6d589ba9b0480b754113e9bae8190890`.

الـmanifest يثبت بايتات ملفات العمل الفعلية قبل التثبيت، مع مدخلات البناء الخاصة؛ Git قد يطبع نهايات الأسطر عند التخزين وفق إعداداته. لا يُفترض أن رقم commit وحده يعيد إنتاج artifacts الخاصة. ملفات المحرك الأصلية والعمل السابق لم تتغير. هذا الملف النهائي لا يدخل في حساب بصمته الذاتية.

## الملفات الثمانية والثلاثون في تثبيت المصدر

| المسار |
|---|
| `.gitignore` |
| `PS2_PROJECT_STATE.md` |
| `reports/RE4_ARCHITECTURE_DECISIONS.md` |
| `reports/RE4_ARCHITECTURE_DRAFT_PR.md` |
| `reports/RE4_ARCHITECTURE_ENGINEERING_AR.md` |
| `reports/RE4_ARCHITECTURE_GAMEPLAY_MATRIX.md` |
| `reports/RE4_PERFORMANCE_ROOT_CAUSES.md` |
| `reports/RE4_RADICAL_ARCHITECTURE_RESEARCH.md` |
| `tests/architecture_detail_state.inl` |
| `tests/architecture_vu_cost.inl` |
| `tests/test_architecture_ammo.py` |
| `tests/test_architecture_lab.py` |
| `tests/test_architecture_timeline.py` |
| `tools/architecture_ammo.py` |
| `tools/architecture_audio_evidence.py` |
| `tools/architecture_benchmark.py` |
| `tools/architecture_build_aot.py` |
| `tools/architecture_build_detail.py` |
| `tools/architecture_build_input.py` |
| `tools/architecture_collect_vu_cost.py` |
| `tools/architecture_cost_model.py` |
| `tools/architecture_finalize.py` |
| `tools/architecture_freeze.py` |
| `tools/architecture_fuzz.py` |
| `tools/architecture_gates.py` |
| `tools/architecture_ghidra.py` |
| `tools/architecture_host_code.py` |
| `tools/architecture_input_acceptance.py` |
| `tools/architecture_minimize.py` |
| `tools/architecture_prepare_cost_probe.py` |
| `tools/architecture_regression.py` |
| `tools/architecture_sample.py` |
| `tools/architecture_timeline.py` |
| `tools/architecture_tool_audit.py` |
| `tools/architecture_validate.py` |
| `tools/architecture_vu_codegen.py` |
| `tools/lab_regression.py` |
| `tools/run_lab.py` |

بقي التعديلان السابقان `tools/build_fusion.py` و`reports/NEXT_ENGINEERING_EXECUTION_AR.md` خارج هذا التثبيت. بقيت الملفات القديمة غير المتتبعة دون تغيير أو حذف. استُعملت هوية Codex من تثبيتات المختبر السابقة لكل عملية commit فقط، دون تعديل config أو بيانات اعتماد. لا push أو PR أو merge أو ترقية حزمة. هذا التقرير يُحفظ في تثبيت توثيقي تالٍ.
