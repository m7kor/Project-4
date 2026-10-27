"""Read bounded EE memory windows from paused local PCSX2 via PINE.

Protocol reference: PCSX2 PINE; workflow inspired by KIexster/god-of-war-recomp.
No write, resume, savestate or controller commands are implemented.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import socket
import struct

RAM_BYTES = 32 * 1024 * 1024
MAX_WINDOW = 65536
MAX_TOTAL = 1024 * 1024


class Pine:
    def __init__(self, connection):
        self.connection = connection

    def exact(self, size):
        result = bytearray()
        while len(result) < size:
            fragment = self.connection.recv(size - len(result))
            if not fragment:
                raise EOFError("PCSX2 disconnected during a reply")
            result.extend(fragment)
        return bytes(result)

    def query(self, request, max_payload):
        self.connection.sendall(struct.pack("<I", len(request) + 4) + request)
        length = struct.unpack("<I", self.exact(4))[0]
        if not 5 <= length <= max_payload + 5:
            raise ValueError("Invalid PINE reply length")
        response = self.exact(length - 4)
        if response[0] != 0:
            raise ValueError("PCSX2 rejected the read")
        return response[1:]

    def status(self):
        payload = self.query(b"\x0f", 4)
        if len(payload) != 4:
            raise ValueError("Invalid PINE status")
        return struct.unpack("<I", payload)[0]

    def text(self, command):
        if command not in (8, 12, 13):
            raise ValueError("Unsupported identity command")
        payload = self.query(bytes([command]), 4096)
        if len(payload) < 5:
            raise ValueError("Truncated PINE identity")
        length = struct.unpack_from("<I", payload)[0]
        value = payload[4:]
        if length != len(value) or not value.endswith(b"\0"):
            raise ValueError("Invalid PINE identity string")
        return value[:-1].decode("utf-8")

    def identity(self):
        if self.status() != 1:
            raise ValueError("Pause PCSX2 before reading a reference")
        result = {"serial": self.text(12), "crc": self.text(13).lower(),
                  "version": self.text(8)}
        if self.status() != 1:
            raise ValueError("PCSX2 resumed during identity inspection")
        return result

    def read(self, address, size):
        validate_window(address, size)
        request = b"".join(b"\x02" + struct.pack("<I", at)
                           for at in range(address, address + size, 4))
        payload = self.query(request, size)
        if len(payload) != size:
            raise ValueError("Truncated EE memory reply")
        return payload


def validate_window(address, size):
    if (address < 0 or address % 4 or size <= 0 or size % 4
            or size > MAX_WINDOW or address + size > RAM_BYTES):
        raise ValueError("EE window must be aligned and within 32 MiB RAM")


def capture(pine, serial, crc, windows):
    if not re.fullmatch(r"[0-9a-fA-F]{8}", crc):
        raise ValueError("Expected CRC must be eight hexadecimal digits")
    if not windows or len(windows) > 64 or sum(size for _, size in windows) > MAX_TOTAL:
        raise ValueError("Specify 1–64 windows totalling at most 1 MiB")
    for address, size in windows:
        validate_window(address, size)
    before = pine.identity()
    if before["serial"] != serial or before["crc"] != crc.lower():
        raise ValueError("PCSX2 game identity differs from the expected edition")
    values = [pine.read(address, size) for address, size in windows]
    # Detect unstable probes as well as a resumed or replaced game.
    for (address, size), value in zip(windows, values):
        if pine.read(address, size) != value:
            raise ValueError("EE memory changed during capture")
    if pine.identity() != before:
        raise ValueError("PCSX2 identity changed during capture")
    return {"schema": 1, "source": "paused PCSX2 PINE", "identity": before,
            "windows": [{"address": hex(address), "size": size,
                         "sha256": hashlib.sha256(value).hexdigest(), "bytes_hex": value.hex()}
                        for (address, size), value in zip(windows, values)],
            "limitation": "Stable windows do not establish the same native game checkpoint."}


def parse_window(text):
    try:
        address, size = (int(part, 0) for part in text.split(":"))
        validate_window(address, size)
        return address, size
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=28011)
    parser.add_argument("--inspect", action="store_true", help="Print paused game's identity only")
    parser.add_argument("--serial", default="SLUS-21134")
    parser.add_argument("--crc", help="Verified PCSX2 CRC for this game edition")
    parser.add_argument("--window", type=parse_window, action="append", default=[])
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Invalid local PINE port")
    if not args.inspect and (not args.crc or not args.window or not args.out):
        parser.error("Capture requires --crc, --window and --out")
    if not args.inspect and (not re.fullmatch(r"[0-9a-fA-F]{8}", args.crc)
                             or len(args.window) > 64
                             or sum(size for _, size in args.window) > MAX_TOTAL):
        parser.error("Invalid CRC or capture window budget")
    if args.out and args.out.exists():
        parser.error("Output already exists; choose a new reference file")
    with socket.create_connection(("127.0.0.1", args.port), timeout=5) as connection:
        pine = Pine(connection)
        result = pine.identity() if args.inspect else capture(pine, args.serial, args.crc, args.window)
    if not args.inspect:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
    print(json.dumps(result if args.inspect else {"out": str(args.out), "windows": len(result["windows"])}))


if __name__ == "__main__":
    main()
