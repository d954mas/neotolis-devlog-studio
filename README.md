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
.\dl.bat render trolley.edits.youtube --width 540p --draft -j 6

# Web studio (script + structure + record + reviewer feedback)
.\dl.bat serve trolley.edits.youtube
# Open http://localhost:8080/devlog/studio.html

# Watch mode — auto-rerender on beats.py change
.\dl.bat watch trolley.edits.youtube

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
# 1. Copy trolley as a template
xcopy /E /I trolley\ newproject\

# 2. Customize
#    - newproject\shared\palette.py    (brand if different)
#    - newproject\edits\youtube\beats.py    (your content)
#    - newproject\.claude\agents\           (project-specific reviewer rules)

# 3. Render
.\dl.bat render newproject.edits.youtube
```
