# SIO2 asymmetric memory-card response clocks

## Actual blocked path

Fresh-card run `20261008T154319Z-a0cf82b9` (400.11 seconds) completed the original Format handler and two original Open calls, then did not complete RPC function `0x1B`. Original service thread 15 remained sampled in Delay at `0x56B80`, with DelayThread argument 500. The actual retail code issues command `0x12` using descriptor `0x100370` at `0x5589C`; its input is three bytes and its response length is four clocks. At `0x56BE4`, it branches back to the delay until the receive byte at `0x6615B` equals the card terminator `0x55`.

The prior card implementation rejected that valid three-byte command because it required the input span to contain all four response clocks. SIO2 then padded a failed three-byte reply, leaving the expected terminator unavailable. This explains this observed write-finish retry path; it does not by itself identify the initial boot performance bottleneck.

## Change and verification

Memory-card replies now allocate their own protocol response length independently of input length. Fixed-response commands can return more bytes than sent. Sector selection requires its actual seven-byte payload, terminator setting its three-byte payload, and read requests their count byte. Writes still require their full data and checksum input; truncated writes remain rejected. NAND programming/erase and range protection remain covered by existing reopen and neighbor-block tests.

SIO2 now aligns the complete generated response to the DMA block size, rather than truncating it to the number of input bytes in one TX block. This follows the pinned PCSX2 SIO2 implementation's post-response alignment. The new test feeds the exact retail three-byte write-finish descriptor and checks all four returned bytes. It also feeds a three-byte 128-byte read request inside a 16-byte TX DMA block and verifies all 134 response bytes plus padding to 144 bytes. Both cases would fail with the previous length coupling.

`artifacts/verification/sio2-asymmetric-card-final.json`: **494/494 C++ tests, 106/106 Python tests, three tool checks**, all passing. The updated native runner build completed successfully in 161.6 seconds (86,673,920 bytes); actual game creation/save/restart/load remains unverified. The normal package and original user saves have not been replaced.

Evidence: `artifacts/research/20261008/iop-card-clock-fresh-observation.json`, `iop-card-clock-fresh-thread-final.json`, `mcman-write-wait-static.json`, `mcman-wait-send-static.json`, and `iop-card-clock-fresh-card.json`.

## Primary reference

Pinned PCSX2 commit `646df006a4688063e56c0826e7ea4b8bb0c112c4`, preserved and hashed under `artifacts/research/20261007/sio2-reference`:

- https://github.com/PCSX2/pcsx2/blob/646df006a4688063e56c0826e7ea4b8bb0c112c4/pcsx2/SIO/Memcard/MemoryCardProtocol.cpp
- https://github.com/PCSX2/pcsx2/blob/646df006a4688063e56c0826e7ea4b8bb0c112c4/pcsx2/SIO/Sio2.cpp

These references describe response generation and DMA alignment. The game-specific descriptor, addresses, and wait branch were disassembled from the actual captured retail IOP RAM, not copied from a modern SDK.

## Actual creation result

Run `20261008T155828Z-861b21b9` lasted 400.234 seconds without recorded fault patterns. The formerly blocked function `0x1B` completed three original writes with lengths **60, 19,280, and 964 bytes**, and each original Close returned zero. The game advanced to creation state `0x28` after each file, free clusters became `0x1F27`, and the service thread returned to RpcLoop sleep. The isolated raw card has 160 non-erased pages and SHA-256 `f12cdeb498fc7e74daad86028bbf28dea25f892ce32634f794cd95b00aa3e061`.

This establishes original system-file creation beyond the prior write-finish loop. A neutral-input restart/readback observation is now running against these retained bytes, without resetting the card. Full gameplay save/load, game rendering after the card screen, performance and intro remain unverified; later captured frames in the creation run were black. The normal package has not yet been promoted. Evidence: `artifacts/research/20261008/sio2-asymmetric-card-observation.json`, `sio2-asymmetric-card-created-live.json`, and `native-async-system-created.ps2`.

## Original system-data restart/readback

Neutral-input run `20261008T160601Z-b31beaa6` lasted 200.141 seconds without recorded fault patterns. Native GetDir returned five entries; Open returned zero; original fast-read function `0x16` returned **60 bytes**; Close returned zero. The game showed “Loading system data” in `frame-5280.png`, completed its read state machine with result word `0x3CF838=0`, and cleared the loader callback through `0x1229A4` returning to `0x1237F0`. The raw card SHA-256 remained identical to the created-card backup. The created image contains `BASLUS-21134SYS`, `bio4.ico` and `icon.sys` names.

This verifies original system-data creation, retained card storage, restart, and original readback. It does not certify gameplay progress saving/loading, the entire filesystem or ECC implementation, or full gameplay. Later frames still become black; startup remains slow. Packaging now selects queued execution only for card SID `0x80000400`, while clearing the unsuccessful measured-reply timing experiment and input/debug fixtures. Packaging completed successfully; the package executable exactly matches the tested runner. Original user saves will be retained; the experimental card is not copied into their save folder.

Evidence: `artifacts/research/20261008/sio2-asymmetric-card-restart-observation.json` and `sio2-asymmetric-card-restart-state.json`.

Final package audit: `artifacts/research/20261008/sio2-asymmetric-card-package-audit.json`. The eight original asset hashes were verified by the packager, the Play launcher selects only card SID `0x80000400` and clears replay/debug options, and the original package card remains the preserved all-erased image (SHA-256 `47ebe237a3987f843fc19b0f801ce1edc1690768ef6b18e4b03a12ca6b298358`). No experimental save was copied into user storage.
