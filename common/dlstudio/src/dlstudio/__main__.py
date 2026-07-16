"""`python -m dlstudio` == `dl2` — same CLI entry as the console script.

Lets the workspace-root `dl2.bat` / `dl2` wrappers work without relying on
pip's scripts directory being on PATH.
"""
from __future__ import annotations

import sys

from dlstudio.cli import main

if __name__ == "__main__":
    sys.exit(main())
