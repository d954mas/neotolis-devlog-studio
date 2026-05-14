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
| Quick result from beats.py edit | 540p draft, parallel, cache-aware | `/dl-iterate` |
| Auto-rebuild on save | Polling watch mode | `/dl-watch` |
| Final upload-ready render | 1080p or 4K + GPU | `/dl-final` |
| Improve a rendered beat/video | Loop: render → reviewer → mech fixes → repeat | `/dl-improve` |
| Cut clip for reel/short | `dl cut` with reframe | `/dl-reel` |
| Review a recorded VO take | Spawn `vo-reviewer` agent on `.webm` | (agent) |
| Review composed beat / iter video | Spawn `video-reviewer` agent | (agent) |

## Critical engineering defaults

1. **FFmpeg engine is the default** (`compose_ffmpeg.py`). Don't suggest `--engine moviepy` unless the user reports a visual bug specific to the ffmpeg pipeline. MoviePy fallback is kept for safety but is 5-25× slower.

2. **Cache is correct and on by default.** Hash includes engine source, design, asset mtimes, draft/gpu flags. Engine code changes auto-invalidate. Don't pass `--no-cache` unless debugging cache itself.

3. **Resolution is a runtime flag, not a code constant.** `--width 540p` for iteration, `--width 4k` for final. Engine is resolution-independent via `design.px()` — same `beats.py` renders correctly at any resolution.

4. **Parallel render** (`-j 4..8`) is safe and useful when rendering many beats. Each worker is its own Python process. Per-worker cache writes are atomic.

5. **Per-chunk fade-in/out is currently disabled in ffmpeg engine** — known interaction with overlay alpha that broke text bands. Plates and overlay bands pop in/out abruptly. Don't try to "fix" the missing fade with hacks unless you have a verified ffmpeg alpha-fade approach. Crossfade between scenes (xfade) works fine.

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

Agent file locations:
- `trolley/.claude/agents/vo-reviewer.md` — audio take review (.webm)
- `trolley/.claude/agents/video-reviewer.md` — composed beat / full video / plan review

For new projects, copy these `.md` files into `<newproject>/.claude/agents/`.

## Don't

- Don't render at 4K during iteration (slow + separate cache entry).
- Don't `--no-cache` unless debugging cache.
- Don't write rendered MP4s, raw recordings, or large images into git (`.gitignore` covers this — verify if adding new asset types).
- Don't invent file paths when applying `src` changes — always Glob/Read first.
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
- `<project>/.claude/agents/` — project-local reviewer definitions
