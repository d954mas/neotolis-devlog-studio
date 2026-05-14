# Trolley Devlog — Pipeline Reference

> **Orchestrator instructions:** read `..\common\PIPELINE.md` first. That's how
> to handle free-form user requests ("улучши b4", "посмотри финал", etc.) and
> when to spawn `vo-reviewer` / `video-reviewer` agents.

## Project

YouTube devlog for "Not a Trolley Problem" (AI-built game, Gamedev.js Jam 2026).
- Runtime: ~3:57, Russian-language VO
- Target aesthetic: Kurzgesagt/sci-pop
- Current iteration: **iter_86** (shipped, new pipeline)

Game source: `C:\projects\game-ai-gamedevjs2026`
Devlog source: `C:\projects\devlogs\trolley` (this repo)

---

## Pipeline (new — see `..\common\README.md` for full docs)

The renderer lives in `..\common\devlog\` and is driven by:
- `shared\palette.py` — brand colors + fonts
- `edits\youtube\design.py` — 1920x1080 design tokens
- `edits\youtube\beats.py` — **single source of truth** for all beats

CLI from `C:\projects\devlogs\`:
```
dl render trolley.edits.youtube                # render all + concat
dl compose trolley.edits.youtube <beat_id>     # render one beat
dl audio   trolley.edits.youtube <beat> <rec>  # process recording → wav + words.json
dl serve   trolley.edits.youtube               # web tools at /devlog/recorder.html
```

The legacy `scripts/compose_beat.py` etc. below are kept for reference but
superseded — use `dl` for new work.

---

## Directory Layout

```
shared/
  palette.py             # ← TROLLEY_PALETTE, TROLLEY_FONTS (used by all edits)

edits/
  youtube/               # ← YT edit (1920x1080)
    design.py            # Design instance
    beats.py             # Beat dict + CONCAT_ORDER + OUTPUT
    __init__.py          # EDIT = Edit(...)
  reel_30k/              # ← example vertical reel (1080x1920)
    design.py beats.py __init__.py

scripts/                 # ← LEGACY (pre-pipeline; kept for reference)
  compose_beat.py        # superseded by `dl compose`
  build_infographics.py  # still used for project-specific charts
  whisper_words.py       # superseded by `dl transcribe`
  process_beat_audio.py  # superseded by `dl audio`

data/
  finalize/              # ← working directory for all pipeline outputs
    <beat>_audio_final.wav
    <beat>_words.json
    <beat>_video_1080p.mp4
    concat_iter<N>.txt
    iter<N>.mp4
    frames_iter<N>/      # 1-frame-per-5s stills for review
  infographics/          # generated MP4/PNG infographics
  trailer/               # clean_gameplay.mp4, clean_gameplay_extended.mp4
  itch/                  # screenshots: snap_city.png, snap_suburbs.png, etc.
  recordings/            # raw voice .webm takes
```

---

## Design System (locked)

```python
COL_BG       = (26, 22, 18)    # #1a1612 — warm dark background
COL_GOLD     = (232, 182, 71)  # #e8b647 — primary accent, axis labels, headlines
COL_GOLD_DIM = (224, 174, 69)  # subtitles, notes (96% gold)
COL_RED      = (192, 57, 43)   # #c0392b — punchline accent, red_underline

FONT_BOLD  = "C:/Windows/Fonts/bahnschrift.ttf"   # display / numbers
FONT_BLACK = "C:/Windows/Fonts/tahomabd.ttf"      # Cyrillic text

Resolution: 1920×1080 @ 30fps
FAST mode:  960×540 @ 24fps (set FAST=1 env var, ~3× faster)
```

---

## Beat Order (concat)

```
a0-1 → a1-1 → a1-2 → b3 → b4 → a2-1 → a2-2 → a2-3 → a2-4 → a2-5 → a3-6 → b10
```

Beats NOT in current cut (exist in BEATS_VISUAL but excluded from concat):
`a0-2`, `a3-1`, `a3-2`, `a3-3`, `a3-4`, `a3-5`

---

## Iteration Workflow

### Full cycle (one iteration):

```bash
# 1. Edit compose_beat.py or build_infographics.py

# 2. Regenerate any changed infographic animations
python scripts/build_infographics.py

# 3. Re-render affected beats
python scripts/compose_beat.py <beat_id>

# 4. Write concat file  data/finalize/concat_iter<N>.txt
# (copy previous, same format)

# 5. Concat
ffmpeg -y -f concat -safe 0 -i data/finalize/concat_iter<N>.txt -c copy data/finalize/iter<N>.mp4

# 6. Extract review frames (1 per 5s)
mkdir data/finalize/frames_iter<N>
ffmpeg -y -i data/finalize/iter<N>.mp4 -vf "fps=1/5" data/finalize/frames_iter<N>/frame_%04d.jpg

# 7. Run producer review (yt-reviewer agent)
```

### Fast render (iteration speed):
```bash
FAST=1 python scripts/compose_beat.py <beat_id>
```

---

## compose_beat.py — Key Patterns

### Chunk kinds

| kind | what it does |
|---|---|
| `plate` | Full-screen centered text with optional subtitle + red underline |
| `overlay` | Text band (bottom or top) over a scene image/video |
| `image` | Full-bleed image, optionally with `label` or `framed_card` |
| `video` | Video clip as background scene |

### Chunk fields

```python
{ "words": (start_idx, end_idx),   # inclusive word range from words.json
  "kind": "plate"|"overlay"|"image"|"video",
  "text": "HEADLINE",
  "subtitle": "sub text",          # plate only
  "subtitle_color": COL_GOLD_DIM,
  "color": COL_GOLD,               # plate text color
  "bg": COL_BG,                    # plate bg color
  "size": 280,                     # font size px (at 1080p)
  "red_underline": True,           # red bar under headline
  "line_gap_ratio": 0.04,          # tighter multiline spacing
  "bg_image": "data/itch/snap_city.png",  # blended bg photo
  "bg_opacity": 0.45,              # alpha for bg_image blend
  "scene": { "kind": "image"|"video", "src": "...", "offset": 0.0 },
  "label": "CAPTION TEXT",        # image label pill
  "label_style": "default"|"branded",  # branded = 90px + red bar
  "framed_card": True,            # card inset with border
  "ken_burns": True,              # 1.0→1.10× zoom over clip
  "position": "bottom"|"top",    # overlay band placement
  "style": "card"|"default",     # overlay card = centered large
}
```

### bg_image compositing formula
```python
bg_base + (image - bg_base) * opacity
```
All chart animations use `snap_city.png` at `opacity=0.20` with `GaussianBlur(14)`.

### overlay_label styles
- `default`: 70px, 30px pad, dark pill, gold text
- `branded`: 90px, 44px pad, dark pill, gold text + 6px red left-border

---

## build_infographics.py — Animations

All 5 animated infographics live in `data/infographics/`:

| File | Function | City bg |
|---|---|---|
| `hype_curve_anim.mp4` | Hype cycle curve draws L→R | yes (0.20) |
| `workflow_diagram_anim.mp4` | Claude Code workflow boxes appear | yes (0.20) |
| `daily_views_anim.mp4` | Daily itch views bar chart grows | yes (0.20) |
| `commits_chart_anim.mp4` | 13-day commit count bars grow | yes (0.20) |
| `timeline_13days_anim.mp4` | Dev timeline nodes appear | no (clean dark) |

Regenerate all:
```bash
python scripts/build_infographics.py
```

Axis label colors: all charts use `COL_GOLD` (not `COL_GOLD_DIM`) as of iter_79.

---

## Audio Processing

### words.json format
```json
{
  "audio": "data/finalize/<beat>_audio_final.wav",
  "duration": 19.2,
  "language": "ru",
  "text": "transcribed text...",
  "words": [
    {"word": "Полгода", "start": 0.6, "end": 1.1, "prob": 0.98},
    ...
  ]
}
```

### Trimming audio (removes phrases from start)
```bash
# Backup first
cp data/finalize/<beat>_audio_final.wav data/finalize/<beat>_audio_final_orig.wav
# Trim from CUT_TIME seconds
ffmpeg -y -ss <CUT_TIME> -i data/finalize/<beat>_audio_final_orig.wav data/finalize/<beat>_audio_final.wav
```
After trimming: remove trimmed words from `words.json`, shift all timestamps by `-CUT_TIME`, update word indices in compose_beat.py chunks.

---

## Known False Positives (producer review)

1. **Dark frame ~t=203s** (frame_0041 in iter_80): daily_views animation cold start — city bg builds from near-zero. Python brightness scan confirms mean=46–56. Not a defect.

2. **a2-1 background = b4 chart**: both beats intentionally use `files_breakdown.png`. Producer may flag as "wrong background" — it is correct.

3. **commits_chart 1.7s window** (~t=67.6–69.3s in full video): chart shows during b4 words (4–5), only ~1.7s. Falls between 5s sample frames. Chart IS present; sampler misses it.

---

## Game Trailer (TrailerDirector.js)

File: `C:\projects\game-ai-gamedevjs2026\src\features\trolley\trailer\TrailerDirector.js`

Current timeline (iter_80, TOTAL=30s):
- 0.0–4.5s: Village (hook)
- 4.5–9.5s: Suburbs crossfade (350ms half)
- 9.5–15.0s: City + upgrade cascade (350ms half)
- 15.0–21.0s: Choice triple (3 modals, 280/250ms crossfades)
- 21.0–27.0s: Hell/chaos finale (400ms half crossfade)
- 27.0–30.0s: Title overlay

Activate: `/?trailer=1` in browser URL.

---

## Current Beat Audio Files

All finals in `data/finalize/`:

| Beat | Duration | Notes |
|---|---|---|
| a0-1 | ~12s | Opening shock claim |
| a1-1 | ~25s | Jam context + idea |
| a1-2 | ~15s | Day 1 mechanics |
| b3 | ~32s | Game showcase (extended gameplay bg) |
| b4 | ~16s | 30k lines / 273 commits / ИИ climax |
| a2-1 | ~19s | iter_80: trimmed 4.8s (removed redundant phrase) |
| a2-2 | ~35s | Hype curve + РЕАЛЬНОСТЬ ПРОЩЕ |
| a2-3 | ~25s | 3 AI principles |
| a2-4 | ~12s | Art pipeline |
| a2-5 | ~18s | Critique response |
| a3-6 | ~15s | Submit → daily views tease |
| b10 | ~30s | Results reveal (players + Wavedash) |

---

## Whisper Transcription

```bash
python scripts/whisper_words.py data/finalize/<beat>_audio_final.wav
# writes data/finalize/<beat>_words.json
```

Model: `large-v3` (default). Output includes word-level timestamps.

---

## Useful One-liners

```bash
# Check video duration
python -c "from moviepy import VideoFileClip; c=VideoFileClip('data/finalize/iter80.mp4'); print(c.duration); c.close()"

# Scene detection (find cut timestamps)
ffprobe -v quiet -show_entries "frame=pts_time" -of csv -f lavfi "movie=<file.mp4>,select=gt(scene\,0.4)"

# Scan frame brightness (verify dark-frame false positive)
python -c "
import numpy as np
from PIL import Image
img = np.array(Image.open('data/finalize/frames_iter80/frame_0041.jpg'))
print('mean brightness:', img.mean())
"
```
