"""Thin command-line adapter for one explicit Studio v3 production."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from dlstudio.application.api import (
    advance_production,
    deliver_local,
    project_status,
    query_status,
    resolve_blob,
    submit_review_payload,
)

from .local import LocalProduction, load_local_production


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dlstudio-v3")
    parser.add_argument("--manifest", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("advance")
    review = commands.add_parser("review")
    review.add_argument("--verdict", type=Path, required=True)
    deliver = commands.add_parser("deliver")
    deliver.add_argument("--destination-id", required=True)
    blob = commands.add_parser("blob")
    blob.add_argument("sha256")
    blob.add_argument("size", type=int)
    return parser


def _advance(production: LocalProduction):
    return advance_production(
        production.workflows,
        production.assets,
        production.repository.objects,
        authoring_path=production.authoring_path,
        output_root=production.production_root / "data" / ".studio" / "outputs",
        cache_root=production.production_root / "data" / ".studio" / "cache",
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        production = load_local_production(args.manifest)
        if args.command == "status":
            result: Any = query_status(production.workflows).as_payload()
        elif args.command == "advance":
            result = project_status(_advance(production)).as_payload()
        elif args.command == "review":
            payload = json.loads(args.verdict.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("review verdict must be a JSON object")
            result = project_status(
                submit_review_payload(production.workflows, payload)
            ).as_payload()
        elif args.command == "deliver":
            workflow, receipt = deliver_local(
                production.workflows,
                production.delivery_root,
                destination_id=args.destination_id,
            )
            result = {
                "status": project_status(workflow).as_payload(),
                "receipt": receipt.as_payload(),
            }
        elif args.command == "blob":
            source = resolve_blob(
                production.repository.objects, args.sha256, args.size
            )
            with source.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    sys.stdout.buffer.write(chunk)
            return 0
        else:  # pragma: no cover - argparse owns command validation.
            raise AssertionError(args.command)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
