"""Fresh-process TimelineIR renderer entry point."""

from __future__ import annotations

import argparse
from pathlib import Path

from dlstudio.foundation.api import BlobRef
from dlstudio.rendering.api import (
    ExecutionFingerprint,
    RenderOptions,
    render,
)
from dlstudio.timeline.api import TimelineIR


class DirectoryResolver:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def path_for(self, ref: BlobRef) -> Path:
        return self.root / ref.sha256

    def verify(self, ref: BlobRef) -> None:
        self.verify_metadata(ref)
        path = self.path_for(ref)
        import hashlib

        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != ref.sha256:
            raise ValueError(f"corrupt object: {ref.sha256}")

    def verify_metadata(self, ref: BlobRef) -> None:
        path = self.path_for(ref)
        if not path.is_file() or path.stat().st_size != ref.size:
            raise ValueError(f"missing object: {ref.sha256}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ir", type=Path, required=True)
    parser.add_argument("--objects", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args(argv)
    timeline = TimelineIR.from_canonical_bytes(args.ir.read_bytes())
    render(
        timeline,
        ExecutionFingerprint.detect(args.ffmpeg),
        RenderOptions(),
        DirectoryResolver(args.objects),
        output=args.output,
        cache_root=args.cache,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
