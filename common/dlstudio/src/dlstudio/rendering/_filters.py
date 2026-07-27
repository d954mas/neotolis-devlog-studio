"""Pure FFmpeg filter fragments shared by renderer branches."""

from __future__ import annotations

from dlstudio.timeline.api import VisualInstruction


def media_geometry_filter(
    instruction: VisualInstruction,
    *,
    background: str,
) -> str:
    if instruction.geometry is not None:
        resolved = instruction.geometry
        geometry = f"scale={resolved.scaled_width}:{resolved.scaled_height}"
        if resolved.crop_x is not None:
            geometry += (
                f",crop={instruction.width}:{instruction.height}:"
                f"{resolved.crop_x}:{resolved.crop_y}"
            )
        elif resolved.pad_x is not None:
            geometry += (
                f",pad={instruction.width}:{instruction.height}:"
                f"{resolved.pad_x}:{resolved.pad_y}:color={background}"
            )
        return geometry
    if instruction.fit == "stretch":
        return f"scale={instruction.width}:{instruction.height}"
    if instruction.fit == "cover":
        return (
            f"scale={instruction.width}:{instruction.height}:"
            "force_original_aspect_ratio=increase,"
            f"crop={instruction.width}:{instruction.height}"
        )
    return (
        f"scale={instruction.width}:{instruction.height}:"
        "force_original_aspect_ratio=decrease,"
        f"pad={instruction.width}:{instruction.height}:"
        f"(ow-iw)/2:(oh-ih)/2:color={background}"
    )
