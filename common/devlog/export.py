"""Markdown exports for authoring and review."""
from __future__ import annotations

from devlog.types import Edit


def script_markdown(edit: Edit) -> str:
    lines = [f"# Script: {edit.name}", ""]
    for beat_id in edit.order:
        beat = edit.beats[beat_id]
        title = beat.title or beat_id
        lines.extend([f"## {beat_id} — {title}", "", beat.vo or "", ""])
        if beat.stage:
            lines.extend([f"> {beat.stage}", ""])
    return "\n".join(lines).rstrip() + "\n"


def shotlist_markdown(edit: Edit) -> str:
    lines = [f"# Shotlist: {edit.name}", ""]
    for beat_id in edit.order:
        beat = edit.beats[beat_id]
        title = beat.title or beat_id
        lines.extend([f"## {beat_id} — {title}", ""])
        for idx, chunk in enumerate(beat.chunks):
            scene = chunk.scene or beat.scene
            scene_desc = f"{scene.kind}:{scene.src}" if scene else "solid"
            text = (chunk.text or chunk.label or "").replace("\n", " / ")
            words = f"{chunk.words[0]}-{chunk.words[1]}"
            lines.append(f"- c{idx} words {words} · {chunk.kind} · {scene_desc} · {text}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
