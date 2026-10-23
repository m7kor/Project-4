# Vertical text flicker: evidence and host presentation change

The user's 4.7685-second, 2560x1440, 60 Hz recording shows the RE4 system-data
prompt oscillating vertically. Examination of the first 120 decoded frames
found 118 visible text samples with their top row alternating between crop
rows 89 and 95: a six-pixel displacement in the recording. The video and
measurement are referenced under `artifacts/research/20261008/user-video/`.

The CPU presentation backend previously selected odd or even scanlines and
duplicated each active scanline. Switching the selected field changes the
apparent position of thin text strokes. This is host presentation behavior;
the game font, icons and original game files are unchanged.

Interlaced field-mode presentation now blends the current line-doubled field
with the immediately preceding opposite field. History stores unfiltered
pixels separately for each parity, so repeated presentation cannot recursively
blur the picture. History is invalidated on reset, missing output, progressive
mode or a size change. Fields separated by a gap are not blended. Progressive
and interlaced frame-mode output retain their original presentation path.

This is temporal field blending, not motion-adaptive deinterlacing. It can
soften moving edges over one field interval. It does not change guest timing,
controller mappings or game content, and does not solve the card-format issue.

Regression validation checks opposite-field stability, repeated-field identity,
preservation of both fields' color contributions, opaque output, skipped-field
handling and progressive-mode transitions. `artifacts/verification/field-blend.json`
records 483/483 C++ and 101/101 Python tests passing, plus three tooling checks.

The final runner build succeeded in 144.1 seconds. RE4 run
`20261008T032356Z-e9b9c3b7` was observed for 151.5 seconds, reaching virtual field
940. Twelve captured system-data-prompt frames from presentation ticks 6600
through 7920 include both field parities; all twelve decoded RGB images are
identical and the text top row remains 136. Evidence and the exact runner hash
are in `artifacts/research/20261008/field-blend-runtime-proof.json`. The observation
ended at its configured timeout, with no detected fault patterns. This validates
the static prompt, not every moving scene or the outstanding save functionality.
