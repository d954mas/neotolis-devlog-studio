# AGENTS.md — instructions for AI agents working on this project

This file is for AI agents (Claude Code and similar) — quick orientation
on how this workspace works, defaults to follow, and which skill/agent to
invoke for which task. Humans should read `README.md` and `common/PIPELINE.md`.

## Workspace shape

```
devlogs/                   ← workspace root, git repo, contains common/ + projects
  common/                  Reusable engine (versioned with workspace)
    devlog/                Python package (render, audio, cache, cli, web)
    PIPELINE.md            Orchestrator playbook (READ FIRST for any iteration task)
    README.md              Quickstart for new projects
  trolley/                 First project — Not a Trolley Problem devlog
  newproject/              Future projects sit as siblings here
  dl.bat / dl              CLI wrapper (Windows / POSIX)
```

## Defaults — do these without being asked

| When user wants | Default action | Skill |
|---|---|---|
| Quick result from beats.py edit | `dl iter --stale -j 4..8` | CLI |
| One-beat iteration | `dl iter --beat <id>` or Studio `Render 540p` | CLI/Studio |
| Record → process → render beat | Studio `Process + Render` on selected beat | Studio |
| Auto-rebuild on save | `dl watch --beat <id>` for targeted work | CLI |
| Final upload-ready render | `dl final [edit]` | CLI |
| Start a new video from script | `dl new-video <project> --script <file>` | CLI |
| Improve a rendered beat/video | Loop: render → reviewer → mech fixes → repeat | workflow |
| Create simple chart/counter/timeline infographic | `dl gen` from JSON/sample, then use as `Scene(kind="video"|"image")` | CLI |
| Create rich HTML/GSAP motion graphic | `dl gen-html <dir> --init`, edit HTML/CSS/JS, render to MP4 | CLI/Hyperframes |
| Cut clip for reel/short | `dl cut` with reframe | CLI |
| Iterate a reel/short edit | `dl reel-preview <edit>` before any upload render | CLI |
| Review a recorded VO take | Spawn `vo-reviewer` agent on `.webm` | (agent) |
| Review composed beat / iter video | Spawn `video-reviewer` agent | (agent) |
| Design infographic/motion asset plan | Spawn `motion-infographic-designer` | (agent) |
| Reflect after a devlog run | Spawn `devlog-reflector`, use `devlog-reflection` | agent/skill |
| Create/review YouTube thumbnail | Spawn `thumbnail-designer`, use `devlog-thumbnail` | agent/skill |

## Critical engineering defaults

1. **FFmpeg engine is the default** (`compose_ffmpeg.py`). Don't suggest `--engine moviepy` unless the user reports a visual bug specific to the ffmpeg pipeline. MoviePy fallback is kept for safety but is 5-25× slower.

2. **Cache is correct and on by default.** Hash includes engine source, design, asset mtimes, draft/gpu flags. Engine code changes auto-invalidate. Don't pass `--no-cache` unless debugging cache itself.

3. **Resolution and quality are runtime flags, not code constants.** Use `dl iter --stale` for 540p draft iteration and `dl final` for upload-ready renders. Engine is resolution-independent via `design.px()` — same `beats.py` renders correctly at any resolution.

4. **Parallel render** (`-j 4..8`) is safe and useful when rendering many beats. Each worker is its own Python process. Per-worker cache writes are atomic.

5. **Run `dl check` before expensive renders.** Use plain `dl check` during normal iteration and `dl check --deep` after changing video assets or scene offsets. These use `default_edit` from `devlog.toml`.

6. **Use `dl doctor`, `dl beats`, and `dl stale` for triage.** `dl doctor` verifies local dependencies; `dl beats <edit> --missing-only` shows durations and missing rendered beat files; `dl stale --width 540p --quality draft` shows renders older than current inputs/cache state.

7. **Prefer targeted watch for one-beat iteration.** `dl watch --beat <id>` runs `check` and re-renders only that beat when `beats.py`, `design.py`, or renderer files change.

8. **For reels/shorts, use `dl reel-preview` before upload renders.** It renders a 540p draft, writes a contact sheet, and extracts chunk midpoint frames. Use this for text size, story clarity, ending, and safe-zone checks. Run 1080/upload only after the preview passes.

9. **Use `dl smoke` after engine changes.** `dl smoke` runs tests plus `check` and `beats`; `dl smoke --skip-tests` is the faster sanity pass.

10. **Use `dl assets --width 4k` before final render.** Missing assets are blockers; low-res warnings include severity, affected beat ids, and recommended action.

11. **Inspect cache before clearing it.** Prefer `dl cache-info`; use `dl cache-prune --older-than-days N` for old entries. Full `cache-clear` is still a rare debugging action.

12. **Use `dl script`, `dl shotlist`, `dl import-script`, and `dl new-video` for planning.** `beats.py` remains the source of truth; `import-script` generates starter chunks from a rough script, and `new-video` creates a scaffold plus generated `beats.py`.

13. **Studio is the default daily UI.** Run `dl serve [edit]`, open `/devlog/studio.html`, then use: select beat → record take → `Process + Render` → preview the 540p draft on the Script tab. The separate recorder page remains available for focused capture.

14. **Per-chunk fade-in/out is currently disabled in ffmpeg engine** — known interaction with overlay alpha that broke text bands. Plates and overlay bands pop in/out abruptly. Don't try to "fix" the missing fade with hacks unless you have a verified ffmpeg alpha-fade approach. Crossfade between scenes (xfade) works fine.

15. **Generated infographics are first-class assets.** Use `dl gen` for simple branded charts/counters/timelines/workflow diagrams. It uses `common/devlog/anim.py`, `charts.py`, and `generated.py`, with only Pillow + NumPy + FFmpeg. Render to `data/infographics/*.mp4` or `.png`, then reference the file from `beats.py` through `Scene(kind="video", src="data/infographics/<file>.mp4")` or `Scene(kind="image", ...)`.

16. **Hyperframes is optional for rich motion graphics, not the core renderer.** Use `dl gen-html` when the visual needs HTML/CSS layout, GSAP animation, dashboard-like UI, or complex motion that is awkward in Pillow. It runs `npx hyperframes render` via `common/devlog/hyperframes.py` and requires Node 22+, npm/npx, Chromium/Puppeteer download access, and FFmpeg. Keep Hyperframes projects under `data/hyperframes/<name>/` and render outputs under `data/infographics/`.

17. **Do not replace the devlog pipeline with Hyperframes or Remotion.** The main video remains `Beat`/`Chunk`/`Scene` + FFmpeg composition. Hyperframes/`dl gen` only produce asset clips that the existing pipeline consumes.

## Reel/short defaults

Before rendering an upload-quality reel, run this gate:

- **Standalone story:** first 2-4 seconds explain the product/context in voice, not only text.
- **No dependency on another reel:** avoid openings like "а еще", "теперь", "можно..." unless the product was just named.
- **Readable phone text:** main overlay should be short; subtitle should be a second readable line, usually `sub_ratio >= 0.5` for vertical reels.
- **Ending:** hold a deliberate final frame with site/product/CTA for about one second.
- **Preview first:** run `dl reel-preview <edit>` and inspect the contact sheet/keyframes before any `--quality upload` render.

## Infographic and motion workflow

Use this decision tree:

| Need | Use | Command |
|---|---|---|
| Bar chart, counter, timeline, simple workflow diagram | Native generator | `dl gen spec.json --out data/infographics/name.mp4 --width 540p` |
| Quick native generator sample | Native generator | `dl gen --sample bar --out data/infographics/sample_bar.mp4` |
| HTML/CSS/GSAP motion, dashboard, UI animation | Hyperframes bridge | `dl gen-html data/hyperframes/name --init`, edit HTML, then render |
| Math/whiteboard explanation | Consider external Manim asset, then import as video | Ask before adding new dependency |

Native `dl gen` JSON spec examples:

```json
{
  "type": "bar_chart",
  "title": "273 COMMITS",
  "subtitle": "13 DAY JAM",
  "values": [
    {"label": "D1", "value": 8},
    {"label": "D2", "value": 23},
    {"label": "D3", "value": 80}
  ],
  "highlight_index": 2
}
```

Supported native types: `bar_chart`, `timeline`, `workflow`, `counter`.

Hyperframes starter flow:

```powershell
dl gen-html data/hyperframes/bar_demo --init
# edit data/hyperframes/bar_demo/index.html
dl gen-html data/hyperframes/bar_demo --out data/infographics/bar_demo.mp4 --quality draft
```

After generation, connect the asset in `beats.py`:

```python
Chunk(words=(0, 5), kind="overlay",
      text="273 КОММИТА", subtitle="ЗА 13 ДНЕЙ",
      scene=Scene(kind="video", src="data/infographics/bar_demo.mp4"))
```

Run `dl check` after connecting generated assets. Run `dl assets --width 4k` before final.

## Improve-loop discipline

When running `/dl-improve` or auto-iterating on review feedback, the
orchestrator may **auto-apply** these `beats.py` changes without asking:

- `size`, `bg_opacity`, `subtitle_color`, `line_gap_ratio`, `sub_ratio`
- `red_underline`, `ken_burns`, `framed_card` flag toggles
- `position`, `style`, `fit`, `label_style`
- `src` (image swap) — **only if the new path exists in `data/`**
- Clear typos in `text` / `subtitle`

The orchestrator must **stop and ask** for:

- Any VO change (re-record needed)
- New asset that doesn't exist yet
- Structural changes (split/merge chunks, new chunk/beat)
- Word-index re-mappings
- Cross-beat changes

**Max 5 improve iterations per beat.** After 5, summarize and hand back to user.

## Spawning reviewer agents

Reviewers persist verdicts to `<project>/data/review/feedback.json` so the
studio UI displays them. Use Write tool inside the agent. Merge with existing
`vo` / `video` keys — don't overwrite.

Reviewer agents should be isolated from prior user corrections by default. Give them the artifact and neutral context, let them produce a blind verdict, then let the orchestrator run a separate regression checklist against known user constraints.

Before final handoff, the orchestrator must run the regression checklist: audio/music present and mixed, VO joins clean, no visual glitches, text/overlays inside safe zones, real product visuals where promised, thumbnail QA for YouTube packaging, and deliberate ending.

Canonical workspace agent templates:
- `.claude/agents/vo-reviewer.md` — audio take review (.webm)
- `.claude/agents/video-reviewer.md` — composed beat / full video / plan review
- `.claude/agents/motion-infographic-designer.md` — plans and generates chart/motion assets via `dl gen` / `dl gen-html`
- `.claude/agents/devlog-reflector.md` — post-run reflection: bottlenecks, missed gates, and pipeline improvements
- `.claude/agents/thumbnail-designer.md` — YouTube thumbnail concept, real-product compositing, and feed-size QA

Project-local copies/overrides live in `<project>/.claude/agents/`. The
current `trolley/.claude/agents/` files are a project-local copy for the
first project, not the canonical source. `dl new` copies from root
`.claude/agents/` into each new project.

## Don't

- Don't render at 4K during iteration (slow + separate cache entry).
- Don't `--no-cache` unless debugging cache.
- Don't write rendered MP4s, raw recordings, or large images into git (`.gitignore` covers this — verify if adding new asset types).
- Don't commit generated `data/infographics/*.mp4`, `data/hyperframes/*`, or `.build_cache.json` unless the user explicitly wants assets versioned.
- Don't invent file paths when applying `src` changes — always Glob/Read first.
- Don't use Hyperframes for simple counters/charts that `dl gen` can produce faster.
- Don't add Manim/Matplotlib/Remotion dependencies without asking; prefer the native generator first.
- Don't loop the improve cycle past 5 iterations without checking in with the user.
- Don't recommend `--engine moviepy` unless ffmpeg engine has a verified visual bug.
- Don't run `dl concat` separately from `dl render` — render handles concat unless `--no-concat`.

## Where the orchestrator lives

Pipeline docs:
- `common/PIPELINE.md` — full orchestrator playbook (improve loop, free-form-to-action map, stop conditions)
- `common/README.md` — pipeline reference, CLI, structure
- This file (`AGENTS.md`) — at-a-glance defaults
- `trolley/CLAUDE.md` — trolley project history (legacy, but useful for context)

Skills:
- `~/.claude/skills/dl-*` — user-level skills, work across all devlog projects in this workspace

Agents:
- `.claude/agents/` — canonical workspace templates copied by `dl new`
- `<project>/.claude/agents/` — project-local copies/overrides
