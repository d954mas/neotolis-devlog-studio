# Studio v2 — Target Architecture

Status: **approved, in design → build**. Decisions locked 2026-07-16.

The current engine (`common/devlog/`, the `dl` CLI) is the **v1 prototype**.
It shipped 2 devlogs + ~7 reels and proved the concept: video as diffable
Python, word-index timing as the master clock, an agentic improve loop with
domain reviewers. v2 rebuilds it as a modular, extensible, production-quality
system. This document is the contract for that build.

## Locked decisions

| Decision | Choice |
|---|---|
| Legacy strategy | **Freeze.** `common/devlog` + `dl` stay for existing projects (trolley, neotolis edits). Bugfix-only (e.g. atomic cache write). No adapter layer, no old-vs-new pixel parity gate. v2 is for new videos. |
| Render backend | **One path: FFmpeg.** No MoviePy fallback in v2. Golden-frame tests are the regression net. |
| Authoring format | **Code-first.** `beats.py`-style Python DSL remains the source of truth (diffable, git-versioned, agent-legible). No GUI timeline, no JSON authoring. |
| Audio scope | **Full mix graph in Phase 2**: music beds spanning beat boundaries, sidechain ducking keyed by VO, SFX events anchored to word indices, beat-to-beat transitions, final-mix loudness normalization (-14 LUFS). |
| Studio UI | **Rewrite on Vite + TypeScript**, typed API (FastAPI/pydantic, OpenAPI → generated TS types). Node toolchain is already a workspace dependency (Hyperframes). |
| What carries over conceptually | Word-index timing model; content-addressable cache with engine-source hashing; draft/final quality tiers; the improve loop + reviewer agents; HIT_VIDEO_PRACTICES and reel gates (become the VQ rule catalog). |

## Package layout

```
common/dlstudio/            v2 engine (Python package, pyproject.toml, pinned deps)
  model/                    user-facing DSL: Edit, Beat, Chunk content types,
                            Style registry, Anim, Transition, AudioMix
  compile/                  beats.py -> Timeline IR (pydantic, JSON-serializable)
  check/                    all gates as code, run on IR + ffprobe facts
  render/
    graph.py                typed FFmpeg filter-graph builder (AST: nodes/pads/edges)
    beat.py                 per-beat render -> video + VO stem
    assemble.py             edit-level assembly: concat + transitions + mix graph
  cache/                    atomic, multi-level (chunk PNG / beat stem / final mix)
  services/                 plugin interfaces, lazy heavy deps:
    transcribe/             WhisperX (word-boundary accuracy > plain whisper)
    audiofix/               DeepFilterNet-class cleanup
    tts/                    scratch VO backends: sapi | piper | silero
    capture/                CDP + obs-websocket (formalizes tmp/ capture scripts)
    stock/                  thin provider wrappers (commodity feature — keep thin)
    publish/                YouTube package generation (titles/desc/tags/chapters)
  cli/                      command groups, top-level error boundary, `dl2`
  api/                      FastAPI app (typed, OpenAPI)
  webui/                    Vite + TS Studio (recorder, karaoke, takes, mix
                            timeline view, IR inspector, review feedback)
common/quality/             VQ-* rule catalog (see below)
.claude/agents/             reviewers + hook-doctor, music-supervisor,
                            publish-packager; deep-reasoner + fast-worker
```

CLI is `dl2` during the transition; `dl` flips to v2 once the first real
video ships on it (Phase 5). Legacy stays reachable for frozen projects.

## Model v2 — composition over flags

v1's `Chunk` is a 30+ field god-dataclass with brand-specific booleans
(`trophy`, `silver_badge`, `red_underline`, …). v2 replaces it with typed
composition; **word indices remain the timing primitive**:

```python
Chunk(
    words=(0, 5),                                  # master clock: Whisper word span
    content=Plate(text="30 000\nСТРОК", style="climax"),
    decorations=[Underline(color="accent"), Badge("trophy")],
    anims=[Anim("scale", 1.04, 1.0, ease="out", t=(0, 0.4))],
    transition=Fade(0.3),
)
```

- `content` is a typed variant: `Plate | Overlay | Image | Video` — invalid
  field combinations become type errors, not silent no-ops.
- `decorations` is an open, composable list. New visual treatments = new
  decoration class, not a new field on a shared type.
- **Style registry per project**: the engine knows primitives; the project
  names combos (`"climax"` → sizes/colors/underline per HIT practices).
  Brand flags move out of the engine entirely.
- `anims` are keyframe primitives (property, from, to, easing, time window) —
  expressible and editable by agents, rendered by the graph builder.
- Transitions are first-class on chunk and beat boundaries.

## Compile → Timeline IR

`compile()` resolves the DSL into a pydantic **Timeline IR**: absolute times,
explicit z-ordered layers, resolved asset references with ffprobe facts
(duration, resolution), and the audio mix graph. Properties:

- JSON-serializable → cacheable, diffable, testable.
- `check` runs on IR + probe facts; the duration-mismatch gate (the bug that
  cost 22 blind iterations in v1) is a **built-in render postcondition**.
- Reviewer agents receive IR + probe facts as ground truth — kills the
  hallucinated-offset failure class at the source.
- The model→IR→backend boundary keeps future backends possible without
  touching the model.

## Render

- `graph.py`: filter graphs built as a small typed AST, not string templates.
  Every v1 trap (setpts PTS-shift, `eof_action=pass`, EOF clamps, loudnorm
  parsing) becomes an encoded invariant with a unit test.
- `beat.py`: one ffmpeg subprocess per beat → video + separate VO stem.
- `assemble.py`: edit-level pass that concats beats with real transitions,
  lays music beds **across beat boundaries**, applies sidechain ducking keyed
  by the VO stems, places SFX at word anchors, normalizes the final mix.
  Draft iteration stays per-beat; assemble runs for full previews and finals.
- Resolution sanity guards (no absurd upscales — the 3840×6826 x264 OOM class)
  and black-frame/duration postconditions built in.

## Cache v2

- Atomic publish (temp + `os.replace` + per-key lock) — parallel `-j N` safe.
- Engine hash auto-derived from the package tree (no manual `_ENGINE_FILES`).
- Levels: chunk PNG → beat stem → final mix.

## Quality catalog + agents

Gates currently scattered across PIPELINE.md / AGENTS.md / README become
`common/quality/` rules with IDs, selected à la carte, hard-gating only at
ship time (pattern ported from game-67-idle's ai_studio):

- `VQ-SYNC` audio/video duration match · `VQ-AUDIO` LUFS/ducking targets ·
  `VQ-MOTION` static-screenshot floor · `VQ-HOOK` goal-in-first-second ·
  `VQ-SAFE` safe zones · `VQ-END` deliberate ending · `VQ-PROOF` real product
  visuals. "Could not verify" reports as `unverified`, never as pass.
  Full catalog with per-rule Use/Check/Evidence: `common/quality/README.md`.

Agents: keep vo-reviewer / video-reviewer / thumbnail-designer (blind review +
orchestrator regression checklist), ground them with IR + probe facts. Add:
**hook-doctor** (pre-recording hook writing/scoring — the b01 beat took 14
takes in v1), **music-supervisor** (track choice + ducking params — 8 manual
mix iterations in v1), **publish-packager** (youtube_package.md was manual).
Port **deep-reasoner** (Opus: engine architecture/debug/adversarial review)
and **fast-worker** (Sonnet: mechanical edits) for work on the studio itself.
`dl2 verify --changed` routes changed paths → owning domain → that domain's
tests. devlog-reflector files findings into `docs/issues/` instead of
report-only output.

## Phases

| Phase | Delivers | Acceptance |
|---|---|---|
| 0 | Legacy safety freeze — **DONE 2026-07-16** | atomic cache fix (done), June work committed |
| 1 | model + compile/IR + graph AST + beat render + cache v2 + `dl2 check/compose/iter` — **DONE 2026-07-16** (214 tests incl. real-ffmpeg E2E; follow-ups in docs/issues/dlstudio-phase1-followups.md) | a v2 beat renders with golden-frame tests green |
| 2 | assemble: full mix graph + transitions + `dl2 render/final` — **DONE 2026-07-16** (reviewed + fixed; 335 tests; ducking/LUFS/transitions pinned by real-ffmpeg integration) | full video with music across beats, ducking, -14 LUFS verified |
| 3 | Studio v2 (FastAPI + Vite/TS) — **DONE 2026-07-16** (reviewed + fixed: process-take beat-path fix, hot-reload, upload cap, CORS/file scoping) | record → process → render → review loop in browser, feature parity + mix view |
| 4 | services (WhisperX, audiofix, TTS, capture, publish) + VQ catalog + new agents — **DONE 2026-07-16** except audiofix/capture (deferred: audiofix needs a DeepFilterNet dependency decision; capture needs a real-usage design round) | `dl2 doctor` green; improve loop runs on v2 with grounded reviewers |
| 5 | switchover | first real video ships on v2; `dl` → v2; legacy = frozen projects only |

Each phase ends with a working system — a video can ship at any point.
