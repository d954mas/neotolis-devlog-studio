# devlog — reusable video production pipeline

Engine + CLI + web tools shared across multiple devlog projects. Designed
around a single source of truth (`beats.py`) that drives composition,
teleprompter, and review tools.

## Architecture

```
common/devlog/                  ← reusable engine (this folder)
  types.py                      Design, Palette, Fonts, Beat, Chunk, Scene, Edit
  render/                       plate, overlay, image, scene, compose
  audio/                        process_beat_audio, transcribe
  charts/                       (project-agnostic chart primitives)
  web/                          recorder.html, preview.html, serve.py
  cli.py                        `devlog` command
  cut.py                        clip + reframe utility for reels

<project>/                      ← per-video project (e.g. trolley)
  shared/palette.py             brand colors + fonts (one per project)
  edits/                        each subfolder = one output (YT, reel, ...)
    <name>/
      design.py                 resolution + design tokens
      beats.py                  Beat dict + CONCAT_ORDER + OUTPUT
      __init__.py               assembles them into EDIT = Edit(...)
  data/                         all assets (audio, video, images, charts)
  web/                          optional per-project HTML tools
```

## Quickstart for a new project

```powershell
# 1) Create a clean project scaffold
dl.bat new newproject

# Or create it directly from a rough script
dl.bat new-video newproject --script script.md

# 2) Update the brand palette if desired
# Edit: newproject\shared\palette.py

# 3) Convert a rough script into starter beats, then edit the result
dl.bat import-script script.md --out newproject\edits\youtube\beats.py

# Or replace beats manually
# Edit: newproject\edits\youtube\beats.py
#   - update audio/words paths under newproject\data\finalize\
#   - rewrite chunks for your content
#   - set OUTPUT filename

# 4) Record VO, process audio
dl.bat audio newproject.edits.youtube intro my_take1.webm

# 5) Validate and render
dl.bat check newproject.edits.youtube
dl.bat iter newproject.edits.youtube -j 6
dl.bat render newproject.edits.youtube --final

# Or render one beat at a time
dl.bat compose newproject.edits.youtube intro
```

## CLI reference

| Command | What it does |
|---|---|
| `dl render [edit]` | Render every beat in `edit.order`, then concat to `edit.output` |
| `dl render <edit> --beat <id>` | Render one beat, skip concat |
| `dl iter [edit]` | Fast draft render shortcut: 540p, draft quality, cache-aware |
| `dl final [edit]` | Final render shortcut: `[final]` config, deep preflight, asset warnings |
| `dl compose [edit] <id>` | Same as `render --beat <id>` (alias); `dl compose b4` uses default edit |
| `dl concat [edit]` | Concat already-rendered beat videos into `edit.output` |
| `dl check [edit]` | Validate assets, words JSON, chunk ranges, and scenes before rendering |
| `dl doctor` | Check local FFmpeg/Python dependencies |
| `dl beats [edit]` | Show beat durations, chunk counts, and render status |
| `dl stale [edit]` | Show missing renders or renders older than inputs |
| `dl assets [edit]` | Show used, missing, unused, and low-resolution assets |
| `dl stock search/download` | Search/download stock B-roll into project assets with manifest |
| `dl preview-chunk <beat> <chunk>` | Render one chunk to a still PNG for fast visual checks |
| `dl scratch-tts <beat>` | Generate local Windows SAPI scratch voiceover for timing |
| `dl gen [spec.json] --out <path>` | Render generated infographic PNG/MP4 assets from a JSON spec or sample |
| `dl gen-html <dir> --out <path>` | Render optional Hyperframes HTML/GSAP motion assets |
| `dl smoke` | Run unit tests + `check` + `beats` as a fast self-test |
| `dl cache-info` | Show render cache entry count and size |
| `dl cache-prune --older-than-days N` | Remove old render cache entries |
| `dl script [edit]` | Export voiceover script as Markdown |
| `dl shotlist [edit]` | Export chunk/scene shotlist as Markdown |
| `dl import-script <file> --out <beats.py>` | Convert rough text/Markdown into starter `beats.py` |
| `dl new <project>` | Create a clean project scaffold |
| `dl new-video <project> --script <file>` | Create a scaffold and import script into `beats.py` |
| `dl audio <edit> <id> <recording>` | Preprocess + loudnorm + Whisper a take |
| `dl transcribe <wav> <out.json>` | Standalone Whisper run |
| `dl serve <edit> [--port 8080]` | Local server: recorder + preview + `/api/project` |
| `dl cut <video> <range> --out <path> [--reframe MODE]` | Clip range from a video, optional reframe for reels |

Useful validation/transcription options:

```powershell
dl check <edit> --deep                  # also ffprobe video durations / offsets
dl check                                # uses default_edit from devlog.toml
dl iter                                 # 540p draft render shortcut
dl iter --beat b4                       # quick single-beat iteration
dl iter --stale                         # render only stale 540p draft beats
dl render                               # uses default width/quality/parallel from devlog.toml
dl render --final                       # [final] settings + final preflight
dl final                                # same final path, shorter
dl compose b4                           # render one beat from the default edit
dl watch --beat b4                      # check + rerender one beat on source changes
dl smoke                                # tests + check + beats
dl smoke --skip-tests                   # faster check + beats only
dl stale --width 540p --quality draft   # what needs rerendering
dl assets --width 4k                    # missing/unused/low-res asset report
dl shotlist --suggest-broll --out data/review/shotlist_broll.md
dl stock search "server logs" --source pexels --aspect 16:9
dl stock search-candidates data/review/broll_candidates.json --source pexels
dl stock download data/review/stock_search.json --out data/assets/stock
dl preview-chunk b04 2 --out data/review/b04_c02_preview.png
dl scratch-tts b04
dl gen --sample bar --out data/infographics/sample_bar.mp4
dl gen chart.json --out data/infographics/my_chart.mp4 --width 540p
dl gen-html data/hyperframes/bar_demo --init
dl gen-html data/hyperframes/bar_demo --out data/infographics/bar_demo.mp4 --quality draft
dl cache-info                           # render cache size
dl cache-prune --older-than-days 14     # clean old cache entries
dl script --out data/review/script.md   # VO script export
dl shotlist --out data/review/shotlist.md
dl import-script script.md --out edits/youtube/beats.py
dl doctor --with-whisper                # include Whisper import check
dl beats <edit> --width 540p --quality draft --missing-only
dl audio <edit> <beat> <take.webm> --language en --model small
dl transcribe data/audio.wav data/words.json --language ru --model medium
```

Render quality presets:

| Preset | Typical use |
|---|---|
| `--quality draft` | Fast 540p iteration, ultrafast encode |
| `--quality preview` | Reviewable intermediate render |
| `--quality upload` | YouTube upload render with higher audio bitrate |
| `--quality master` | Slower archival/high-quality H.264 render |

Edit path is a Python dotted module like `trolley.edits.youtube`. The CLI
auto-detects project root from the module location and runs each command
with cwd set to the project root, so paths in `beats.py` stay relative
(`data/finalize/...`).

## Multiple edits per project

The model is "one folder per output". For a YouTube video + two reels of
the same project:

```
trolley/edits/
  youtube/        1920x1080, full 4-min video
  reel_30k/       1080x1920, short reel about the 30k lines moment
  reel_wavedash/  1080x1920, Wavedash announcement
```

Each subfolder has its own `design.py` (resolution + token overrides) and
its own `beats.py` (typically much shorter for reels — different VO, fewer
chunks). All edits share the same `data/` assets and the same
`shared/palette.py`, so the brand stays consistent across formats.

**Vertical reels — design philosophy:** the engine doesn't try to
auto-adapt a horizontal layout into vertical. Vertical reels are written
as their own beats with text sizes and overlay positions chosen
specifically for 9:16. This produces a better result than any automatic
crop. For quick clips out of a finished video, use `dl cut` with
`--reframe crop_center` instead.

## Adding a new edit

```python
# trolley/edits/reel_30k/design.py
from devlog.types import Design
from trolley.shared.palette import TROLLEY_PALETTE, TROLLEY_FONTS

DESIGN = Design(
    resolution=(1080, 1920),
    fps=30,
    palette=TROLLEY_PALETTE,
    fonts=TROLLEY_FONTS,
    underline_width=270,    # baseline 480, scaled for vertical
)
```

```python
# trolley/edits/reel_30k/beats.py
from devlog.types import Beat, Chunk
from trolley.shared.palette import TROLLEY_PALETTE as PAL

BEATS = {
    "main": Beat(
        audio="data/reels/reel_30k_audio.wav",
        words="data/reels/reel_30k_words.json",
        chunks=[
            Chunk(words=(0,3), kind="plate", text="30 000\nСТРОК", size=400,
                  red_underline=True, line_gap_ratio=0.04),
            # ... more chunks ...
        ],
        face="full",
        vo="Тридцать тысяч строк кода ...",
    ),
}
CONCAT_ORDER = ["main"]
OUTPUT = "data/reels/reel_30k.mp4"
```

```python
# trolley/edits/reel_30k/__init__.py
from devlog.types import Edit
from .design import DESIGN
from .beats import BEATS, CONCAT_ORDER, OUTPUT

EDIT = Edit(name="reel_30k", design=DESIGN, beats=BEATS, order=CONCAT_ORDER, output=OUTPUT)
```

Then `dl render trolley.edits.reel_30k`.

`dl new <project>` also copies `trolley/.claude/agents/vo-reviewer.md` and
`video-reviewer.md` into the new project when those template files exist.

## Beat / Chunk reference

See `common/devlog/types.py` for the full dataclass definitions. Key fields:

**Beat:**
- `audio`, `words` — paths to wav + Whisper JSON
- `chunks` — ordered list of `Chunk` objects
- `scene` — optional beat-wide background (overridden by chunk-level scene)
- `title`, `vo`, `stage`, `face` — production metadata for recorder/preview

**Chunk kinds:**
- `plate` — full-screen centered text (with optional bg image, underline, accent)
- `overlay` — text band/card/hero over a scene
- `image` — full-bleed image with optional caption pill or framed-card wrap
- `video` — video segment (with `offset` for seek)

**Same-source merging:** consecutive chunks pointing at the same scene
`src` collapse into one continuous segment — the background plays through
seamlessly while overlay text changes. The first chunk's offset is used;
subsequent chunks' offsets are ignored (don't try to "skip ahead" within a
shared scene by setting per-chunk offsets).

## Web tools

The Studio lives at `/devlog/studio.html` and loads beats from
`/api/project`. It combines script view, structure view, recording,
take processing, quick 540p beat render, and reviewer feedback display.
The simpler recorder remains at `/devlog/recorder.html` for focused VO
capture.

## Migrating from scripts/ (one-time)

The legacy `scripts/compose_beat.py`, `process_beat_audio.py`,
`whisper_words.py`, and `serve.py` in the trolley project root are
preserved for reference but superseded by the `dl` CLI. The migration:

| Legacy command | New equivalent |
|---|---|
| `python scripts/compose_beat.py <beat>` | `dl compose <edit> <beat>` |
| `python scripts/process_beat_audio.py <beat> <rec>` | `dl audio <edit> <beat> <rec>` |
| `python scripts/whisper_words.py <wav> <out>` | `dl transcribe <wav> <out>` |
| `python serve.py` | `dl serve <edit>` |
| Hand-rolled ffmpeg concat | `dl concat <edit>` |
