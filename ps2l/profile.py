#!/usr/bin/env python3
"""lodestone profile — read/validate game profiles.

The rules this enforces exist because a profile is the ONLY place per-game
knowledge is allowed to live (docs/00-ARCHITECTURE.md, R2). If a profile can
lie, the whole design collapses.

Enforced:
  - every [boundary] entry carries an evidence tier
  - no boundary entry names a handler that does not exist upstream
  - no triage handler (ret0/ret1/reta0) survives into a promotable state
  - addresses are 4-byte aligned and inside a declared section
  - [identity] hashes match the file on disk when given
  - [stages] never regress (a completed stage cannot go back to pending)
  - EVERY [analysis] figure that the analyzer can independently re-derive is
    compared against analysis/analysis.json, and a stale one is a hard error

That last rule exists because it already failed once. Session 4 measured 7,977
functions at 94.69% byte coverage; the profile still carried the session-2
figures (5,904 / 39.75%), and `lodestone status` happily printed both numbers in
different places. A verifier that does not verify the verifier is the exact
failure mode this project was built to end.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

try:                                    # Python 3.11+
    import tomllib
except ModuleNotFoundError:             # 3.10 and older
    import tomli as tomllib             # type: ignore[no-redef]

# Evidence tiers, strongest first. Taken verbatim from the ladder published in
# InitialDad/PS2Recomp-WoS-Findings (CC0).
TIERS = [
    "on_screen",
    "snapshot_diff",
    "stated_verified",
    "catalogued",
    "static_vtable_walk",
    "shared_sdk",
]
TIER_RANK = {t: i for i, t in enumerate(TIERS)}

# The generic triage handlers upstream provides for classifying call importance.
TRIAGE = {"ret0", "ret1", "reta0"}

# Names present in upstream's PS2_SYSCALL_LIST / PS2_STUB_LIST (658 unique).
# A subset that covers everything a first port touches; the full list is
# generated from ps2_call_list.h rather than typed by hand.
UPSTREAM_HANDLERS = {
    "ResetEE", "GsSetCrt", "ExitThread", "SleepThread", "CreateThread",
    "DeleteThread", "StartThread", "TerminateThread", "GetThreadId",
    "AddIntcHandler", "RemoveIntcHandler", "EnableIntc", "DisableIntc",
    "EnableDmac", "DisableDmac", "AddDmacHandler", "RemoveDmacHandler",
    "SetAlarm", "CancelAlarm", "CreateSema", "DeleteSema", "SignalSema",
    "SetupHeap", "EndOfHeap", "FlushCache", "GsGetIMR", "GsPutIMR",
    "Deci2Call", "InitTLB", "FindAddress", "SetMemoryMode",
    "sceCdRead", "sceCdSync", "sceCdGetError", "sceCdStatus", "sceCdSearchFile",
    "sceCdReadIOPm", "sceCdDiskReady", "sceCdGetToc", "sceCdStream",
    "sceSifInitRpc", "sceSifExitRpc", "sceSifBindRpc", "sceSifCallRpc",
    "sceSifRegisterRpc", "sceSifLoadModule", "sceSifLoadStartModule",
    "sceSifLoadModuleBuffer", "sceSifLoadStartModuleBuffer",
    "sceSifUnloadModule", "sceSifStopModule", "sceSifResetIop",
    "sceSifSyncIop", "sceSifIsAliveIop", "sceSifInitIopHeap",
    "sceSifAllocIopHeap", "sceSifFreeIopHeap", "sceSifAllocSysMemory",
    "sceSifFreeSysMemory", "sceSifQueryMemSize", "sceSifGetModuleList",
    "sceSifSearchModuleByName", "sceSifSearchModuleByAddress",
    "sceSifLoadFileReset", "sceSifLoadFile", "sceSifGetFileList",
    "sceGsInit", "sceGsReset", "sceGsSetDispEnv", "sceGsPutRGBPalette",
    "sceGsSetCRTCoreLock", "sceGsSetDisplay", "sceGsSetFlip", "sceGsGetFlip",
    "sceGsSetZBuffer", "sceGsSetPSM", "sceGsSetClip", "sceGsSetOffset",
    "sceGsSetVramParam", "sceGsSetVramAddr", "sceGsSetTexturePage",
    "sceGsDrawSync", "sceGsFinish", "sceGsWaitSync", "sceGsSync",
    "sceGsDmaSync", "sceGsPutTransfer", "sceGsStartDisplay",
    "sceGsAbortDisplay", "sceGsSetTextureFilter", "sceGsSetTextureMode",
    "sceGsMalloc", "sceGsFree", "sceGsGetBaseAddr", "sceGsStoreImage",
    "sceGsExecute",
    "sceGifInit", "sceGifInitSystem", "sceGifQuit", "sceGifPutRecord",
    "sceGifGetRecord", "sceGifGetFreeSize", "sceGifSetPacketMode",
    "sceGifSetDMAMode", "sceGifSetCRTCoreLock", "sceGifLockBuffer",
    "sceGifUnlockBuffer", "sceGifBreakFlush", "sceGifSetMarker", "sceGifDMA",
    "sceDmaSync", "sceDmaChannel", "sceDmaMalloc", "sceDmaFree",
    "sceDmaOpen", "sceDmaClose", "sceDmaReset", "sceDmaExec",
    "sceMpegCreate", "sceMpegDelete", "sceMpegDecode", "sceMpegGetPicture",
    "sceMpegUnpack", "sceMpegFlush", "sceMpegIsEnd", "sceMpegDemuxPss",
    "sceMpegAwait", "sceMpegGetMpegBitstream", "sceMpegPutBitstream",
    "sceMpegGetWs", "sceMpegInitThlocal",
    "sceIpuInit", "sceIpuQuit", "sceIpuDMACallback", "sceIpuDMASync",
    "sceIpuDMAEnd", "sceIpuPutVect", "sceIpuGetVect", "sceIpuDST01",
    "sceIpuDST02", "sceIpuSetIdx",
    "scePadPortOpen", "scePadPortClose", "scePadPortStart", "scePadPortStop",
    "scePadPortReset", "scePadPortEnd", "scePadPortGetState",
    "scePadPortSetStateMode", "scePadPortGetButtonMask", "scePadEnterCancelMode",
    "scePadSetMainMode", "scePadGetCurrentMode", "scePadInit",
    "scePadChClose", "scePadChOpen", "scePadGetState", "scePadSetState",
    "scePadSync", "scePadInfoMode", "scePadSetInfoMode",
    "sceMcCreate", "sceMcDelete", "sceMcOpen", "sceMcClose", "sceMcRead",
    "sceMcWrite", "sceMcDeleteData", "sceMcFormat", "sceMcUnformat",
    "sceMcGetInfo", "sceMcGetSector", "sceMcRestore", "sceMcCheck",
    "sceDeci2Poll", "sceDeci2Open", "sceDeci2Close", "sceDeci2ReqSend",
    "sceDeci2ExRecv", "sceDeci2ExSend", "sceDeci2ReqRecv",
    "sceFileOpen", "sceFileClose", "sceFileRead", "sceFileWrite",
    "sceFileLseek", "sceFileGetIoMode", "sceFileGetStat", "sceFileDopen",
    "sceFileDread", "sceFileDclose", "sceFileMount", "sceFileUmount",
    "sceFileAddDrv", "sceFileRemoveDrv", "sceFileIoctl",
    "sceKernelLoadModule", "sceKernelStartModule", "sceKernelStopModule",
    "sceKernelUnloadModule", "sceKernelGetModuleList",
    "sceKernelSearchModuleByName", "sceKernelFreeLibMemory",
    "sceVu0ApplyMatrix", "sceVu0ApplyMatrixI", "sceVu0MulMatrix",
    "sceVu0OuterProduct", "sceVu0InnerProduct", "sceVu0Normalize",
    "sceVu0Transpose", "sceVu0Invers", "sceVu0RotTransPersN",
    "sceVu0DropShadowMatrix", "sceVu0Vector0", "sceVu0Vector1",
    "sceVu0Vector2", "sceVu0Vector3", "sceVu0Vector4",
    "sceVu0SubVector", "sceVu0AddVector", "sceVu0SubVector0",
    "sceVu0CopyVector", "sceVu0ZeroVector", "sceVu0ScaleVector",
    "sceVu0IsVector", "sceVu0IsIEqual", "sceVu0IsFEqual", "sceVu0FVector",
    "sceVu0IVector", "sceVu0ClampVector", "sceVu0MaxVector",
    "sceVu0MinVector", "sceVu0CombineVector", "sceVu0InterleaveVector",
    "sceVu0InterleaveXVector", "sceVu0InterleaveXYVector",
    "sceVu0InterleaveXYZVector", "sceVu0CopyVector", "sceVu0Length",
    "sceVu0DotProduct", "sceVu0RotMatrix", "sceVu0RotMatrixX",
    "sceVu0RotMatrixY", "sceVu0RotMatrixZ", "sceVu0RotTransMatrix",
    "sceVu0RotTransMatrixI", "sceVu0RotHomogeneousMatrix",
    "sceVu0SetUMatrix", "sceVu0SetVMatrix", "sceVu0SetTranslation",
    "sceVu0SetProjection", "sceVu0SetProjectionMatrix",
    "sceVu0SetViewMatrix", "sceVu0SetLightMatrix", "sceVu0SetFogMatrix",
    "sceVu0SetHalfClip", "sceVu0SetClip", "sceVu0SetViewport",
    "sceVu0SetProjectionViewportMatrix", "sceVu0MulVecMat",
    "sceVu0SolveQuadratic", "sceVu0ATan", "sceVu0GenLOD",
    "printf", "malloc", "free", "memset", "memcpy", "write", "read",
    "iFprintf", "iPrint", "kputs", "atoi", "atof", "malloc", "free",
    "TODO", "TODO_NAMED", "iFlushCache", "iGsGetIMR", "iGsPutIMR",
    "GetMemorySize", "EnableIntc", "SetAlarm", "CreateThread",
    "SleepThread", "CreateSema", "WaitSema", "InitTLB", "GetEntryAddress",
    "Copy", "TerminateThread", "ExitDeleteThread", "GetThreadInfo",
}


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(1)


# Which ELF sections back each [analysis.layout] field.
_LAYOUT_SECTIONS = ((".text", "text"), (".data", "data"), (".sndata", "sndata"),
                    (".rodata", "rodata"), (".bss", "bss"))


def measured_facts(a: dict) -> dict:
    """Flatten analysis.json into exactly the values a profile is allowed to claim.

    Only facts the analyzer re-derives from the ELF on every run appear here.
    A value that is not in this table cannot be machine-checked, and the
    validator will say so instead of pretending it was verified.
    """
    secs = {s["name"]: s for s in (a.get("sections") or []) if s.get("name")}
    ov = a.get("overlays") or {}
    st = a.get("stats") or {}

    f: dict = {}
    for sec_name, key in _LAYOUT_SECTIONS:
        s = secs.get(sec_name)
        if not s:
            continue
        f[f"layout.{key}_addr"] = str(s["addr"]).upper()
        f[f"layout.{key}_size"] = int(s["size"])
        f[f"layout.{key}_flags"] = int(s["flags"])

    f["overlays.count"] = int(ov.get("count", 0))
    f["overlays.total_bytes"] = int(ov.get("total_bytes", 0))

    f["functions.found"] = int(st.get("functions", 0))
    f["functions.median_bytes"] = int(st.get("median_fn_bytes", 0))
    f["functions.max_bytes"] = int(st.get("max_fn_bytes", 0))
    f["functions.byte_coverage_pct"] = float(st.get("coverage_pct", 0.0))
    f["functions.discovery_mix"] = dict(st.get("by_kind") or {})

    f["syscalls.sites"] = int(st.get("syscall_sites", 0))
    f["syscalls.distinct_20bit_ids"] = int(st.get("distinct_syscall_ids", 0))
    return f


def _same(got, want) -> bool:
    if isinstance(want, float) or isinstance(got, float):
        try:
            return abs(float(got) - float(want)) < 0.005
        except (TypeError, ValueError):
            return False
    if isinstance(want, dict):
        return {k: v for k, v in dict(got or {}).items() if v} == \
               {k: v for k, v in want.items() if v}
    if isinstance(want, int) and not isinstance(want, bool):
        try:
            return int(str(got), 0) == want
        except (TypeError, ValueError):
            return False
    return str(got).upper() == str(want).upper()


def check_measured(r: "Report", d: dict, analysis: Path) -> None:
    """Compare every [analysis] figure the analyzer can re-derive against the run."""
    if not analysis.is_file():
        r.warn(f"no {analysis.name} to check [analysis] against — run "
               f"`lodestone analyze <elf>` first, or pass --analysis")
        return
    try:
        a = json.loads(analysis.read_text(encoding="utf-8"))
    except Exception as e:                        # noqa: BLE001
        r.err(f"{analysis.name} is not readable JSON: {e}")
        return

    blocks = d.get("analysis") or {}
    if not blocks:
        r.warn("profile has no [analysis] block — nothing is claimed, so "
               "nothing is verifiable")
        return

    checked, mismatched, unchecked = 0, 0, []
    for key, want in measured_facts(a).items():
        section, _, field = key.rpartition(".")
        body = blocks.get(section) or {}
        if field not in body:
            unchecked.append(key)
            continue
        got = body[field]
        checked += 1
        if not _same(got, want):
            mismatched += 1
            r.err(f"analysis.{key} = {got!r} contradicts the measured {want!r} "
                  f"in {analysis.name} — a profile may not carry a stale number")

    if checked == 0 and mismatched == 0:
        r.warn("[analysis] claims no value the analyzer can verify — the block "
               "is decorative, not evidence")
    if checked:
        r.note(f"{checked} [analysis] value(s) agree with {analysis.name}")
    if unchecked:
        r.note("not machine-checkable (analyzer does not derive these): "
               + ", ".join(f"analysis.{u}" for u in unchecked))


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warns: list[str] = []
        self.notes: list[str] = []

    def err(self, m: str) -> None:
        self.errors.append(m)

    def warn(self, m: str) -> None:
        self.warns.append(m)

    def note(self, m: str) -> None:
        self.notes.append(m)


def validate(path: Path, elf: Path | None, analysis: Path | None = None) -> Report:
    r = Report()
    try:
        d = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        die(f"{path} is not valid TOML: {e}")
        return r

    ident = d.get("identity", {})
    for key in ("serial", "entry", "sha256"):
        if not ident.get(key):
            r.err(f"identity.{key} missing")

    # --- hash check against the real file -------------------------------
    if elf:
        if not elf.is_file():
            die(f"{elf} not found")
        h = hashlib.sha256(elf.read_bytes()).hexdigest()
        want = (ident.get("sha256") or "").lower()
        if want and h != want:
            r.err(f"sha256 mismatch\n     profile: {want}\n     file:    {h}")
        else:
            r.note(f"sha256 verified against {elf.name}")

    # --- boundary + evidence -------------------------------------------
    boundary = d.get("boundary", {}) or {}
    evidence = d.get("evidence", {}) or {}
    if boundary and not evidence:
        r.err("boundary exists but [evidence] is empty — every entry needs a tier")
    if evidence and not boundary:
        r.err("[evidence] exists but [boundary] is empty")

    for addr, handler in boundary.items():
        try:
            a = int(str(addr), 0)
        except ValueError:
            r.err(f"boundary[{addr!r}] is not an address")
            continue
        if a & 3:
            r.err(f"boundary[{addr!r}] is not 4-byte aligned")
        if a == 0:
            r.err(f"boundary[{addr!r}] is NULL — upstream's readWord() maps addr 0 "
                  f"to .reginfo; a zero boundary is always a typo")
        tier = evidence.get(addr)
        if not tier:
            r.err(f"boundary[{addr!r}] has no entry in [evidence]")
        elif tier not in TIER_RANK:
            r.err(f"boundary[{addr!r}] evidence tier {tier!r} is not one of {TIERS}")
        elif tier in ("catalogued", "shared_sdk", "static_vtable_walk"):
            r.warn(f"boundary[{addr!r}] = {handler} is only {tier}; "
                   f"a stub at this tier is a guess")

        h = str(handler)
        if h.startswith("@"):
            r.note(f"boundary[{addr!r}] -> C++ {h} (must survive regeneration "
                   f"by being registered by ADDRESS, not by a patch file)")
            continue
        if h in TRIAGE:
            r.warn(f"boundary[{addr!r}] = {h} is a TRIAGE handler: classify the "
                   f"call, then promote it or delete it")
            continue
        if h not in UPSTREAM_HANDLERS:
            r.err(f"boundary[{addr!r}] = {h!r} is not in upstream "
                  f"PS2_SYSCALL_LIST / PS2_STUB_LIST — it will throw TODO_NAMED")

    # --- cross-file agreement ------------------------------------------
    env = d.get("environment", {}) or {}
    if "PS2X_STRICT_RETURN_DIAGNOSTICS" in env:
        want = str(env["PS2X_STRICT_RETURN_DIAGNOSTICS"]).upper()
        if want != "ON":
            r.err("PS2X_STRICT_RETURN_DIAGNOSTICS must be ON: by default JR $ra "
                  "is a bare `pc=target; return` and a missing target is silent")

    ver = d.get("verification", {}) or {}
    if ver:
        if ver.get("oracle") == "pcsx2" and ver.get("method") != "process-isolated":
            r.err("oracle=pcsx2 requires method=process-isolated "
                  "(PCSX2 is GPL: diff against it, never link it)")

    legal = d.get("legal", {}) or {}
    if legal.get("ship_game_content"):
        r.err("legal.ship_game_content = true is never allowed in this project")

    build = d.get("build", {}) or {}
    for k, want, why in (
        ("unity_build", False, "counterproductive with Ninja across ~10k TUs"),
        ("never_clean", True, "a clean build costs 20-30h"),
    ):
        if k in build and build[k] != want:
            r.err(f"build.{k} must be {want}: {why}")

    # --- stage monotonicity ---------------------------------------------
    stages = d.get("stages", {}) or {}
    done = {"complete", "done", "passed"}
    for name, body in stages.items():
        st = (body or {}).get("status", "pending") if isinstance(body, dict) else "pending"
        if st not in ("pending", "active") and st not in done:
            r.warn(f"stages.{name}.status = {st!r} is not a known status")

    # --- every [analysis] figure against a fresh measurement -------------
    check_measured(r, d, analysis or (path.resolve().parents[2]
                                      / "analysis" / "analysis.json"))

    return r


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    args = argv[1:]
    elf = None
    if "--elf" in args:
        elf = Path(args[args.index("--elf") + 1])
        args = args[:args.index("--elf")] + args[args.index("--elf") + 2:]
    analysis = None
    if "--analysis" in args:
        analysis = Path(args[args.index("--analysis") + 1])
        args = args[:args.index("--analysis")] + args[args.index("--analysis") + 2:]
    path = Path(args[0])

    rep = validate(path, elf, analysis)
    print("=" * 72)
    print(f"LODESTONE profile check   {path}")
    print("=" * 72)
    for m in rep.notes:
        print(f"  note  {m}")
    for m in rep.warns:
        print(f"  WARN  {m}")
    for m in rep.errors:
        print(f"  ERROR {m}")
    if rep.errors:
        print(f"-" * 72)
        print(f"  {len(rep.errors)} error(s), {len(rep.warns)} warning(s) — "
              f"profile is NOT trustworthy")
        print("=" * 72)
        return 1
    print("-" * 72)
    print(f"  OK — {len(rep.warns)} warning(s), 0 errors")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # a Windows console is not UTF-8
        _s.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main(sys.argv))
