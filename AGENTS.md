# AGENTS.md — instructions for AI agents working on this project

This file is for AI agents (Claude Code / Codex) — quick orientation on how
this workspace works, defaults to follow, and which agent to spawn for which
task. The one-page draft path is `docs/QUICKSTART_V2.md`; the engine
contract is `docs/ARCHITECTURE_V2.md`.

## Workspace shape

```
devlogs/                     ← workspace root, git repo
  common/
    dlstudio/                Studio v2 engine: model → compile → IR → check → render (FFmpeg)
    quality/                 VQ-* quality-rule catalog (sync, audio, hook, motion, ...)
  docs/
    QUICKSTART_V2.md         full draft path on one page (cold-start entry)
    ARCHITECTURE_V2.md       v2 layering contract — read before engine work
    PLAN_STUDIO_V2.md        production plan (safe-fix / stop rules §2.2–2.3)
  <project>/                 each video project sits as a sibling of common/
    edits/<edit>/            __init__.py (module-level EDIT) + beats.py + design.py
    data/                    audio/ footage/ images/ music/ sfx/ fonts/
                             hyperframes/ infographics/ scratch/ recordings/
                             finalize/ review/ publish/
  dl2.bat / dl2              CLI wrapper (Windows / POSIX)
```

Edits are addressed by dotted module path (e.g. `myreel.edits.main`); the
default edit comes from `devlog.toml` `[v2] default_edit`. Orientation is
the `RESOLUTION` tuple in `design.py` — there is no separate format field.
`common/devlog` (v1) заморожен и обслуживает только старые проекты — не
использовать для новой работы.

## Defaults — do these without being asked

| When user wants | Default action |
|---|---|
| Quick result from a beats.py edit | `dl2 iter <edit> --stale -j 4` |
| One-beat iteration | `dl2 compose <edit> <beat>` |
| Watchable draft + review artifacts | `dl2 preview <edit>` → draft at `EDIT.output` + `data/review/contact_sheet.jpg` + `data/review/keyframes/` |
| Final upload-ready render | `dl2 final <edit>` (1080p, −14 LUFS loudnorm) |
| Start a new video | `dl2 new-video <project> --format vertical` (or `landscape`) |
| Scratch VO for a beat | `dl2 scratch-tts <edit> <beat>` → `dl2 transcribe <wav> <words.json>` → wire BOTH paths into the beat in `beats.py` |
| Process a recorded take | `dl2 audio <edit> <beat> <take>` (takes live in `data/recordings/`) |
| Record VO / takes / feedback UI | `dl2 studio <edit>` → http://127.0.0.1:8788 |
| Missing-asset / compile triage | `dl2 check <edit>` (its error list is the TODO); cache status: `dl2 beats <edit>` |
| Ground-truth timings | `dl2 ir <edit> --out ir.json` |
| Motion / infographic asset | `dl2 gen-html <asset> --init`, edit HTML, render to `data/infographics/` |
| Stock b-roll | `dl2 stock search` / `dl2 stock download` |
| YouTube package | `dl2 publish <edit>` → `data/publish/youtube_package.md` |
| Environment triage | `dl2 doctor` |
| Engine-work verification | `dl2 verify --changed` |

Agent routing:

| Task | Agent |
|---|---|
| Review a recorded VO take | `vo-reviewer` |
| Review composed beat / full draft / plan | `video-reviewer` |
| Hook check before recording | `hook-doctor` |
| Music choice + MusicRegion/Duck params | `music-supervisor` |
| Design/generate motion or infographic asset | `motion-infographic-designer` |
| YouTube packaging after final | `publish-packager` |
| Thumbnail creation / critique | `thumbnail-designer` |
| Post-run reflection | `devlog-reflector` |
| Engine architecture / render debugging | `deep-reasoner` (Opus) |
| Mechanical edits / already-decided plan | `fast-worker` (Sonnet) |

## Critical engineering defaults

1. **Checks are a built-in pre-render gate.** Every render path (`compose`,
   `iter`, `render`, `final`, `preview`, Studio API) compiles the edit and
   runs the mechanical checks first — errors block, draft may continue on
   warnings. Don't script a manual check before renders; use `dl2 check`
   for triage (missing assets, broken fonts, word-index errors).
2. **Cache is content-addressed and on by default.** Entries are MP4 +
   VO-stem pairs restored together; keys cover engine source, design,
   assets, fonts, and the resolution/quality profile. Don't pass
   `--no-cache` unless debugging the cache itself.
3. **Resolution profiles are orientation-aware runtime flags, not code.**
   Draft is the 540p-class profile (960×540 landscape / 304×540 vertical);
   delivery is 1080p (1920×1080 / 1080×1920) via `dl2 final`; 4K is
   3840×2160 / 2160×3840. Same `beats.py` renders at any profile.
4. **Parallel render is safe within one edit** (`-j 4..8`, one process per
   worker). Don't render two edits of the same project concurrently — they
   share `data/finalize/`.
5. **FFmpeg is the only backend.** No fallback engine. A render failure is
   a bug to fix (route to `deep-reasoner`), not a reason to switch engines.
6. **Fonts are validated assets.** A broken or missing TTF in `data/fonts/`
   is a check error, never a silent fallback; replacing a font file
   invalidates the cache.
7. **Draft first for a new reel.** Scaffold, provisional script, scratch
   VO, existing/stock/generated visuals, `dl2 preview`. Source capture is a
   short bounded step; use placeholders and replace next iteration.

## Reel defaults

- **Captions:** set `subtitles=True` on the beat — phrase captions are
  auto-grouped from the beat's words, styled by `Design.captions`. Don't
  hand-build caption chunks.
- **Goal in second 0–1:** first spoken sentence names the
  situation/problem/product with a viewer-facing hook (problem, number,
  failure, contrast, funny situation) — else rewrite/re-record before any
  visual polish.
- **Standalone:** no "а ещё / теперь / можно…" openings, no dependency on a
  prior reel.
- **Voice energy:** flat, disengaged VO is a re-record issue; visual edits
  can't hide it.
- **Motion floor:** no static screenshot run over ~3s — `ken_burns`,
  framed/inset cards, live footage, or a generated motion asset.
- **Readable phone text:** short overlay text; subtitle as a second
  readable line.
- **Ending:** hold a deliberate final frame with site/product/CTA ~1s.
- **Preview first:** inspect the `dl2 preview` contact sheet + keyframes
  before any delivery-quality render.

## Infographic and motion workflow — HyperFrames only

All generated motion/infographic assets go through the HyperFrames bridge
(there is no other generator in v2):

```bash
dl2 gen-html <asset> --init          # scaffold data/hyperframes/<asset>/
# edit index.html — deterministic seekable GSAP timelines in window.__timelines
dl2 gen-html <asset> --out data/infographics/<asset>.mp4 --quality draft
```

Requires Node 22+ / npx. Wire into `beats.py` as
`VideoShot(src="data/infographics/<asset>.mp4")` or
`Scene(kind="video", src=...)`. Generated assets are inputs to the normal
Beat/Chunk pipeline — never replace the pipeline with HyperFrames/Remotion.
Math/whiteboard needs (Manim etc.): ask before adding a dependency.

## Improve-loop discipline

Loop: draft (`dl2 preview`) → blind review → safe fixes → re-preview.
**Max 3 iterations by default, 5 hard cap** — then summarize and hand back.

Safe to apply without asking (PLAN_STUDIO_V2 §2.2): clear typos; `size`,
`bg_opacity`, `sub_ratio`, `line_gap_ratio`, `subtitle_color`; safe-zone
`position`, `style`, `fit`; decoration / `ken_burns` toggles; `src` swap
**only if the new path exists in `data/`**; wiring an existing asset;
creating/editing HyperFrames assets; re-rendering drafts; running review.

Stop and ask the user (§2.3): new real footage; final VO or any VO change;
meaning or structure changes (split/merge beats, new chunks/beats);
word-index re-mappings; contested product claims; a critical asset that
can't be substituted; reviewer demands a 6th iteration.

## Spawning reviewer agents

- Reviewers are **blind by default**: artifact + neutral context, no prior
  user corrections. The orchestrator runs a separate regression checklist
  against known user constraints afterward.
- Reviewers ground claims in facts: `dl2 ir <edit> --out ir.json` for
  timings, `dl2 check` output, ffprobe numbers, and the `data/review/`
  artifacts (contact sheet, keyframes) — never "looks fine".
- Verdicts persist to `data/review/feedback.json` — POST to the running
  `dl2 studio` `/api/feedback` (deep-merges; don't clobber other keys) or
  write the file directly, merging. **Every verdict must name the
  `artifact_path` of the exact MP4/take reviewed** plus `artifact_sha256`,
  `timestamp`, `verdict` (the server computes sha/timestamp from
  `artifact_path` when omitted — still always name the path).
- **Stale-feedback rule:** before trusting a stored verdict, recompute the
  artifact's sha256; a mismatch with `artifact_sha256` means the file
  changed since the review — the verdict is STALE, re-review it.
- Before final handoff the orchestrator runs the regression checklist:
  music present and mixed, VO joins clean, no visual glitches, text inside
  safe zones, real product visuals where promised, deliberate ending,
  thumbnail QA for YouTube packaging.

## Quality rules

`common/quality/` holds the VQ-* catalog (sync, audio, motion, hook, safe
zones, ending, real-product proof, resolution, word indices, assets).
Mechanical parts of VQ-SYNC/VQ-RES/VQ-WORDS/VQ-ASSET are enforced in code
(`common/dlstudio/src/dlstudio/check/`); the rest is judgment, checked
against the rule files — never assumed from "looks fine". Unverified ≠ pass.

## Don't

- Don't render 4K during iteration.
- Don't `--no-cache` unless debugging the cache.
- Don't commit rendered MP4s, recordings, `data/hyperframes/*` or
  `data/infographics/*` outputs unless the user wants assets versioned.
- Don't invent file paths for `src` changes — Glob/Read first (VQ-ASSET).
- Don't invent `dl2` commands or flags — `dl2 --help` is the surface.
- Don't reuse a feedback verdict whose `artifact_sha256` no longer matches.
- Don't loop improve iterations past the cap without checking in.
- Don't touch `common/dlstudio` internals for content work — engine changes
  route to `deep-reasoner` / `fast-worker` and end with `dl2 verify --changed`.

## Where things live

- `docs/QUICKSTART_V2.md` — full draft path (commands + output paths)
- `docs/ARCHITECTURE_V2.md` — engine contract and phase status
- `docs/PLAN_STUDIO_V2.md` — production plan, safe-fix/stop rules
- `.claude/agents/` — canonical workspace agent templates
- `<project>/.claude/agents/` — project-local copies/overrides
