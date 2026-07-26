# Devlog Reference Lab

Repeatable evidence extraction for long-form YouTube devlogs. The lab keeps
reference downloads under the ignored `data/research/` tree and produces:

- exact SHA-256 and ffprobe facts;
- public YouTube metadata and clean auto-caption transcripts;
- speaking rate;
- scene-change cadence and timestamps;
- integrated loudness and true peak;
- timestamped 10-second contact sheets.

The scene-change number is a comparison signal, not a literal edit-decision
count. Camera motion, animated overlays, and transitions can also cross the
threshold. Editorial conclusions still require watching the exact MP4.

## Setup

From the workspace root:

```powershell
py -3.12 -m pip install -r tools/devlog_reference_lab/requirements.txt
```

`ffmpeg` and `ffprobe` must be on `PATH`.

## Sync a channel

The `/videos` tab deliberately excludes Shorts. Re-running is idempotent:

```powershell
tools/devlog_reference_lab/sync_channel.ps1
```

For another channel or destination:

```powershell
tools/devlog_reference_lab/sync_channel.ps1 `
  -ChannelUrl "https://www.youtube.com/@channel/videos" `
  -OutputDirectory "data/research/channel/source"
```

## Analyze references

```powershell
py -3.12 tools/devlog_reference_lab/analyze.py `
  data/research/zerah_games/source `
  --out data/research/zerah_games/analysis
```

Analyze one or more local delivery candidates with the same machinery:

```powershell
py -3.12 tools/devlog_reference_lab/analyze.py `
  not_a_trolley_problem/delivery/devlogs/2026_07_17_devlog_01/video.mp4 `
  not_a_trolley_problem/delivery/devlogs/2026_07_22_devlog_01/video.mp4 `
  --out data/research/our_long_devlogs/analysis
```

Use `--skip-sheets` for a faster numeric-only pass. The normal output is
ignored by git; durable conclusions belong in a small tracked Markdown
benchmark or production brief, not in downloaded media or generated frames.

## Gate a new long-form story before scripting

For a product-first Studio v2 devlog, the canonical gate is integrated:

```powershell
dl2 longform-check not_a_trolley_problem:<production>
dl2 longform-check not_a_trolley_problem:<production> --strict
```

It validates both the story map and montage fields in `shot_manifest.json`,
and is also called by `preflight`/`autopilot-run`. The standalone validator
below remains useful for a reference project that is not yet a Studio v2
production.

Copy `templates/story_map.example.json` into the production `data/plan/`
directory, replace every placeholder, and validate it:

```powershell
py -3.12 tools/devlog_reference_lab/validate_story_map.py `
  not_a_trolley_problem/devlogs/<production>/data/plan/story_map.json `
  --production-root not_a_trolley_problem/devlogs/<production>
```

Early planning may keep `needs_capture` sources as warnings. Before final VO,
run the same command with `--strict`; unresolved sources then block. Each
mini-arc must contain before/payoff evidence plus failure or process evidence,
so a chronological status list cannot silently pass as a story.
