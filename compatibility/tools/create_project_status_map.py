"""Create a native SVG evidence map; no completion percentage is inferred."""
from pathlib import Path
from html import escape
import json,hashlib
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'reports'
comparison=json.loads((ROOT/'artifacts/experiments/vu-shared-regions/game-comparison-summary.json').read_text())
palette={
    'verified':('#0ca30c','#f1fbf3','مثبت بنطاق'),
    'partial':('#e9a913','#fffaf0','جزئي'),
    'gap':('#d94b48','#fff3f2','فجوة'),
    'unknown':('#8b97a7','#f3f5f8','غير مثبت'),
    'experiment':('#3974d8','#eff5ff','تجربة')}
components=[
 ('EE / R5900','partial','إقلاع ولعب فعليان','قبول الحملة أوسع من الإقلاع'),
 ('MMI / FPU','partial','تنفيذ واختبارات قائمة','تغطية عتاد أوسع مطلوبة'),
 ('VU0','partial','مسارات واختبارات وحدة','حدود النقل والحواف تحتاج قبولًا'),
 ('VU1','gap','أكبر اختناق في العينة','نحو 74% شاملًا من خيط اللعبة'),
 ('VIF','partial','UNPACK وتكامل مع VU','حدود التجزئة والتوقيت مفتوحة'),
 ('GIF / IMAGE2','verified','تصحيح مثبت في خمسة مسارات','هذا ليس قبول GIF كله'),
 ('GS / Textures','partial','عالم وشخصية وواجهة ظاهرة','مزامنة GPU ومشاهد أوسع'),
 ('DMAC / SPR','partial','نقل وسلاسل DMA عاملة','اختبارات الحواف والتداخل'),
 ('IOP / SIF','partial','وحدات وتحكم وصوت فعلي','قبول أوسع عبر الانتقالات'),
 ('IPU / Video','partial','مقاطع ومسار فك قائم','تخطي وتزامن عبر مشاهد أكثر'),
 ('SPU2 / Audio','gap','مسار الصوت موجود ويعمل','نقص عينات؛ القبول السمعي ناقص'),
 ('Streaming','partial','أصول أصلية للقراءة فقط','عبور الغرف وتحميل الاعتماديات'),
 ('Controllers','partial','يد فعلية وإدخال مرصود','تأخر الشاشة وأجهزة أوسع'),
 ('Memory Cards','verified','حفظ ثم تحميل فعليان','الخانة 01 ضمن الفصل 1-1'),
 ('Timing','partial','عداد ضيف وتوقيت مقترن','pacing وتزامن أشمل مطلوبان')]
stages=[
 ('الإقلاع','verified','مثبت: الملف التنفيذي الصحيح'),
 ('القائمة الرئيسية','verified','مثبت: صور ومدخلات فعلية'),
 ('بدء اللعبة','partial','جزئي: مسار البداية غير موثق كاملًا'),
 ('المقدمة السينمائية','partial','جزئي: ظهرت مقاطع وتُخطي بعضها'),
 ('اتصال Hunnigan','verified','مثبت: اتصال ما بعد المنزل'),
 ('الغابة','verified','مثبت: عالم وشخصية وواجهة'),
 ('حركة الشخصية','verified','مثبت: يد فعلية وقراءات موضع'),
 ('التصويب وإطلاق النار','verified','مثبت: ذخيرة وإصابة وظرف طلقة'),
 ('انتقال غرفة مستقلة','verified','مثبت: 0x100 → 0x101 بيد المستخدم'),
 ('تفاعل الأعداء','verified','مثبت ضمن المواجهات المرصودة'),
 ('الحفظ ثم التحميل','verified','مثبت: نجاح ثم استعادة في تشغيل آخر')]
data={'as_of':'2026-10-24','game':'Resident Evil 4 USA','serial':'SLUS-211.34',
    'accepted_runner_sha256':'e17998c7099f3bff2892529d7726836d9689b9af1d6cd091bfa5b29c9a88542a',
    'completion_percentage':None,'reference_svg_serial':'SCUS_973.99',
    'median_scene_speed':comparison['median_shared_speed'],
    'median_scene_improvement_percent':comparison['median_speed_increase_percent'],
    'cpp_unit_passed':633,'python_cases':403,'python_skipped':7,
    'components':[dict(zip(('name','status','evidence','gap'),row)) for row in components],
    'stages':[{'number':i+1,'name':r[0],'status':r[1],'scope':r[2]} for i,r in enumerate(stages)],
    'limits':['One stationary scene for speed claim','Hardware reference has eight mismatches','Flag coalescing passed correctness but was rejected after seven slower benchmark pairs','Combat evidence and latest optimized-run evidence have different scopes']}
(out/'RE4_STATUS_MAP.data.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
parts=['''<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="1500" viewBox="0 0 1440 1500" role="img" aria-labelledby="title desc">
<title id="title">حالة RE4 × Zmbor — الأدلة والنواقص</title>
<desc id="desc">خريطة مكونات ومراحل لعبة Resident Evil 4 SLUS-211.34. الألوان تمثل نطاق الدليل، لا نسبة اكتمال. تحسن مشهد الحفظ 48.8 بالمئة، وسرعة الضيف نحو0.215 من الزمن الحقيقي. انتقال غرفة مستقلة وقبول الصوت والحملة كاملة غير مثبتة.</desc>
<style>text{font-family:'Segoe UI',Tahoma,Arial,sans-serif} .rtl{direction:rtl;unicode-bidi:plaintext} .ltr{direction:ltr;unicode-bidi:embed} </style>
<rect width="1440" height="1500" fill="#f5f7fb"/>
''']
def rect(x,y,w,h,fill,rx=8,stroke=None):
    parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"'+(f' stroke="{stroke}"' if stroke else '')+'/>')
def text(x,y,value,size=22,color='#182536',weight=400,rtl=True,anchor='start'):
    parts.append(f'<text x="{x}" y="{y}" class="{"rtl" if rtl else "ltr"}" text-anchor="{anchor}" font-size="{size}" font-weight="{weight}" fill="{color}">{escape(str(value))}</text>')
def line(x1,y1,x2,y2,color='#d9e0e8'):
    parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}"/>')
text(1400,66,'RE4 × Zmbor — خريطة الحالة والنواقص',42,weight=700)
rect(40,32,390,42,'#e9edf4',6)
text(58,60,'SLUS-211.34  |  24 OCT 2026',22,weight=600,rtl=False)
text(1400,110,'نسخة تعمل داخل اللعب، لكنها لم تحقق بعد قبول الحملة والسرعة الطبيعية والصوت كاملًا',25,color='#425269')
text(1400,149,'الألوان تصف ما اختُبر فعلًا — لا توجد نسبة اكتمال عامة موثوقة',23,color='#8b5c00',weight=600)
line(40,171,1400,171)
stats=[(960,'تحسن مشهد الحفظ','+48.8%','زوجان متناوبان • لا يعمم على الحملة','#0b7c48'),
       (500,'سرعة الضيف في المشهد','0.215×','السرعة الطبيعية: 1.0× • الفجوة باقية','#bb3634'),
       (40,'اختبارات C++ المكتملة','633 / 633','403 حالة Python؛ منها 7 متخطاة','#2451a3')]
for x,title,value,note,color in stats:
    rect(x,192,440,136,'#ffffff',10,'#d9e0e8')
    text(x+420,224,title,24,weight=600)
    text(x+22,277,value,47,color,700,False)
    text(x+420,309,note,20,color='#526176')
for x,key,label in [(1400,'verified','مثبت بنطاق محدد'),(1080,'partial','قبول جزئي'),(810,'gap','فجوة مثبتة'),(550,'unknown','غير مثبت'),(290,'experiment','تجربة غير مقبولة')]:
    parts.append(f'<circle cx="{x-9}" cy="363" r="8" fill="{palette[key][0]}"/>')
    text(x-29,370,label,21,color='#425269')
text(935,420,'مكونات المحرك',30,weight=700)
text(935,451,'كل مكوّن يحتاج قبولًا أوسع من نجاح مسار واحد',21,color='#526176')
text(1400,420,'تقدم اللعبة',30,weight=700)
text(1400,451,'الدليل مرتبط بالمشهد والنسخة المختبرة',21,color='#526176')
cw=(895-32)/3
for i,(name,status,scope,gap) in enumerate(components):
    col=2-i%3;row=i//3;x=40+col*(cw+16);y=470+row*132
    color,tint,label=palette[status]
    parts.append(f'<g><title>{escape(name+" — "+label+": "+scope+". "+gap)}</title>')
    rect(round(x,2),y,round(cw,2),116,tint,8,'#d9e0e8')
    rect(round(x+cw-6,2),y+8,6,100,color,2)
    text(x+16,y+34,name,25,weight=650,rtl=False)
    text(x+cw-17,y+32,label,17,color,600)
    text(x+cw-17,y+70,scope,20.5,weight=500)
    text(x+cw-17,y+99,gap,19.5,color='#526176')
    parts.append('</g>')
rect(970,470,430,644,'#ffffff',8,'#d9e0e8')
for i,(name,status,scope) in enumerate(stages):
    y=476+i*54;color=palette[status][0]
    if i:line(988,y-2,1382,y-2,'#e8edf3')
    parts.append(f'<g><title>{escape(str(i+1)+": "+name+" — "+scope)}</title><circle cx="1373" cy="{y+23}" r="16" fill="{color}"/></g>')
    text(1373,y+29,i+1,17,'#ffffff',700,False,'middle')
    text(1343,y+21,name,23,weight=600)
    text(1343,y+44,scope,17.5,color='#526176')
text(1384,1095,'المرحلة 11 لا تغلق فجوة المرحلة 9',19,color='#8b5c00',weight=600)
line(40,1143,1400,1143)
text(1400,1181,'ما الذي يحتاجه المشروع أولًا؟',30,weight=700)
priorities=[(960,'P0 — تقدم اللعب',['عبور غرفة مستقلة ومتابعة اللعب','إعادة القتال على النسخة الأحدث','تتبع البث والوحدات والحفظ']),
            (500,'P0 — السرعة الطبيعية',['VU هو أكبر اختناق مقاس','التقاعد والأعلام والحساب الدقيق','قياس متكرر قبل قبول أي تحسين']),
            (40,'P1 — الصوت والقبول',['نقص العينات والتزامن السمعي','توقيت الإطارات وتغطية العتاد','الحملة الكاملة ما زالت غير مثبتة'])]
for x,title,notes in priorities:
    rect(x,1203,440,151,'#ffffff',8,'#d9e0e8')
    text(x+420,1239,title,25,weight=650)
    for i,note in enumerate(notes):text(x+420,1274+i*29,note,21,color='#425269')
rect(40,1372,1360,70,'#edf4ff',8,'#c5d8f8')
text(1380,1400,'تجربة جمع الأعلام رُفضت: اجتازت الصحة، لكنها أبطأ في الأزواج السبعة (وسيط 0.73%)',23,color='#2451a3',weight=600)
text(1380,1427,'مرشح تخصيص الخانات رُفض: أبطأ 0.93% رغم اجتياز الصحة. النسخة المقبولة بقيت محفوظة.',20,color='#425269')
text(1400,1479,'الخريطة تخص RE4؛ المرجع المرفق يخص SCUS_973.99. الأخضر ليس شهادة باكتمال المكوّن.',20,color='#526176')
text(40,1479,'Accepted build: e17998c7',17,color='#526176',rtl=False)
parts.append('</svg>')
svg='\n'.join(parts)
(out/'RE4_STATUS_MAP.svg').write_text(svg,encoding='utf-8')
print(json.dumps({'svg':'reports/RE4_STATUS_MAP.svg','bytes':len(svg.encode()),'components':len(components),'stages':len(stages),'data_sha256':hashlib.sha256((out/'RE4_STATUS_MAP.data.json').read_bytes()).hexdigest()}))
