#!/usr/bin/env python3
"""lodestone check <terms...> — query failure memory BEFORE trying anything.

Adapted from InitialDad/PS2Recomp-WoS-Findings (CC0), whose own rationale:
"Most recompilation and RE projects fail not for lack of tools but for lack of
verification discipline and memory of what already failed."
"""
import json, sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "knowledge" / "dead_ends.jsonl"

def main(argv):
    if len(argv) < 2:
        print(__doc__); return 2
    terms = [t.lower() for t in argv[1:]]
    rows = []
    for line in DB.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line: continue
        try: r = json.loads(line)
        except json.JSONDecodeError:
            print(f"!! malformed dead-end line skipped: {line[:60]}"); continue
        hay = f'{r.get("pattern","")} {r.get("reason","")}'.lower()
        if all(t in hay for t in terms): rows.append(r)
    if not rows:
        print(f"no recorded failure matches {' '.join(terms)}")
        print("(that is not proof the idea is new — record the result when you finish)")
        return 0
    print(f"{len(rows)} known failure(s) match {' '.join(terms)}:\n")
    for r in rows:
        print(f"  !! #{r['id']} {r['pattern']}")
        print(f"     why   {r['reason']}")
        print(f"     ref   {r.get('ref','-')}")
        print(f"     prior {r.get('project','-')}\n")
    return 0

if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # a Windows console is not UTF-8
        _s.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main(sys.argv))
