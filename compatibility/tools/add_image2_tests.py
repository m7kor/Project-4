"""Extend existing semantic tests with IMAGE2 cases without replacing IMAGE coverage."""
from pathlib import Path
root=Path(__file__).resolve().parents[1]/'engines/project4/ps2xTest/src'
cases={
 'ps2_gs_tests.cpp':'GIF IMAGE packet writes host-to-local data into GS VRAM',
 'ps2_memory_tests.cpp':'VIF1 DIRECT finds an image continuation after packed setup',
 'ps2_vu1_tests.cpp':'XGKICK sends a VU memory GIF packet through PATH1',
}
for name,title in cases.items():
    p=root/name;text=p.read_text();marker='        tc.Run("'+title+'"'
    start=text.index(marker);end=text.index('\n        tc.Run(',start+len(marker))
    block=text[start:end];assert 'GIF_FMT_IMAGE' in block
    extra=block.replace(title,title+' [IMAGE2 regression]').replace('GIF_FMT_IMAGE','GIF_FMT_DISABLED')
    p.write_text(text[:end]+'\n'+extra+text[end:])
print('Added GS VRAM, VIF continuation, and wrapped XGKICK IMAGE2 regressions')
