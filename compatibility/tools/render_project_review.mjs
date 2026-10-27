import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import fs from 'node:fs/promises';
import path from 'node:path';
const require=createRequire(import.meta.url);
const sharp=require('sharp');
const {marked}=await import(pathToFileURL(require.resolve('marked')).href);
const root='D:/Project/compatbilty';
const dir=path.join(root,'reports');
const svg=await fs.readFile(path.join(dir,'RE4_STATUS_MAP.svg'));
await sharp(svg,{density:96}).resize({width:1440}).png().toFile(path.join(dir,'RE4_STATUS_MAP.png'));
let body=marked.parse(await fs.readFile(path.join(dir,'RE4_PROJECT_REVIEW_AR.md'),'utf8'));
const end=body.indexOf('</h1>')+5;
body=body.slice(0,end)+`
<figure><a href="RE4_STATUS_MAP.svg"><img src="RE4_STATUS_MAP.svg" alt="خريطة مكونات RE4 ونواقص الأداء والصوت والتقدم، مع نطاقات الأدلة" /></a>
<figcaption><a href="RE4_STATUS_MAP.svg" download>تنزيل خريطة SVG</a> · <a href="RE4_STATUS_MAP.png" download>نسخة PNG</a> · <a href="RE4_PROJECT_REVIEW_AR.md" download>نسخة التقرير النصية</a></figcaption></figure>
`+body.slice(end);
const html=`<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>تقرير تطوير RE4 × Zmbor</title>
<style>
*{box-sizing:border-box}html{background:#f3f6fa;color:#1d2a3a;font:18px/1.95 'Segoe UI',Tahoma,Arial,sans-serif}
body{margin:0}main{max-width:1180px;margin:36px auto;padding:40px 52px;background:white;border:1px solid #dce3eb;border-radius:12px}
h1{font-size:34px;line-height:1.6;margin:0 0 22px;color:#123e50}h2{font-size:26px;line-height:1.6;margin:46px 0 16px;padding-bottom:9px;border-bottom:2px solid #dbe8ed;color:#123e50}h3{font-size:21px;margin:28px 0 12px;color:#215c70}
p{margin:14px 0}strong{color:#11384d}a{color:#195f91;text-decoration-thickness:1px;text-underline-offset:4px}figure{margin:28px 0 38px;padding:0}figure img{display:block;width:100%;height:auto;border:1px solid #dce3eb;border-radius:8px}figcaption{font-size:15px;text-align:center;padding:9px}
table{border-collapse:collapse;width:100%;font-size:16px;line-height:1.8;margin:22px 0;table-layout:fixed}th,td{border:1px solid #dce3eb;padding:12px 14px;vertical-align:top;text-align:right;overflow-wrap:anywhere}th{background:#edf4f8;color:#173e50;font-weight:700}tbody tr:nth-child(even){background:#f8fafc}
li{margin:8px 0;padding-right:4px}ul,ol{padding-right:26px}code{font:14px/1.7 Consolas,monospace;direction:ltr;unicode-bidi:embed;background:#eef2f6;border-radius:4px;padding:2px 5px;overflow-wrap:anywhere}hr{border:0;border-top:1px solid #dce3eb}
@media(max-width:720px){main{margin:0;padding:24px 16px;border:0;border-radius:0}html{font-size:16px}h1{font-size:27px}h2{font-size:23px}table{font-size:13px}th,td{padding:8px 6px}code{font-size:12px}}
@media print{html{background:white;font-size:12pt}main{max-width:none;border:0;margin:0;padding:0}a{color:inherit;text-decoration:none}h2,h3{break-after:avoid}tr,figure{break-inside:avoid}figcaption{display:none}table{font-size:10pt}figure img{max-height:225mm;object-fit:contain;border:0}code{font-size:9pt}}
</style></head><body><main>${body}</main></body></html>`;
await fs.writeFile(path.join(dir,'RE4_PROJECT_REVIEW_AR.html'),html,'utf8');
console.log(JSON.stringify({png:'reports/RE4_STATUS_MAP.png',html:'reports/RE4_PROJECT_REVIEW_AR.html',svgBytes:svg.length,htmlBytes:Buffer.byteLength(html)}));
