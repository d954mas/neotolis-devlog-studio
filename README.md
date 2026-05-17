# devlogs/

Workspace for spoken-word video production (YouTube devlogs, narrated essays).

## Structure

```
devlogs/
  common/                    Reusable engine + CLI + web tools (versioned here)
    devlog/                  Python package (render, audio, cache, cli, web)
    tests/                   pytest smoke tests
    PIPELINE.md              How the orchestrator runs the improve loop
    README.md                Quickstart for a new project

  dl.bat / dl                CLI wrapper (Windows / POSIX)

  trolley/                   First project — Not a Trolley Problem devlog
    shared/palette.py        Brand colors + fonts
    edits/youtube/           1920x1080 YouTube edit
    edits/reel_30k/          Example vertical reel
    .claude/agents/          vo-reviewer, video-reviewer
    data/                    [NOT tracked — large media stored separately]
    scripts/                 Project-specific infographic builders
    web/                     Legacy HTML tools (preview, recorder)
```

## Quick start

```powershell
# Render a project (uses cache; second run is ~instant)
.\dl.bat iter
.\dl.bat render
.\dl.bat final

# Validate before rendering expensive outputs
.\dl.bat check
.\dl.bat check --deep

# Inspect environment and beat status
.\dl.bat doctor
.\dl.bat beats --missing-only
.\dl.bat stale --width 540p --quality draft
.\dl.bat iter --stale
.\dl.bat assets --width 4k
.\dl.bat cache-info
.\dl.bat script --out trolley\data\review\script.md
.\dl.bat import-script script.md --out trolley\edits\youtube\beats.py
.\dl.bat smoke --skip-tests

# Web studio (script + structure + record + reviewer feedback)
.\dl.bat serve trolley.edits.youtube
# Open http://localhost:8080/devlog/studio.html

# Watch mode — auto-rerender on beats.py change
.\dl.bat watch trolley.edits.youtube
.\dl.bat watch --beat b4

# Run tests
PYTHONPATH=common python -m pytest common/tests/ -v
```

See `common/README.md` for the full pipeline reference and
`common/PIPELINE.md` for the orchestrator's improve-loop behavior.

## Data (not in repo)

Media assets (audio recordings, screenshots, rendered videos, infographics)
are large and stored outside git. Each project keeps them under its own
`data/` folder. To bootstrap a project on a fresh checkout you need to
restore data via your own backup/cloud sync mechanism.

The git repo tracks: source code, beats.py, design.py, agents, docs,
words.json (Whisper outputs — small, expensive to regenerate).

The git repo ignores: `*.mp4`, `*.webm`, `*.wav`, `*.png`, `*.jpg`,
render cache, intermediate logs, raw recordings, ephemeral previews.

See `.gitignore` for the full list.

## Adding a new project

```powershell
# 1. Create a clean scaffold
.\dl.bat new newproject
# Or start from a rough script
.\dl.bat new-video newproject --script script.md

# 2. Customize
#    - newproject\shared\palette.py    (brand if different)
#    - newproject\edits\youtube\beats.py    (your content)
#    - newproject\.claude\agents\           (project-specific reviewer rules)

# 3. Render
.\dl.bat check newproject.edits.youtube
.\dl.bat iter newproject.edits.youtube -j 6
.\dl.bat final newproject.edits.youtube
```
