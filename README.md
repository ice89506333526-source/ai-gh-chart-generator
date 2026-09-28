# AI Guitar Hero Chart Generator

Turn an MP3 into a playable **Guitar Hero III (PC)** custom song — automatically.

Pick a song, press one button, and get a `notes.chart` + `song.wav` package ready
to import with GHTCP. The charts also work in **Clone Hero** out of the box.

![App screenshot](screenshots/chart%20generator1.jpg)

- **Expert** track: melodic contour mapping (frets follow the melody), 2-note
  chords, sustains, Star Power, playability-revised (no sub-80 ms attack pairs)
- **Hard** track: independent 4-lane design on a steady half-beat grid
- Practice sections (Part 01…NN) baked into the chart
- Optional vocal isolation for full-band songs (Demucs separation)
- Game mix with guitar pushed forward and vocals pulled back

> Works best on guitar-driven tracks (solo guitar, fingerstyle covers, rock
> songs with a clear guitar). Chart quality depends on the source mix.

## How it works

```
MP3 ──► tempo grid fit ──► Basic Pitch transcription ──► noise/click filters
     ──► onset grouping ──► melodic contour fret mapping ──► sustains/HOPO/SP
     ──► <80 ms revision ──► strict validation ──► song.wav + notes.chart
```

Under the hood: librosa (tempo), Basic Pitch ICASSP 2022 (note transcription),
Demucs htdemucs_6s (optional stem separation), pure Python chart logic.

## Download / install

Two ways:

1. **Prebuilt exe** (Windows, no Python needed):
   download `AI-GH-Chart-Generator.exe` from
   [Releases](../../releases) (~420 MB — TensorFlow inside).
   Windows SmartScreen may warn on first run ("Unknown publisher") —
   click *More info → Run anyway*.
2. **From source** (Python 3.11+, any OS where the libs install):
   ```bash
   pip install librosa soundfile numpy basic-pitch pillow
   python src/gh3_maker_gui.py
   ```

Optional (vocal isolation only): a second Python env with
`demucs` + `torch`. Without it, everything else still works.

## Using the app

1. **Open song** — choose an mp3/wav/flac/ogg, type a song ID (latin letters).
2. **Settings** (usually untouched):
   - manual BPM override if auto-detection misses;
   - *"Make easier"* — sparser attacks (`--min-gap 0.114` equivalent);
   - *"This is a full song with vocals"* — separate the guitar stem first;
   - Hard track on by default.
3. **Convert** — takes ~1 minute (plus 1–3 min if separation is enabled).
4. **Listen** to two previews: tempo clicks and synthesized notes. If they
   sound wrong, fix settings and re-convert.
5. **Confirm** → **Open folder** → import `notes.chart` + `song.wav` via GHTCP
   (GH3 PC) or drop the folder into Clone Hero's songs directory.

In game: use **Practice → Part NN** sections to drill hard spots.

## Tips for good charts

- Clean guitar or fingerstyle covers → perfect charts, no separation needed.
- Full-band songs → enable vocal separation; the chart follows the guitar stem.
- Too hard? Re-convert with "Make easier" checked.
- Clicks drift from the beat? Set the BPM manually.

## Known limitations

- Transcription is a model, not a human: expect a few wrong notes per song.
  The listening previews let you catch the bad ones before importing.
- Only 5-fret (GH3-style) lead guitar charts. No drums/bass/vocals tracks.
- Expert/Hard only (no Medium/Easy).
- Windows-focused (exe); the Python source also runs on Linux/macOS.

## Credits

- [Basic Pitch](https://github.com/spotify/basic-pitch) by Spotify — note transcription
- [Demucs](https://github.com/adefossez/demucs) by Meta — source separation
- [librosa](https://librosa.org/) — audio analysis
- GHTCP community — GH3 PC custom song tooling

If this tool saved you time and you feel like supporting the author:

- **International:** USDT on TON — `UQDFdVjxx81PCZFTiH8P9DKk89f48jccmBKbEjtMoWaAFvyb`
  (scan the QR from the app's ♥ button with any wallet app)
- **Россия:** карта **2204 3206 1512 3140** (Озон Банк) — QR в приложении

## License

MIT — see [LICENSE](LICENSE).
