# Studio v3

Local video-production workspace for one owner. Studio v3 is a modular Python
application with one workflow shared by CLI, HTTP API and Web UI.

Start here:

- [Quickstart](docs/QUICKSTART_V3.md)
- [Architecture](docs/ARCHITECTURE_V3.md)
- [Contribution rules](AGENTS.md)

## Run

Windows:

```powershell
.\dl2.bat --manifest path\to\production.toml status
.\dl2.bat --manifest path\to\production.toml serve
```

POSIX:

```bash
./dl2 --manifest path/to/production.toml status
./dl2 --manifest path/to/production.toml serve
```

The status returns exactly one useful action:

- `advance` runs the next automatic stage;
- `review` records a verdict for the exact final artifact;
- `deliver` copies the current eligible frozen candidate.

Use `dl2 --help` for the complete command surface. There are no v1/v2 commands
or compatibility mode.

## Layout

```text
common/dlstudio/       Studio package, tests and Web UI
docs/                  v3 architecture, quickstart and cutover evidence
tools/studio_v3_verify executable architecture/performance/cutover gates
<project>/.../         production.toml, authoring.py and local media
```

Media, recordings, object stores, renders and deliveries are intentionally not
committed. Preserve them through the verified backup process; never infer trust
or approval from historical filenames.
