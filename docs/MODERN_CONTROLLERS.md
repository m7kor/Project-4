# Automatic modern-controller input

## Fresh desktop sampling

Update 2026-10-14: at the user's request, normal play returns to raylib's
original cached controller polling. Direct fresh GLFW sampling is now an
opt-in comparison mode (`PS2X_PAD_FRESH_GLFW=1`); the normal launcher sets it
to zero. The mapping database, PS2 layout, pressure conversion and focus-loss
release remain. `PS2X_TRACE_PAD=1` records host publication and native guest
consumption separately. Detection or neutral guest reads alone do not prove
that physical buttons work; the GameSir regression still needs observed
physical presses in a focused game window.

The following describes the earlier fresh-sampling change, retained as the
comparison mode:

On GLFW desktop builds, the window thread now calls `glfwGetGamepadState` to
publish a fresh standardized controller snapshot before rendering. Previously
it read raylib's cached state, which is refreshed at `EndDrawing` and therefore
belonged to the previous presentation frame. The PS2 button order, analog
pressure, deadzone, focus handling and original game artwork are preserved.
Other platforms retain their raylib backend. This removes the stale sampling
stage; physical end-to-end latency still requires measurement and also depends
on guest execution speed.

The runtime loads a pinned, offline copy of SDL_GameControllerDB automatically after opening its window. The bundle contains 2,279 mappings (869 for Windows), including Xbox, Sony and GameSir entries. Database version, original file hashes and embedded-header hash are recorded in `core/ps2xRuntime/resources/controllers/manifest.json`; the original zlib license is distributed beside it. No network access is required when playing.

Use `Play-RE4.cmd` for ordinary RE4 play: it enables the native SIO2/SPU2 paths needed by this development build and removes replay-input and selected diagnostic settings from its child process. The physical controller is chosen automatically; no button setup or game-artwork conversion is required. Separate card fixes have now verified original formatting, system-data creation and readback; gameplay-progress saving remains unverified (see [SIO2_ASYMMETRIC_CARD.md](SIO2_ASYMMETRIC_CARD.md)). The launcher does not certify full-game compatibility. `python tools/controllers/embed_mappings.py --check` verifies the pinned source/license hashes and that the compiled header matches them; running without `--check` reproducibly regenerates that header.

The host normalizes controller buttons by physical position. Game artwork and original game files are untouched:

| Original PS2 function | Xbox position/name | Sony position/name |
| --- | --- | --- |
| Cross × | South / A | South / × |
| Circle ○ | East / B | East / ○ |
| Square □ | West / X | West / □ |
| Triangle △ | North / Y | North / △ |
| L1 / R1 | LB / RB | L1 / R1 |
| L2 / R2 | LT / RT | L2 / R2 |
| L3 / R3 | Stick clicks | Stick clicks |
| Select / Start | View / Menu | Share or Create / Options |

Each host frame scans the four controller slots supported by the current raylib backend. It chooses the first mapped controller, retains ownership while it remains connected, and automatically switches to another connected controller or the keyboard after disconnection. Reconnection can use a different host index. One host controller is routed to PS2 port 0; it is not duplicated onto port 1. Unsupported raw joysticks are not assigned guessed button indices.

Window-thread polling publishes one complete mutex-protected state. Guest EE/IOP input reads do not poll GLFW/raylib independently. Losing focus releases all buttons and centers the sticks while retaining device selection. Both sticks use a radial 8% deadzone with full-range rescaling, finite-value checks and the PS2 0–255 range. Trigger travel becomes proportional DS2 L2/R2 pressure, with activation near the beginning of travel. Digital face buttons retain binary pressure because ordinary modern face buttons lack DS2 pressure sensors. Known mappings without trigger axes are neutralized instead of interpreting GLFW’s absent-axis zero as a half press. The HLE and native paths share host input, and the HLE R1/L2 pressure-byte ordering is corrected to the DS2 layout.

OS-level USB/Bluetooth connection remains the operating system’s responsibility. Automatic synchronization here means detection, standardized mapping and reconnection within the running application; it does not perform Bluetooth pairing or install drivers. Rumble output remains unimplemented by the GLFW backend, and multitap or simultaneous second-player input is outside this implementation. Hardware compatibility must be verified on actual models; database entries and synthetic tests do not establish that every controller or transport mode has been physically tested.

The meaningful regression tests cover host index 2, stable ownership, switching without stale buttons, keyboard fallback, reconnection at index 3, focus loss, port isolation, drift suppression, full stick travel, analog trigger travel/release, invalid axis values and distinct R1/L2 pressure bytes. The release build succeeded in 141.6 seconds, and `artifacts/verification/auto-controller-release.json` records 482/482 C++ tests, 101/101 Python tests and three tooling checks passing. All eight original game files passed `artifacts/research/20261007/game-file-preservation-auto-controller.json`. Run `20261008T024314Z-0e6bdea4` logged `[controller] Xbox Controller host=0 PS2-port=0` at startup, demonstrating automatic detection of the attached device. That diagnostic run uses deterministic replay for guest input, so it does not certify physical button presses, Bluetooth reconnection or other controller models.

Primary references: [GLFW gamepad input](https://www.glfw.org/docs/latest/input_guide.html#gamepad), [SDL_GameControllerDB pinned source](https://github.com/mdqinc/SDL_GameControllerDB/tree/c1d5289a1f713b30a2c121e9fe6529d39360be0f), and the pinned PCSX2 DualShock 2 reference in `artifacts/research/20261007/sio2-reference/manifest.json`.
