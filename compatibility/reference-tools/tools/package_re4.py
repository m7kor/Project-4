"""Build a verified local RE4 native folder; never delete source game or saves."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import time
import subprocess
import re

ROOT = Path(__file__).resolve().parents[1]


def runtime_dependencies(executable, inspector=None, system_directory=None):
    """Resolve the transitive PE imports; fail before shipping an incomplete folder."""
    inspector = inspector or shutil.which('llvm-readobj') or 'C:/Program Files/LLVM/bin/llvm-readobj.exe'
    system_directory = system_directory or Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32'
    local = {p.name.lower(): p for p in executable.parent.glob('*.dll')}
    pending, visited, dependencies = [executable], set(), {}
    while pending:
        binary = pending.pop()
        if binary.name.lower() in visited:
            continue
        visited.add(binary.name.lower())
        result = subprocess.run([str(inspector), '--coff-imports', str(binary)],
                                capture_output=True, text=True, check=True, timeout=30)
        for name in re.findall(r'^\s*Name:\s*(\S+\.dll)\s*$', result.stdout, re.MULTILINE | re.IGNORECASE):
            key = name.lower()
            if key in local:
                dependencies[key] = local[key]
                pending.append(local[key])
            elif key.startswith(('api-ms-', 'ext-ms-')) or (system_directory / name).is_file():
                continue
            else:
                raise RuntimeError(f'Missing runtime dependency: {binary.name} -> {name}')
    return sorted(dependencies.values(), key=lambda p: p.name.lower())


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def package():
    source = ROOT / 'game/Resident Evil 4 (USA)'
    destination = ROOT / 'Resident Evil 4'
    destination.mkdir(exist_ok=True)
    records = []
    runner = ROOT / 'core/out/build/ps2xRuntime/ps2EntryRunner.exe'
    runtime_dlls = runtime_dependencies(runner)

    def copy(src, dst, expected=None, replace=False):
        if src.is_symlink() or dst.is_symlink():
            raise RuntimeError(f'Linked package input/output is not supported: {src} -> {dst}')
        sha = expected or digest(src)
        if expected and digest(src) != expected:
            raise RuntimeError(f'Original game file does not match the preservation audit: {src}')
        existing_sha = digest(dst) if dst.exists() else None
        if existing_sha is not None and existing_sha != sha and not replace:
            raise RuntimeError(f'Existing destination differs; preserved without overwriting: {dst}')
        if existing_sha != sha:
            dst.parent.mkdir(parents=True, exist_ok=True)
            temporary = dst.with_name(dst.name + '.packaging-partial')
            if temporary.exists():
                raise RuntimeError(f'Previous incomplete copy needs inspection: {temporary}')
            shutil.copy2(src, temporary)
            if digest(temporary) != sha:
                raise RuntimeError(f'Copied bytes failed verification: {temporary}')
            # Windows scanners can briefly hold a newly copied file. Retry
            # that transient lock; a persistent lock still preserves the old
            # destination and reports failure without deleting either copy.
            for attempt in range(12):
                try:
                    os.replace(temporary, dst)
                    break
                except PermissionError:
                    if os.name != 'nt' or attempt == 11:
                        raise
                    time.sleep(0.1)
        records.append({'source': str(src.relative_to(ROOT)), 'path': str(dst.relative_to(destination)),
                        'bytes': dst.stat().st_size, 'sha256': sha})
        print(f'Verified: {dst.relative_to(destination)}', flush=True)

    reference = json.loads((ROOT / 'artifacts/research/20261007/game-file-preservation-auto-controller.json').read_text())
    for item in reference['files']:
        relative = Path(item['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise RuntimeError('Invalid original-file audit path')
        copy(source / relative, destination / relative, item['sha256'])

    # Prefer active save storage; retain all source data and never replace a
    # destination save with an older legacy copy.
    active = source / 'saves'
    if active.exists():
        for path in sorted(active.rglob('*')):
            if path.is_symlink():
                raise RuntimeError(f'Linked save input requires inspection: {path}')
            if path.is_file():
                target = destination / 'saves' / path.relative_to(active)
                if not target.exists():
                    copy(path, target)
    if not (active / '.legacy-migration-complete').exists():
        for port in range(2):
            legacy = source / f'mc{port}'
            if legacy.is_symlink():
                raise RuntimeError(f'Linked save input requires inspection: {legacy}')
            for path in sorted(legacy.rglob('*')):
                if path.is_symlink():
                    raise RuntimeError(f'Linked save input requires inspection: {path}')
                if not path.is_file():
                    continue
                relative = path.relative_to(legacy)
                target = destination / 'saves' / (f'cards' if relative == Path(f'native-card-{port}.ps2') else f'mc{port}') / relative
                if target.exists():
                    continue
                copy(path, target)
    for folder in ('cards', 'mc0', 'mc1'):
        (destination / 'saves' / folder).mkdir(parents=True, exist_ok=True)
    records = [r for r in records if not Path(r['path']).parts[0] == 'saves']
    for path in sorted((destination / 'saves').rglob('*')):
        if path.is_symlink():
            raise RuntimeError(f'Linked package save requires inspection: {path}')
        if path.is_file():
            records.append({'source': 'retained package save', 'path': str(path.relative_to(destination)),
                            'bytes': path.stat().st_size, 'sha256': digest(path)})
    copy(runner, destination / 'Resident Evil 4.exe', replace=True)
    for dll in runtime_dlls:
        copy(dll, destination / dll.name, replace=True)
    copy(ROOT / 'core/LICENSE', destination / 'licenses/PS2Recomp-GPL.txt', replace=True)
    copy(ROOT / 'core/ps2xRuntime/resources/controllers/LICENSE', destination / 'licenses/ControllerDB-LICENSE.txt', replace=True)
    copy(ROOT / 'core/deps/raylib/LICENSE', destination / 'licenses/raylib-LICENSE.txt', replace=True)
    copy(ROOT / 'core/deps/raylib/src/external/glfw/LICENSE.md', destination / 'licenses/GLFW-LICENSE.txt', replace=True)
    copy(ROOT / 'core/deps/fmt/LICENSE', destination / 'licenses/fmt-LICENSE.txt', replace=True)
    copy(ROOT / 'dependencies/pcsx2/3rdparty/soundtouch/COPYING.TXT', destination / 'licenses/SoundTouch-LGPL-2.1.txt', replace=True)
    copy(ROOT / 'integrations/kzspu2/COPYING.GPLv3', destination / 'licenses/kzspu2-GPL-3.0.txt', replace=True)
    copy(ROOT / 'docs/licenses/runtime-libraries/FFmpeg-LGPL-2.1.txt', destination / 'licenses/FFmpeg-LGPL-2.1.txt', replace=True)
    (destination / 'Play.cmd').write_text(
        '@echo off\nsetlocal\npushd "%~dp0"\n'
        'set "PS2X_IOP_SIO2_NATIVE=1"\nset "PS2X_IOP_SPU2_NATIVE=1"\n'
        'set "PS2X_GS_BACKEND=parallel"\nset "PS2X_GS_THREAD=1"\n'
        'set "PS2X_VU1_CLEAN_BLOCKS=1"\nset "PS2X_VIF1_FAST_UNPACK=1"\n'
        'set "PS2X_VU1_COMMANDS_DIR="\nset "PS2X_PROFILE_VU1_DIR="\n'
        'set "PS2X_VU1_TRACE_BLOCKS="\nset "PS2X_VIF1_FAST_WITNESS="\n'
        'set "PS2X_PAD_FRESH_GLFW=0"\nset "PS2X_TRACE_PAD="\n'
        'set "PS2X_NATIVE_PAD_REPLAY="\nset "PS2X_IOP_RPC_CAPTURE="\n'
        'set "PS2X_TRACE_NATIVE_RPC_SID="\nset "PS2X_TRACE_IOP_PC="\n'
        'set "PS2X_CAPTURE_DIR="\nset "PS2X_TRACE_EE="\n'
        'set "PS2X_TRACE_GUEST_WORDS="\n'
        'set "PS2X_PROFILE_IOP_HOST="\n'
        'set "PS2X_PROFILE_IOP_STAGES="\n'
        'set "PS2X_TRACE_CALLS="\nset "PS2X_TRACE_CALL_SOURCES="\n'
        'set "PS2X_SIF_RPC_TIMING="\n'
        'set "PS2X_SIF_RPC_ASYNC=0x80000400"\n'
        'set "PS2X_TRACE_IOP_THREADS="\nset "PS2X_TRACE_IOP_PC="\n'
        '"Resident Evil 4.exe" "SLUS_211.34"\n'
        'set "RE4_EXIT_CODE=%ERRORLEVEL%"\npopd\nexit /b %RE4_EXIT_CODE%\n', encoding='ascii')
    (destination / 'README.txt').write_text(
        'Resident Evil 4 — تشغيل PC الأصلي قيد التطوير\n\n'
        'شغّل Play.cmd. لا يحتاج بناء المشروع عند التشغيل.\n'
        'برنامج Resident Evil 4.exe يشغّل بيانات اللعبة الموجودة بجانبه.\n'
        'الحفظ داخل saves؛ البطاقة الخام داخل saves/cards، وملفات مسار الحفظ الآخر داخل saves/mc0 وsaves/mc1.\n'
        'تم التحقق من شاشة بيانات النظام والوصول إلى بداية اللعب. سرعة اللعب الكاملة وحفظ تقدم المرحلة ما زالا قيد التحقق.\n'
        'إصلاح الصوت يشمل ترتيب مهام IOP للقناتين وضبط خرج SoundTouch حسب إنتاج اللعبة وطلب جهاز الصوت. تفاصيل التحقق والقيود داخل docs في المشروع.\n'
        'لا تُعد هذه النسخة شهادة لعب كامل: تم التحقق من إنشاء بيانات النظام وقراءتها بعد إعادة التشغيل والوصول إلى شاشة عنوان اللعبة؛ حفظ تقدم اللعب لم يُختبر بعد، ومقدمة PS2 لم تُدمج. الإقلاع البطيء ما زال قيد الإصلاح.\n'
        'المجلد يجهز نسخة محلية من ملفات اللعبة الموجودة في المشروع.\n', encoding='utf-8-sig')
    (destination / 'package-manifest.json').write_text(json.dumps(
        {'schema': 1, 'scope': 'verified-local-native-folder', 'game_compatibility': 'unverified',
         'original_game_files': len(reference['files']), 'files': records}, indent=2) + '\n', encoding='utf-8')
    print(f'Package ready: {destination}', flush=True)


if __name__ == '__main__':
    package()
