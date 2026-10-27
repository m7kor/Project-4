"""Reuse the existing verified-generated fusion candidate, retaining the IMAGE2 correction."""
from pathlib import Path
import json,shutil,hashlib
ROOT=Path(__file__).resolve().parents[1]
source=Path('C:/Project/PS2redmption/tmp/diag/claude-vu1')
runtime=ROOT/'engines/project4/ps2xRuntime/src/lib/vu'
base=source/'tree-base/ps2xRuntime/src/lib/vu'
candidate=source/'tree/ps2xRuntime/src/lib/vu'
backup=ROOT/'artifacts/experiments/vu-fusion/integration-before'
backup.mkdir(exist_ok=False)
assert (ROOT/'engines/project4/ps2xRuntime/include/runtime/ps2_vu1.h').read_bytes()==(source/'tree/ps2xRuntime/include/runtime/ps2_vu1.h').read_bytes()
old=(runtime/'ps2_vu1_core.cpp').read_text()
normalized=old.replace('else if (format == 2u || format == 3u)','else if (format == 2u)')
assert normalized==(base/'ps2_vu1_core.cpp').read_text(), 'Candidate base differs beyond our known IMAGE2 predicate'
names=['ps2_vu1_core.cpp','ps2_vu1_step_body.inl','ps2_vu1_step_issue.inl','ps2_vu1_step_post.inl','generated/vu1_compiled_programs.inc']
for name in names:
    p=runtime/name;b=backup/name
    if p.exists():b.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,b)
    p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(candidate/name,p)
core=(runtime/'ps2_vu1_core.cpp').read_text()
assert core.count('else if (format == 2u)')==1
(runtime/'ps2_vu1_core.cpp').write_text(core.replace('else if (format == 2u)','else if (format == 2u || format == 3u)'))
shutil.copy2(source/'tree/tools/vu1_clean_blocks_codegen.py',ROOT/'tools/vu1_fusion_codegen.py')
result=dict(scope='Existing fused-scoreboard candidate plus IMAGE2; no arithmetic, headers, or guest runner edits',
            copied_files=names,generated_sha256=hashlib.sha256((runtime/'generated/vu1_compiled_programs.inc').read_bytes()).hexdigest(),
            generator= 'tools/vu1_fusion_codegen.py',fallback='PS2X_VU1_FUSED=0',status='experimental; requires integrated tests and real-game validation')
(ROOT/'artifacts/experiments/vu-fusion/integration.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
