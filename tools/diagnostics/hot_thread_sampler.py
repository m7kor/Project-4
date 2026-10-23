"""Sampling profiler for a running ps2EntryRunner (Windows, no extra tools).

Finds the busiest thread (or --tid), then repeatedly suspends it, reads RIP
with GetThreadContext and resumes it. Samples are symbolized with DbgHelp
against the runner's PDB, so both runtime functions and recompiled game
functions show up by name.

    python -I tools/diagnostics/hot_thread_sampler.py [--seconds 10] [--rate 1000] [--tid N]
"""
import argparse
import collections
import ctypes
import ctypes.wintypes as wt
import time
from pathlib import Path

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
dbghelp = ctypes.WinDLL('dbghelp', use_last_error=True)
ntdll = ctypes.WinDLL('ntdll')

PROCESS_ACCESS = 0x0400 | 0x0010  # query information and VM read, no memory writes
THREAD_ACCESS = 0x0002 | 0x0008 | 0x0010 | 0x0040  # suspend/resume, get context, query
CONTEXT_CONTROL = 0x00100001
CONTEXT_FULL = 0x0010000B
TH32CS_SNAPPROCESS, TH32CS_SNAPTHREAD = 0x2, 0x4


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [('dwSize', wt.DWORD), ('cntUsage', wt.DWORD), ('th32ProcessID', wt.DWORD),
                ('th32DefaultHeapID', ctypes.c_void_p), ('th32ModuleID', wt.DWORD), ('cntThreads', wt.DWORD),
                ('th32ParentProcessID', wt.DWORD), ('pcPriClassBase', ctypes.c_long), ('dwFlags', wt.DWORD),
                ('szExeFile', ctypes.c_wchar * 260)]


class THREADENTRY32(ctypes.Structure):
    _fields_ = [('dwSize', wt.DWORD), ('cntUsage', wt.DWORD), ('th32ThreadID', wt.DWORD),
                ('th32OwnerProcessID', wt.DWORD), ('tpBasePri', ctypes.c_long), ('tpDeltaPri', ctypes.c_long),
                ('dwFlags', wt.DWORD)]


class SYMBOL_INFO(ctypes.Structure):
    _fields_ = [('SizeOfStruct', wt.ULONG), ('TypeIndex', wt.ULONG), ('Reserved', ctypes.c_uint64 * 2),
                ('Index', wt.ULONG), ('Size', wt.ULONG), ('ModBase', ctypes.c_uint64), ('Flags', wt.ULONG),
                ('Value', ctypes.c_uint64), ('Address', ctypes.c_uint64), ('Register', wt.ULONG),
                ('Scope', wt.ULONG), ('Tag', wt.ULONG), ('NameLen', wt.ULONG), ('MaxNameLen', wt.ULONG),
                ('Name', ctypes.c_char * 512)]


class FILETIME(ctypes.Structure):
    _fields_ = [('lo', wt.DWORD), ('hi', wt.DWORD)]


def find_process(name):
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    entry = PROCESSENTRY32W(dwSize=ctypes.sizeof(PROCESSENTRY32W))
    ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
    pid = None
    while ok:
        if entry.szExeFile.lower() == name.lower():
            pid = entry.th32ProcessID
        ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    kernel32.CloseHandle(snap)
    return pid


def threads_of(pid):
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    entry = THREADENTRY32(dwSize=ctypes.sizeof(THREADENTRY32))
    ok = kernel32.Thread32First(snap, ctypes.byref(entry))
    out = []
    while ok:
        if entry.th32OwnerProcessID == pid:
            out.append(entry.th32ThreadID)
        ok = kernel32.Thread32Next(snap, ctypes.byref(entry))
    kernel32.CloseHandle(snap)
    return out


def cpu_time(handle):
    times = [FILETIME() for _ in range(4)]
    kernel32.GetThreadTimes(handle, *[ctypes.byref(t) for t in times])
    return sum(((t.hi << 32) | t.lo) for t in times[2:])  # kernel + user, 100 ns


def thread_name(handle):
    name = ctypes.c_wchar_p()
    try:
        if kernel32.GetThreadDescription(handle, ctypes.byref(name)) >= 0 and name.value:
            return name.value
    except AttributeError:
        pass
    return ''


def busiest_thread(pid):
    handles = {}
    for tid in threads_of(pid):
        h = kernel32.OpenThread(THREAD_ACCESS, False, tid)
        if h:
            handles[tid] = h
    before = {tid: cpu_time(h) for tid, h in handles.items()}
    time.sleep(1.0)
    usage = sorted(((cpu_time(h) - before[tid]) / 1e5, tid) for tid, h in handles.items())[::-1]
    print('busiest threads (% of one core over 1 s):')
    for pct, tid in usage[:5]:
        print(f'  tid={tid:6d} {pct:5.1f}%  {thread_name(handles[tid])}')
    for h in handles.values():
        kernel32.CloseHandle(h)
    return usage[0][1]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--process', default='ps2EntryRunner.exe')
    parser.add_argument('--pid', type=int, help='sample exactly this process, without name selection')
    parser.add_argument('--expected-exe', type=Path, help='require this executable path for the opened process')
    parser.add_argument('--tid', type=int)
    parser.add_argument('--seconds', type=float, default=10.0)
    parser.add_argument('--rate', type=float, default=1000.0, help='samples per second')
    parser.add_argument('--top', type=int, default=40)
    parser.add_argument('--depth', type=int, default=16, help='stack frames per sample (0 = leaf only)')
    parser.add_argument('--callers-of', help='print the callers of functions whose name contains this')
    parser.add_argument('--lines', action='store_true', help='also rank the hottest source lines of the leaf samples (needs PDB)')
    args = parser.parse_args()

    pid = args.pid or find_process(args.process)
    if not pid:
        raise SystemExit(f'{args.process} is not running')
    process = kernel32.OpenProcess(PROCESS_ACCESS, False, pid)
    if not process:
        raise SystemExit(f'cannot open process (error {ctypes.get_last_error()})')
    if args.expected_exe:
        path = ctypes.create_unicode_buffer(32768)
        length = wt.DWORD(len(path))
        if not kernel32.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(length)):
            raise SystemExit(f'cannot verify process image (error {ctypes.get_last_error()})')
        if str(Path(path.value).resolve()).casefold() != str(args.expected_exe.resolve()).casefold():
            raise SystemExit('opened process does not match --expected-exe')
    if args.tid and args.tid not in threads_of(pid):
        raise SystemExit('requested thread does not belong to the selected process')
    tid = args.tid or busiest_thread(pid)
    thread = kernel32.OpenThread(THREAD_ACCESS, False, tid)
    if not thread:
        raise SystemExit(f'cannot open process/thread (error {ctypes.get_last_error()})')

    winmm = ctypes.WinDLL('winmm')
    winmm.timeBeginPeriod(1)
    dbghelp.SymSetOptions(0x2 | 0x4 | 0x10)  # undecorate, deferred loads, load line info
    dbghelp.SymInitializeW.argtypes = [wt.HANDLE, wt.LPCWSTR, wt.BOOL]
    dbghelp.SymInitializeW(process, None, True)
    dbghelp.SymFromAddr.argtypes = [wt.HANDLE, ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint64),
                                    ctypes.POINTER(SYMBOL_INFO)]
    dbghelp.SymFunctionTableAccess64.restype = ctypes.c_void_p
    dbghelp.SymFunctionTableAccess64.argtypes = [wt.HANDLE, ctypes.c_uint64]
    dbghelp.SymGetModuleBase64.restype = ctypes.c_uint64
    dbghelp.SymGetModuleBase64.argtypes = [wt.HANDLE, ctypes.c_uint64]
    dbghelp.StackWalk64.argtypes = [wt.DWORD, wt.HANDLE, wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    table_access = dbghelp.SymFunctionTableAccess64
    module_base = dbghelp.SymGetModuleBase64

    # 16-byte aligned x64 CONTEXT (1232 bytes): ContextFlags 0x30, Rsp 0x98, Rbp 0xA0, Rip 0xF8.
    raw = ctypes.create_string_buffer(1232 + 16)
    base = (ctypes.addressof(raw) + 15) & ~15
    frame = ctypes.create_string_buffer(1024)  # STACKFRAME64
    stacks = collections.Counter()
    deadline = time.perf_counter() + args.seconds
    period = 1.0 / args.rate
    taken = 0
    u64 = lambda address: ctypes.c_uint64.from_address(address)
    while time.perf_counter() < deadline:
        if kernel32.SuspendThread(thread) != 0xFFFFFFFF:
            try:
                ctypes.c_uint32.from_address(base + 0x30).value = CONTEXT_FULL
                if kernel32.GetThreadContext(thread, ctypes.c_void_p(base)):
                    pcs = [u64(base + 0xF8).value]
                    if args.depth:
                        ctypes.memset(frame, 0, 1024)
                        fa = ctypes.addressof(frame)
                        u64(fa).value = pcs[0]; ctypes.c_int.from_address(fa + 12).value = 3
                        u64(fa + 32).value = u64(base + 0xA0).value; ctypes.c_int.from_address(fa + 44).value = 3
                        u64(fa + 48).value = u64(base + 0x98).value; ctypes.c_int.from_address(fa + 60).value = 3
                        pcs = []
                        for _ in range(args.depth):
                            if not dbghelp.StackWalk64(0x8664, process, thread, fa, base, None,
                                                       ctypes.cast(table_access, ctypes.c_void_p),
                                                       ctypes.cast(module_base, ctypes.c_void_p), None):
                                break
                            pc = u64(fa).value
                            if not pc:
                                break
                            pcs.append(pc)
                    stacks[tuple(pcs)] += 1
                    taken += 1
            finally:
                # Never strand the game thread if a read or stack walk raises.
                kernel32.ResumeThread(thread)
        time.sleep(period)
    winmm.timeEndPeriod(1)

    names = {}

    def name_of(rip):
        if rip not in names:
            info = SYMBOL_INFO(SizeOfStruct=88, MaxNameLen=500)
            disp = ctypes.c_uint64()
            names[rip] = (info.Name.decode(errors='replace')
                          if dbghelp.SymFromAddr(process, rip, ctypes.byref(disp), ctypes.byref(info))
                          else f'?? {rip:#x}')
        return names[rip]

    class IMAGEHLP_LINE64(ctypes.Structure):
        _fields_ = [('SizeOfStruct', wt.DWORD), ('Key', ctypes.c_void_p), ('LineNumber', wt.DWORD),
                    ('FileName', ctypes.c_char_p), ('Address', ctypes.c_uint64)]

    dbghelp.SymGetLineFromAddr64.argtypes = [wt.HANDLE, ctypes.c_uint64, ctypes.POINTER(wt.DWORD),
                                             ctypes.POINTER(IMAGEHLP_LINE64)]
    line_names = {}

    def line_of(rip):
        if rip not in line_names:
            line = IMAGEHLP_LINE64(SizeOfStruct=ctypes.sizeof(IMAGEHLP_LINE64))
            disp = wt.DWORD()
            if dbghelp.SymGetLineFromAddr64(process, rip, ctypes.byref(disp), ctypes.byref(line)):
                path = line.FileName.decode(errors='replace').replace(chr(92), '/')
                line_names[rip] = f'{path.rsplit("/", 1)[-1]}:{line.LineNumber}'
            else:
                line_names[rip] = f'{name_of(rip)} (no line)'
        return line_names[rip]

    leaf = collections.Counter()
    leaf_lines = collections.Counter()
    inclusive = collections.Counter()
    callers = collections.Counter()
    for pcs, count in stacks.items():
        if not pcs:
            continue
        chain = [name_of(pc) for pc in pcs]
        leaf[chain[0]] += count
        if args.lines:
            leaf_lines[line_of(pcs[0])] += count
        for name in set(chain):
            inclusive[name] += count
        if args.callers_of:
            for i, name in enumerate(chain):
                if args.callers_of in name:
                    callers[' <- '.join(chain[i:i + 5])] += count
                    break
    print(f'tid={tid}: {taken} samples in {args.seconds:.0f} s')
    print('--- self time')
    for name, count in leaf.most_common(args.top):
        print(f'{100.0 * count / max(taken, 1):6.2f}%  {count:6d}  {name}')
    if args.depth:
        print('--- inclusive time')
        for name, count in inclusive.most_common(args.top):
            print(f'{100.0 * count / max(taken, 1):6.2f}%  {count:6d}  {name}')
    if leaf_lines:
        print('--- hottest source lines (leaf)')
        for name, count in leaf_lines.most_common(args.top):
            print(f'{100.0 * count / max(taken, 1):6.2f}%  {count:6d}  {name}')
    if callers:
        print(f'--- call chains through "{args.callers_of}"')
        for chain, count in callers.most_common(15):
            print(f'{100.0 * count / max(taken, 1):6.2f}%  {chain}')


if __name__ == '__main__':
    main()
