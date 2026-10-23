# Local RE4 native folder and per-game saves

The user-facing folder is `Resident Evil 4` at the workspace root. It contains
`Resident Evil 4.exe`, `Play.cmd`, all eight original extracted game files,
license notices and `package-manifest.json`. `Play.cmd` launches the bundled
executable with its bundled ELF and enables native SIO2/SPU2. No compiler or
Python process is required to play. The root `Play-RE4.cmd` forwards to it.

Save layout:

```
Resident Evil 4/
  saves/
    cards/native-card-0.ps2
    mc0/
    mc1/
    .legacy-migration-complete
```

The native PS2 memory card is separate from the file-backed card directories.
Formatting a file-backed card therefore cannot delete the live native card
image. Both belong to this game folder and remain with it when it is moved.
Custom file-card roots are still respected; native images use the sibling
`cards` directory. This organizes storage but does not repair native formatting.

At startup, game-local legacy `mc0`/`mc1` contents are copied once into `saves`.
Existing destination files win; original files are retained. The completion
marker prevents restarting from resurrecting files deleted by formatting or
ordinary save deletion. Linked migration inputs/destinations are rejected.
The executable selects the game folder before initializing the native IOP,
avoiding creation of a card in the working directory before the ELF is loaded.

`tools/package_re4.py` verifies original source and package bytes against the
eight-file preservation audit, copies active saves or retained legacy saves
without overwriting an existing package save, and records all packaged hashes.
Partial asset copies do not replace the target until their hash is verified.
Source game assets and save files are not deleted.

Validation: `artifacts/verification/game-save-folder.json` records 484/484 C++
and 101/101 Python tests plus three tooling checks passing. The migration
regression covers both slots, current-save priority, raw-image separation,
legacy retention, no resurrection and separation between different game
folders. The final build succeeded in 186.1 seconds.

Final packaging verification is recorded separately in
`artifacts/verification/re4-package-final.json`. Two packaging regression cases
verify that updating the bundle preserves newer destination saves and refuses
to overwrite conflicting game assets. Package tests use the workspace
filesystem, since atomic rename in the sandbox's virtualized Windows temp
returned access denied. The actual workspace package copy succeeded.

Bundled run `20261008T034141Z-48d2fbe7` executed the ELF and native executable
from `Resident Evil 4`, observed 65 frames over 151.531 seconds and reached
virtual field 903. Replay delivered all twelve button transitions. Only Init
and GetInfo were captured by the selected card-service trace; no native Format
RPC or selected Format entry was observed. The save-format issue and full
gameplay remain unverified. The configured timeout ended the observation.

Next card investigation: the EE client Format routine was located at 0x2A97A0
by its asynchronous function-0x10 call to SifCallRpc at 0x29F488, from call
site 0x2A9828. It can return -100 before calling when its client server field
is zero, or -200 when PollSema fails. These are static paths, not yet observed
causes. See `artifacts/research/20261008/mc-client-call-sites.json`.
