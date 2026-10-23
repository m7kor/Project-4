# RE4 recompile: proposed masterpiece vision

Date: 2026-10-12. Brainstorm and proposed roadmap, not a completion claim.

## The experience we are aiming for

A faithful, polished PC edition of the PS2 game: the original atmosphere,
combat timing, cutscenes and progression, with dependable performance, clean
sound, clear presentation and effortless controls. Improvements should make
the game feel finished from launch through the ending and every included mode.

“10x better” is an ambition. We will measure concrete changes in frame time,
sound faults, loading, reliability and usability rather than invent one score.

## Current evidence and gaps

- Early gameplay and cutscenes run; a complete campaign has not been verified.
- Natural gameplay speed remains below target in the recorded gameplay runs.
  A full-speed static screen does not demonstrate full-speed combat.
- Cutscene sound has periodic corruption already present upstream of the
  sampled EE-to-IOP transfers. The exact production fault remains open.
- Creating and reloading system settings was tested. Story progress saves,
  death/retry recovery and late-game progression still need real tests.
- GPU rendering works in tested scenes. Full scene coverage and presentation
  quality across the game remain unproven.
- The latest Python run passed 236 tests; earlier C++ evidence is 539 tests.
  An isolated known-input ADX call now matches original machine instructions
  and generated code with checkpoints disabled, every checkpoint, and every
  eighth checkpoint. That result does not validate real cutscene inputs.

## Ideas ranked by player impact

| Area | Proposed improvements | Proof we need |
|---|---|---|
| Sound | Correct decoding and buffer handoff; dependable streaming; channel balance; stable dialogue/music/effects mix | Same-scene original references, internal and speaker captures, channel/transition checks, listening review |
| Performance | Natural simulation speed; consistent frame delivery; fewer loading/shader stalls | Timed gameplay on a documented hardware/resolution baseline, including busy combat and effects |
| Gameplay | Correct aiming, enemy behavior, collisions, damage, inventory, camera, menus and scripted events | Matched scenarios and complete playthrough coverage, including deaths and retries |
| Cutscenes | Complete playback, synchronized dialogue/subtitles/video, reliable skip and return to play | In-game coverage of every included movie and transition; decoding files alone is insufficient |
| Saves | Dependable chapter saves/load, safe persistence, separate settings/progress, optional backup recovery | Save at real checkpoints, close/reopen, load and verify inventory, chapter, difficulty and state |
| Presentation | Clear text, clean scaling, correct brightness/colors, stable image; optional higher resolution | Reference screenshots and movement checks across menus, dark scenes, effects and cutscenes |
| Controls | Easy remapping, useful defaults, controller reconnect handling, sensitivity options and reliable rumble where supported | Actual keyboard/controller play, pause/focus/reconnect tests and retained settings |
| Finish | A simple launcher, understandable settings, dependable packaging and a one-click diagnostic report | A fresh installation can launch, configure, play, save and recover without developer setup |

## Three directions to choose from

1. **Faithful premium edition — recommended.** Preserve the original game
   behavior and atmosphere; improve reliability, sound, performance and PC
   usability. The existing project work fits this direction best.
2. **Modernized edition.** Add optional widescreen/camera/control changes,
   visual upgrades and eventually higher frame rates. Each needs explicit
   design choices and its own correctness tests.
3. **Preservation edition.** Prioritize original image, timing and behavior,
   with minimal presentation changes and extensive reference comparison.

Use faithful behavior as the common foundation. Keep experimental enhancements
separately selectable and label unverified ones clearly. A 60-fps mode requires
game timing, animation, scripting and physics work; it is a separate milestone.

## Proposed delivery sequence

### 1. Make the opening excellent

Use one repeatable route: launch, settings, opening movies, first combat,
inventory, death/retry, a story save, restart and load. Finish this whole route
with clean sound and natural speed, then expand coverage. This is the first
quality milestone, not a replacement for completing the game.

Immediate sound experiment: capture real ADX call inputs, compare original
instructions with generated code, then trace input identity, decoder history,
keys and buffer ownership. Repair the responsible layer and replay the same
scene through both internal and actual speaker recording.

Immediate performance experiment: measure EE, IOP, VU, GS and presentation in
the same playable route, fix the largest measured costs, then repeat. Ordered
VU threading and direct GPU presentation are candidates, not assumed cures.

### 2. Prove the whole game

Build a coverage ledger for every chapter, boss, dynamic module, included mode,
cutscene and major transition. Record hardware, build, settings, actions and
evidence for each result. Test saves and recovery throughout the campaign,
including chapter transitions and completion/unlocks. Reproduce failures on
the reference where practical and add focused regressions for real defects.

### 3. Polish the PC experience

Choose a tested default resolution, presentation and sound configuration.
Improve text, input defaults, launch/loading behavior and settings clarity.
Add optional enhancements once their affected scenarios are covered.
Gather user feedback on feel, sound and readability; automated checks cannot
fully judge those qualities.

### 4. Release and sustain quality

Package the exact verified build. Test a fresh installation and long sessions,
repeated launches, suspend/focus changes, controller/audio-device reconnects,
save recovery and update preservation. Keep a known-good build and a release
checklist so future changes do not silently undo fixes.

## Definition of done

- All included campaign/mode content is playable and verified, with no known
  blocking progression, gameplay, save or cutscene failures.
- Intended timing is preserved at natural speed on the published baseline.
  The current game uses a 30-fps presentation target; raising the displayed
  frame rate alone is not an improvement in simulation speed.
- Sound has no confirmed added corruption, unintended duplication, streaming
  gaps or synchronization defects in covered scenarios. Naturally centered
  dialogue must not be misclassified as broken stereo.
- Story saves survive restart and reproduce the correct game state.
- Presentation and controls satisfy the reference checks and player review.
- The shipped package passes the same checks as the development build.
- Documentation states remaining limitations honestly. A green unit-test
  suite or a successful boot is not proof of these requirements.

## Existing evidence

[Current state](CURRENT.md), [engineering plan](PLAN.md),
[audio investigation](AUDIO_WASAPI_PCSX2_20261012.md),
[open-source tools](OPEN_SOURCE_AUDIO_TOOLS_20261012.md),
[call replay](CALL_TRACE.md).
