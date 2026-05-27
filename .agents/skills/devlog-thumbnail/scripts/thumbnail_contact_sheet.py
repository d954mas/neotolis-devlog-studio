#!/usr/bin/env python3
"""Create a thumbnail QA contact sheet at common YouTube feed sizes."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


SIZES = [
    ("upload", (1280, 720)),
    ("large", (640, 360)),
    ("feed", (320, 180)),
    ("small", (160, 90)),
]


def load_font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def fit_canvas(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_w, target_h = size
    src = image.convert("RGB")
    src_ratio = src.width / src.height
    target_ratio = target_w / target_h
    if src_ratio > target_ratio:
        new_h = target_h
        new_w = round(new_h * src_ratio)
    else:
        new_w = target_w
        new_h = round(new_w / src_ratio)
    resized = src.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("thumbnail", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    image = Image.open(args.thumbnail)
    out = args.out or args.thumbnail.with_name(args.thumbnail.stem + "_contact.png")
    margin = 24
    label_h = 32
    canvas_w = 1280 + margin * 2
    canvas_h = sum(size[1] + label_h + margin for _, size in SIZES) + margin
    canvas = Image.new("RGB", (canvas_w, canvas_h), "#101010")
    draw = ImageDraw.Draw(canvas)
    font = load_font(22)
    small_font = load_font(18)

    ratio = image.width / image.height
    expected = 16 / 9
    status = "OK" if abs(ratio - expected) < 0.02 else "CHECK ASPECT"
    header = f"{args.thumbnail.name}  {image.width}x{image.height}  aspect {ratio:.3f}  {status}"
    draw.text((margin, 8), header, fill="#f4f4f4", font=small_font)

    y = margin + 24
    for name, size in SIZES:
        preview = fit_canvas(image, size)
        canvas.paste(preview, (margin, y + label_h))
        draw.text((margin, y), f"{name}: {size[0]}x{size[1]}", fill="#ffd65a", font=font)
        y += size[1] + label_h + margin

    canvas.save(out)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
