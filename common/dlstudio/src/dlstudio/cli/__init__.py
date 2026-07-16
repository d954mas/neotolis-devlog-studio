"""cli — the `dl2` command.

OWNER: cli-agent.

Phase 1 commands:
  dl2 check <edit>                 compile + run_checks, human-readable report
  dl2 ir <edit> [--out ir.json]    dump the Timeline IR (agents' ground truth)
  dl2 compose <edit> <beat>        render one beat (cache-aware)
  dl2 iter <edit> [--stale]        draft-quality render of all/stale beats
  dl2 beats <edit>                 durations, chunk counts, render status
  dl2 doctor                       ffmpeg/ffprobe/python/pydantic diagnostics

Conventions (v1 parity where sensible):
- <edit> is a dotted module path exposing EDIT (dlstudio.model.Edit);
  CLI auto-detects project root from module location and chdirs there so
  beats.py paths stay relative. Port the loader idea from legacy cli.py.
- Import compile/render lazily INSIDE handlers (stubs may be unimplemented).
- Top-level error boundary in main(): pretty one-line error + exit 1;
  --debug re-raises with traceback. No raw tracebacks by default (v1 gap).
- Defaults read from workspace devlog.toml [v2] table when present.
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError("cli-agent implements this")


if __name__ == "__main__":
    sys.exit(main())
