"""Sampling host profiler for the native runner (Windows, no administrator rights).

Attaches to a running process, suspends each thread at a fixed interval,
walks its call stack, and resolves the frames to function names with
llvm-symbolizer and the runner's PDB (link with PS2X_RUNNER_PDB=ON).

    python -I tools/diagnostics/host_sampler.py --name ps2EntryRunner.exe --seconds 30 --out report.json

The report gives, per thread, how many samples were waiting in the kernel
and the hottest functions by self time and by inclusive time, plus the most
common stacks. Sampling suspends threads for microseconds at a time; it
changes timing slightly and never writes process memory.
"""
import argparse
import collections
import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import time

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
dbghelp = ctypes.WinDLL('dbghelp', use_last_error=True)
psapi = ctypes.WinDLL('psapi', use_last_error=True)

TH32CS_SNAPTHREAD = 0x4
TH32CS_SNAPPROCESS = 0x2
THREAD_ACCESS = 0x0002 | 0x0008 | 0x0040
PROCESS_ACCESS = 0x0400 | 0x0010
CONTEXT_FULL = 0x00100000 | 0x1 | 0x2 | 0x8
IMAGE_FILE_MACHINE_AMD64 = 0x8664
SYMBOLIZER = os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'), 'LLVM', 'bin',
                          'llvm-symbolizer.exe')


class THREADENTRY32(ctypes.Structure):
    _fields_ = [('dwSize', wt.DWORD), ('cntUsage', wt.DWORD), ('th32ThreadID', wt.DWORD),
                ('th32OwnerProcessID', wt.DWORD), ('tpBasePri', wt.LONG), ('tpDeltaPri', wt.LONG),
                ('dwFlags', wt.DWORD)]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [('dwSize', wt.DWORD), ('cntUsage', wt.DWORD), ('th32ProcessID', wt.DWORD),
                ('th32DefaultHeapID', ctypes.c_size_t), ('th32ModuleID', wt.DWORD),
                ('cntThreads', wt.DWORD), ('th32ParentProcessID', wt.DWORD),
                ('pcPriClassBase', wt.LONG), ('dwFlags', wt.DWORD), ('szExeFile', wt.WCHAR * 260)]


class ADDRESS64(ctypes.Structure):
    _fields_ = [('Offset', ctypes.c_ulonglong), ('Segment', wt.WORD), ('Mode', wt.DWORD)]


class KDHELP64(ctypes.Structure):
    _fields_ = [('raw', ctypes.c_ulonglong * 24)]


class STACKFRAME64(ctypes.Structure):
    _fields_ = [('AddrPC', ADDRESS64), ('AddrReturn', ADDRESS64), ('AddrFrame', ADDRESS64),
                ('AddrStack', ADDRESS64), ('AddrBStore', ADDRESS64), ('FuncTableEntry', ctypes.c_void_p),
                ('Params', ctypes.c_ulonglong * 4), ('Far', wt.BOOL), ('Virtual', wt.BOOL),
                ('Reserved', ctypes.c_ulonglong * 3), ('KdHelp', KDHELP64)]


class MODULEINFO(ctypes.Structure):
    _fields_ = [('lpBaseOfDll', ctypes.c_void_p), ('SizeOfImage', wt.DWORD), ('EntryPoint', ctypes.c_void_p)]


kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
kernel32.OpenThread.restype = wt.HANDLE
kernel32.OpenProcess.restype = wt.HANDLE
FUNCTION_TABLE_ACCESS = ctypes.WINFUNCTYPE(ctypes.c_void_p, wt.HANDLE, ctypes.c_ulonglong)
GET_MODULE_BASE = ctypes.WINFUNCTYPE(ctypes.c_ulonglong, wt.HANDLE, ctypes.c_ulonglong)
dbghelp.SymFunctionTableAccess64.restype = ctypes.c_void_p
dbghelp.SymFunctionTableAccess64.argtypes = [wt.HANDLE, ctypes.c_ulonglong]
dbghelp.SymGetModuleBase64.restype = ctypes.c_ulonglong
dbghelp.SymGetModuleBase64.argtypes = [wt.HANDLE, ctypes.c_ulonglong]
dbghelp.StackWalk64.argtypes = [wt.DWORD, wt.HANDLE, wt.HANDLE, ctypes.POINTER(STACKFRAME64), ctypes.c_void_p,
                                ctypes.c_void_p, FUNCTION_TABLE_ACCESS, GET_MODULE_BASE, ctypes.c_void_p]


def find_pid(name):
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
    found = None
    while ok:
        if entry.szExeFile.lower() == name.lower():
            found = entry.th32ProcessID
        ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    kernel32.CloseHandle(snap)
    return found


def thread_ids(pid):
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    entry = THREADENTRY32()
    entry.dwSize = ctypes.sizeof(entry)
    ids = []
    ok = kernel32.Thread32First(snap, ctypes.byref(entry))
    while ok:
        if entry.th32OwnerProcessID == pid:
            ids.append(entry.th32ThreadID)
        ok = kernel32.Thread32Next(snap, ctypes.byref(entry))
    kernel32.CloseHandle(snap)
    return ids


def list_modules(process):
    handles = (ctypes.c_void_p * 1024)()
    needed = wt.DWORD()
    psapi.EnumProcessModulesEx(process, handles, ctypes.sizeof(handles), ctypes.byref(needed), 3)
    result = []
    for i in range(needed.value // ctypes.sizeof(ctypes.c_void_p)):
        name = ctypes.create_unicode_buffer(1024)
        psapi.GetModuleFileNameExW(process, ctypes.c_void_p(handles[i]), name, 1024)
        info = MODULEINFO()
        psapi.GetModuleInformation(process, ctypes.c_void_p(handles[i]), ctypes.byref(info), ctypes.sizeof(info))
        result.append((name.value, info.lpBaseOfDll or 0, info.SizeOfImage))
    return result


def symbolize(path, base, addresses):
    fallback = [f'+0x{a - base:x}' for a in addresses]
    if not os.path.exists(SYMBOLIZER) or not addresses:
        return fallback
    lines = ''.join(f'0x{a - base:x}\n' for a in addresses)
    try:
        out = subprocess.run([SYMBOLIZER, '--obj', path, '--relative-address', '--functions=linkage',
                              '--no-inlines', '--output-style=GNU', '--demangle'],
                             input=lines, capture_output=True, text=True, timeout=1200).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return fallback
    names = out[0::2]
    if len(names) != len(addresses):
        return fallback
    return [n if n and n != '??' else f for n, f in zip(names, fallback)]


def short(name, limit=110):
    return name if len(name) <= limit else name[:limit] + '...'


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--pid', type=int)
    parser.add_argument('--name', default='ps2EntryRunner.exe')
    parser.add_argument('--seconds', type=float, default=30.0)
    parser.add_argument('--interval-ms', type=float, default=3.0)
    parser.add_argument('--depth', type=int, default=24)
    parser.add_argument('--out')
    args = parser.parse_args()

    pid = args.pid or find_pid(args.name)
    if not pid:
        raise SystemExit(f'process {args.name} not found')
    process = kernel32.OpenProcess(PROCESS_ACCESS, False, pid)
    if not process:
        raise SystemExit(f'OpenProcess failed: {ctypes.get_last_error()}')
    dbghelp.SymSetOptions(0x4)
    dbghelp.SymInitializeW(process, None, True)
    table_access = FUNCTION_TABLE_ACCESS(lambda h, a: dbghelp.SymFunctionTableAccess64(h, a))
    module_base = GET_MODULE_BASE(lambda h, a: dbghelp.SymGetModuleBase64(h, a))

    buf = ctypes.create_string_buffer(1232 + 16)
    aligned = (ctypes.addressof(buf) + 15) & ~15
    stacks = collections.defaultdict(collections.Counter)  # tid -> Counter(tuple(frames))
    handles = {}
    deadline = time.perf_counter() + args.seconds
    rounds = 0
    while time.perf_counter() < deadline:
        for tid in thread_ids(pid):
            h = handles.get(tid)
            if h is None:
                h = kernel32.OpenThread(THREAD_ACCESS, False, tid)
                if not h:
                    continue
                handles[tid] = h
            if kernel32.SuspendThread(h) == 0xFFFFFFFF:
                continue
            try:
                ctypes.memset(aligned, 0, 1232)
                ctypes.c_uint32.from_address(aligned + 0x30).value = CONTEXT_FULL
                if not kernel32.GetThreadContext(h, ctypes.c_void_p(aligned)):
                    continue
                frame = STACKFRAME64()
                frame.AddrPC.Offset = ctypes.c_uint64.from_address(aligned + 0xF8).value
                frame.AddrStack.Offset = ctypes.c_uint64.from_address(aligned + 0x98).value
                frame.AddrFrame.Offset = ctypes.c_uint64.from_address(aligned + 0xA0).value
                frame.AddrPC.Mode = frame.AddrStack.Mode = frame.AddrFrame.Mode = 3
                frames = []
                for _ in range(args.depth):
                    if not dbghelp.StackWalk64(IMAGE_FILE_MACHINE_AMD64, process, h, ctypes.byref(frame),
                                               ctypes.c_void_p(aligned), None, table_access, module_base, None):
                        break
                    if frame.AddrPC.Offset == 0:
                        break
                    frames.append(frame.AddrPC.Offset)
                stacks[tid][tuple(frames)] += 1
            finally:
                kernel32.ResumeThread(h)
        rounds += 1
        time.sleep(args.interval_ms / 1000.0)

    modules = list_modules(process)
    addresses = sorted({a for per in stacks.values() for stack in per for a in stack})
    names = {}
    for path, base, size in modules:
        inside = [a for a in addresses if base <= a < base + size]
        for a, n in zip(inside, symbolize(path, base, inside)):
            names[a] = f'{os.path.basename(path)}!{n}'

    def name(a):
        return names.get(a, f'0x{a:x}')

    report = {'pid': pid, 'rounds': rounds, 'threads': []}
    for tid, per in stacks.items():
        total = sum(per.values())
        waiting = sum(c for st, c in per.items() if st and name(st[0]).startswith(('ntdll.dll', 'win32u.dll')))
        self_time = collections.Counter()
        inclusive = collections.Counter()
        named = collections.Counter()
        for st, c in per.items():
            frame_names = [name(a) for a in st]
            # Skip kernel wait stubs so self time names the caller that waits.
            first = next((n for n in frame_names if not n.startswith(('ntdll.dll', 'KERNELBASE.dll',
                                                                       'win32u.dll'))), '?')
            self_time[first] += c
            for n in set(frame_names):
                inclusive[n] += c
            named[' <- '.join(short(n, 60) for n in frame_names[:8])] += c
        report['threads'].append({'tid': tid, 'samples': total, 'kernel_wait_samples': waiting,
                                  'self': self_time.most_common(25), 'inclusive': inclusive.most_common(40),
                                  'stacks': named.most_common(12)})
    report['threads'].sort(key=lambda t: -(t['samples'] - t['kernel_wait_samples']))
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=1)
    print(f'{rounds} rounds')
    for t in report['threads'][:6]:
        busy = t['samples'] - t['kernel_wait_samples']
        print(f"thread {t['tid']}: {t['samples']} samples, {t['kernel_wait_samples']} in kernel waits, {busy} running")
        for n, c in t['self'][:12]:
            print(f'   self {100.0 * c / t["samples"]:6.2f}%  {short(n)}')
        for s, c in t['stacks'][:3]:
            print(f'   stack {100.0 * c / t["samples"]:6.2f}%  {s}')


if __name__ == '__main__':
    main()
