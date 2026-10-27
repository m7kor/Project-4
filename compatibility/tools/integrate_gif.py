"""Apply the five upstream IMAGE2 corrections to the isolated working snapshot."""
from pathlib import Path
import shutil, json, hashlib
root=Path(__file__).resolve().parents[1]
runtime=root/'engines/project4/ps2xRuntime/src/lib'
edits={
 'gs/ps2_gif_arbiter.cpp':('return flg == 2u;','return flg == 2u || flg == 3u; // IMAGE2 shares IMAGE transfer and arbitration rules.'),
 'gs/gs_frontend.cpp':('else if (flg == GIF_FMT_IMAGE)','else if (flg == GIF_FMT_IMAGE || flg == GIF_FMT_DISABLED)'),
 'Kernel/Stubs/GS.cpp':('if (flag != 2u)','if (flag < 2u) // IMAGE and IMAGE2 count qwords directly.'),
 'ps2_vif1_interpreter.cpp':('else if (flg == kGifFmtImage)','else if (flg == kGifFmtImage || flg == 3u)'),
 'vu/ps2_vu1_core.cpp':('else if (format == 2u)','else if (format == 2u || format == 3u)'),
}
backup=root/'artifacts/gif-before';backup.mkdir(exist_ok=False)
for name,(old,new) in edits.items():
    p=runtime/name;data=p.read_text();assert data.count(old)==1,(name,data.count(old))
    b=backup/name;b.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,b)
    p.write_text(data.replace(old,new))
(root/'artifacts/gif-integration.json').write_text(json.dumps({'source_commit':'e5636981a1c9de368f6b71e819c3dc188dfedbf4',
    'scope':'FLG3 packet sizing, transport and arbitration only; no VU arithmetic or scheduling changes',
    'files':list(edits),'reference':'ps2tek GIFtag bits 58-59: 2=IMAGE 3=IMAGE; DIRECTHL IMAGE barrier'},indent=2))
print('Applied five narrow IMAGE2 condition changes; no headers or generated sources edited')
