"""Explicit-path Python edit loader used only during compilation."""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path

from .api import Edit


def load_edit(path: Path) -> Edit:
    source = path.resolve(strict=True)
    module_name = f"_dlstudio_v3_edit_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load edit: {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        edit = getattr(module, "EDIT", None)
        if not isinstance(edit, Edit):
            raise TypeError("v3 edit module must expose EDIT: Edit")
        return edit
    finally:
        sys.modules.pop(module_name, None)
