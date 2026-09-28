# Changelog

## v1.0 — 2026-09-28

First public release.

- Expert track: melodic contour fret mapping (rolling 8-note window),
  2-note chords, sustains, Star Power, automatic playability revision
  (no attack pairs closer than 80 ms)
- Hard track: independent 4-lane design on a steady half-beat grid
- Practice sections (Part 01…NN) baked into every chart
- Optional guitar isolation for full-band songs (Demucs htdemucs_6s)
- Game mix export with guitar pushed forward, vocals pulled back
- Bilingual UI (English / Russian), listening previews before export
- Windows exe (TensorFlow + Basic Pitch inside) and Python source

## v1.0.1 — 2026-09-28

- **Fix**: donation QR now shows correctly in the "Thank the author" window
  (the PNG was missing from the exe bundle; both QR images are now embedded
  with a fallback, and the QR is regenerated straight from the address)
- Source bundle: both QR images included in `src/`, build command updated

Planned:

- Chart quality presets (casual / balanced / dense)
- Bass and drums stubs investigation
- Per-song feedback loop for noise-filter tuning
