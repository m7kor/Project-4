"""Original RE4 diagram matching the requested GitHub treemap visual style.

Cells are decorative service group tiles, never invented SDK function counts.
"""
from pathlib import Path
from html import escape
import sys
import json
import re

ROOT = Path(__file__).resolve().parents[1]
TARGET = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / 'lab/github-publication-20261027'
OUT = TARGET / 'docs/status/progress.svg'


def main():
    configuration = json.loads((TARGET / "docs/status/map.json").read_text(encoding="utf-8"))
    s = ['<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="510" viewBox="0 0 1000 510" role="img" aria-labelledby="title desc">',
         '<title id="title">RE4 status: scoped library services and PS2 hardware</title>',
         '<desc id="desc">GitHub dark treemap. Green means working in verified scope, yellow hatched means partial, gray means pending. SDK function percentages have not been measured. Independent hardware reference47 of55 is separate from candidate validation.</desc>',
         '<style>text{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif}.bg{fill:#0d1117}.line{stroke:#30363d}.t1{fill:#e6edf3}.t2{fill:#8b949e}.ok{fill:#0ca30c}.partial{fill:#fab219}.pending{fill:#484f58}.gap{stroke:#0d1117;stroke-width:1}.chip{fill:#1f2328;fill-opacity:.83}</style>',
         '<defs><pattern id="hatch" patternUnits="userSpaceOnUse" width="8" height="8"><path d="M-2 2L2 -2M0 8L8 0M6 10L10 6" stroke="#8a5a00" stroke-width=".7"/></pattern></defs>',
         '<rect class="bg" width="1000" height="510"/>',
         '<text class="t1" x="44" y="33" font-size="24">Status</text>',
         '<path class="line" d="M44 44H980"/>']

    def txt(x, y, text, size=12, cls='t1', anchor='start'):
        s.append(f'<text class="{cls}" x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}">{escape(text)}</text>')

    def badge(x, label, value):
        s.extend([f'<rect x="{x}" y="57" width="93" height="23" rx="3" fill="#30363d"/>',
                  f'<rect x="{x+92}" y="57" width="100" height="23" rx="3" fill="#fab219"/>'])
        txt(x+46,73,label,11,anchor='middle');s.append(f'<text x="{x+142}" y="73" font-size="11" text-anchor="middle" fill="#1f2328">{escape(value)}</text>')

    badge(44, 'libraries*', 'not measured')
    badge(244, 'hardware', 'partial')
    txt(44,105,'RE4 SDK / runtime services*: scoped evidence',13)
    txt(530,105,'PS2 hardware: implemented, partly validated',13)

    def tile(x,y,w,h,label,status,detail,grid=False,vertical=False):
        s.append(f'<g id="component-{re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")}"><title>{escape(label+": "+detail)}</title>')
        s.append(f'<rect class="{status} gap" x="{x}" y="{y}" width="{w}" height="{h}"/>')
        if status=='partial':s.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="url(#hatch)"/>')
        if grid:
            for px in range(x+13,x+w,13):s.append(f'<path d="M{px} {y}V{y+h}" stroke="#0d1117" stroke-width=".8"/>')
            for py in range(y+13,y+h,13):s.append(f'<path d="M{x} {py}H{x+w}" stroke="#0d1117" stroke-width=".8"/>')
            s.append(f'<rect class="chip" x="{x+2}" y="{y+2}" width="{min(w-4,max(32,len(label)*6+8))}" height="16"/>')
            txt(x+6,y+14,label,10)
        else:
            color='#fff' if status=='ok' else '#1f2328' if status=='partial' else '#e6edf3'
            transform=f' transform="rotate(-90 {x+w/2} {y+h/2})"' if vertical else ''
            s.append(f'<text x="{x+w/2}" y="{y+h/2}" font-size="11" text-anchor="middle" dominant-baseline="central" fill="{color}"{transform}>{escape(label)}</text>')
        s.append('</g>')

    # Library grouping and area are a diagram layout, not audited function counts.
    for row in configuration['libraries']:
        tile(*row,grid=True)

    # Closely follows the reference's component treemap arrangement.
    x=530
    for row in configuration['hardware']:
        tile(*row,vertical=row[4]=='Timer')
    for bx,name in [(530,'IOP'),(695,'EE'),(853,'GS / VU')]:
        s.append(f'<rect class="chip" x="{bx+2}" y="120" width="{55 if name=="GS / VU" else 28}" height="16"/>');txt(bx+6,132,name,10)
    for bx,label,status in [(44,'Working (verified scope)','ok'),(245,'Partial','partial'),(355,'Pending','pending')]:
        s.append(f'<rect class="{status}" x="{bx}" y="421" width="13" height="13" rx="2"/>')
        if status=='partial':s.append(f'<rect x="{bx}" y="421" width="13" height="13" fill="url(#hatch)"/>')
        txt(bx+20,432,label,12,'t2')
    txt(530,432,'Gameplay: room100 →101 | scene0.2155x | paired gain+4.94%',11,'t2')
    txt(44,457,'* Library cells are decorative service groups, not counted SDK functions. Areas do not measure overall completion.',11,'t2')
    txt(44,477,'Separate hardware reference:47/55 exact on Zmbor00173a2; not candidate hardware acceptance. Full campaign and quicksave pending.',11,'t2')
    txt(44,497,'RE4 USA SLUS-211.34 | 27 Oct2026 | Evidence and limits: docs/status/README.md',11,'t2')
    s.append('</svg>')
    result = '\n'.join(s)
    for key, original in {'background':'#0d1117', 'working':'#0ca30c', 'partial':'#fab219', 'pending':'#484f58'}.items():
        color = configuration['palette'][key]
        assert re.fullmatch(r'#[0-9a-fA-F]{6}', color)
        result = result.replace(original, color)
    OUT.write_text(result, encoding='utf-8', newline='\n')
    print('GitHub dark green/yellow/gray treemap written; no invented function percentages.')


if __name__=='__main__':
    main()
