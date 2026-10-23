"""Load the portable RenderDoc DLL in this isolated process and verify its API.

Does not inject into the game, capture a frame, or install a Vulkan layer.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('dll', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Preserve existing evidence')
    dll_path = args.dll.resolve(strict=True)
    with os.add_dll_directory(str(dll_path.parent)):
        library = ctypes.CDLL(str(dll_path))
        get_api = library.RENDERDOC_GetAPI
        get_api.argtypes = (ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))
        get_api.restype = ctypes.c_int
        api = ctypes.c_void_p()
        # Version 1.0.0 is the API requested by our Granite source.
        accepted = get_api(10000, ctypes.byref(api))
        if accepted != 1 or not api.value:
            raise RuntimeError('RenderDoc API 1.0.0 unavailable')
        first_function = ctypes.cast(api, ctypes.POINTER(ctypes.c_void_p))[0]
        if not first_function:
            raise RuntimeError('GetAPIVersion unavailable')
        get_version = ctypes.CFUNCTYPE(None, ctypes.POINTER(ctypes.c_int),
                                       ctypes.POINTER(ctypes.c_int),
                                       ctypes.POINTER(ctypes.c_int))(first_function)
        major, minor, patch = ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
        get_version(ctypes.byref(major), ctypes.byref(minor), ctypes.byref(patch))
        report = {'scope': __doc__, 'dll': str(dll_path),
                  'dll_sha256': hashlib.sha256(dll_path.read_bytes()).hexdigest(),
                  'requested_api': '1.0.0', 'accepted': True,
                  'returned_api': f'{major.value}.{minor.value}.{patch.value}',
                  'game_frame_captured': False}
        with args.out.open('x', encoding='utf-8') as output:
            json.dump(report, output, indent=2)
        print(json.dumps(report))


if __name__ == '__main__':
    main()
