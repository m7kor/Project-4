"""Run the project CLI with python -m ps2l."""
import sys
from .cli import main

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")
raise SystemExit(main(sys.argv))
