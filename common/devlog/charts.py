"""Reusable animated infographic primitives for devlog projects.

These scenes render into regular PNG/MP4 assets, so they can be used by the
existing FFmpeg pipeline via `Scene(kind="image"|"video")`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from devlog.anim import count_up, ease_out_back, progress, staggered_progress
from devlog.render.text import pick_font
from devlog.types import Design


RGB = tuple[int, int, int]


@dataclass(frozen=True)
class GeneratedScene:
    type: str
    duration: float
    frame: Any
    fps: int | None = None
    crf: int = 18


@dataclass(frozen=True)
class BarDatum:
    label: str
    value: float
    color: RGB | None = None


@dataclass(frozen=True)
class BarChart:
    title: str
    values: list[BarDatum]
    subtitle: str = ""
    unit: str = ""
    duration: float = 3.2
    reveal_duration: float = 1.9
    highlight_index: int | None = None

    def frame(self, t: float, design: Design) -> Image.Image:
        S = design.px
        pal = design.palette
        img = _bg(design)
        draw = ImageDraw.Draw(img)
        title_bottom = _title(draw, design, self.title, self.subtitle)

        chart_top = title_bottom + S(64)
        chart_bottom = design.H - S(205)
        chart_h = chart_bottom - chart_top
        left = S(135)
        right = design.W - S(135)
        gap = S(12)
        n = max(1, len(self.values))
        bar_w = max(4, (right - left - gap * (n - 1)) // n)
        max_value = max((d.value for d in self.values), default=1.0) or 1.0

        draw.line((left, chart_bottom, right, chart_bottom), fill=pal.gold, width=S(4))
        f_num = _font(design.fonts.display, S(38))
        f_label = _font(design.fonts.display, S(30))
        f_unit = _font(design.fonts.text, S(36))

        for i, d in enumerate(self.values):
            p = staggered_progress(i, n, t, start=0.15, duration=self.reveal_duration,
                                   stagger=0.065, easing="out_cubic")
            h = int(chart_h * (d.value / max_value) * p)
            x = left + i * (bar_w + gap)
            y = chart_bottom - h
            color = d.color or pal.gold
            if self.highlight_index == i:
                pop = progress(t, self.reveal_duration * 0.8, 0.5, "out_back")
                color = pal.red if pop > 0.15 else color
            if h > 0:
                draw.rectangle((x + S(4), y + S(8), x + bar_w + S(4), chart_bottom + S(8)),
                               fill=(0, 0, 0))
                draw.rectangle((x, y, x + bar_w, chart_bottom), fill=color)
                val = f"{count_up(d.value, t, 0.1 + i * 0.055, self.reveal_duration)}{self.unit}"
                vb = draw.textbbox((0, 0), val, font=f_num, anchor="lt")
                _text(draw, (x + (bar_w - (vb[2] - vb[0])) // 2, y - S(50)),
                      val, f_num, color)
            lb = draw.textbbox((0, 0), d.label, font=f_label, anchor="lt")
            _text(draw, (x + (bar_w - (lb[2] - lb[0])) // 2, chart_bottom + S(22)),
                  d.label, f_label, pal.gold_dim, shadow=False)

        total = sum(d.value for d in self.values)
        note = f"TOTAL {int(total):,}".replace(",", " ")
        if self.unit:
            note += self.unit
        nb = draw.textbbox((0, 0), note, font=f_unit, anchor="lt")
        _text(draw, ((design.W - (nb[2] - nb[0])) // 2, design.H - S(102)),
              note, f_unit, pal.gold_dim, shadow=False)
        return img


@dataclass(frozen=True)
class TimelineItem:
    label: str
    text: str
    at: float
    color: RGB | None = None


@dataclass(frozen=True)
class TimelineChart:
    title: str
    items: list[TimelineItem]
    subtitle: str = ""
    duration: float = 3.4
    reveal_duration: float = 2.1

    def frame(self, t: float, design: Design) -> Image.Image:
        S = design.px
        pal = design.palette
        img = _bg(design)
        draw = ImageDraw.Draw(img)
        _title(draw, design, self.title, self.subtitle)
        left, right = S(170), design.W - S(170)
        y = design.H // 2 + S(58)
        line_p = progress(t, 0.15, self.reveal_duration, "in_out_cubic")
        draw.line((left, y, left + int((right - left) * line_p), y),
                  fill=pal.gold, width=S(8))

        f_label = _font(design.fonts.display, S(54))
        f_text = _font(design.fonts.text, S(30))
        for i, item in enumerate(self.items):
            p = staggered_progress(i, len(self.items), t, 0.45, self.reveal_duration,
                                   stagger=0.18, easing="out_back")
            if p <= 0:
                continue
            x = left + int((right - left) * max(0.0, min(1.0, item.at)))
            r = int(S(18) * max(0.2, ease_out_back(p)))
            color = item.color or pal.gold
            draw.ellipse((x - r, y - r, x + r, y + r), fill=color, outline=pal.bg, width=S(4))
            label_y = y - S(118) if i % 2 == 0 else y + S(54)
            tb = draw.textbbox((0, 0), item.label, font=f_label, anchor="lt")
            _text(draw, (x - (tb[2] - tb[0]) // 2, label_y), item.label, f_label, color)
            text_y = label_y + S(58)
            wrapped = item.text if len(item.text) <= 18 else item.text[:18] + "..."
            db = draw.textbbox((0, 0), wrapped, font=f_text, anchor="lt")
            _text(draw, (x - (db[2] - db[0]) // 2, text_y), wrapped, f_text,
                  pal.gold_dim, shadow=False)
        return img


@dataclass(frozen=True)
class WorkflowDiagram:
    title: str
    steps: list[str]
    subtitle: str = ""
    duration: float = 3.0

    def frame(self, t: float, design: Design) -> Image.Image:
        S = design.px
        pal = design.palette
        img = _bg(design)
        draw = ImageDraw.Draw(img)
        _title(draw, design, self.title, self.subtitle)
        n = max(1, len(self.steps))
        box_w = min(S(430), (design.W - S(220)) // n)
        box_h = S(230)
        gap = S(52)
        total_w = n * box_w + (n - 1) * gap
        x0 = (design.W - total_w) // 2
        y0 = design.H // 2 - S(30)
        f = _font(design.fonts.text, S(52))
        arrow_font = _font(design.fonts.display, S(90))
        for i, step in enumerate(self.steps):
            p = staggered_progress(i, n, t, 0.2, 1.5, stagger=0.28, easing="out_back")
            if p <= 0:
                continue
            grow = 0.86 + 0.14 * p
            w = int(box_w * grow)
            h = int(box_h * grow)
            cx = x0 + i * (box_w + gap) + box_w // 2
            cy = y0 + box_h // 2
            x1, y1 = cx - w // 2, cy - h // 2
            draw.rounded_rectangle((x1 + S(7), y1 + S(14), x1 + w + S(7), y1 + h + S(14)),
                                   radius=S(22), fill=(0, 0, 0))
            draw.rounded_rectangle((x1, y1, x1 + w, y1 + h), radius=S(22),
                                   fill=(20, 16, 12), outline=pal.gold, width=S(5))
            draw.rectangle((x1, y1 + S(28), x1 + S(14), y1 + h - S(28)), fill=pal.red)
            lines = step.replace("\\n", "\n").splitlines() or [step]
            line_h = S(58)
            ty = cy - (len(lines) * line_h) // 2
            for line in lines:
                bb = draw.textbbox((0, 0), line, font=f, anchor="lt")
                _text(draw, (cx - (bb[2] - bb[0]) // 2, ty), line, f, pal.gold)
                ty += line_h
            if i < n - 1:
                ap = progress(t, 0.55 + i * 0.28, 0.35, "out_cubic")
                if ap > 0:
                    arrow = ">"
                    ab = draw.textbbox((0, 0), arrow, font=arrow_font, anchor="lt")
                    ax = x0 + i * (box_w + gap) + box_w + (gap - (ab[2] - ab[0])) // 2
                    _text(draw, (ax, cy - S(48)), arrow, arrow_font, pal.red)
        return img


@dataclass(frozen=True)
class CounterCard:
    title: str
    value: float
    subtitle: str = ""
    suffix: str = ""
    duration: float = 2.4

    def frame(self, t: float, design: Design) -> Image.Image:
        S = design.px
        pal = design.palette
        img = _bg(design)
        draw = ImageDraw.Draw(img)
        f_title = _font(pick_font(self.title, design), S(82))
        f_value = _font(design.fonts.display, S(250))
        f_sub = _font(pick_font(self.subtitle, design), S(52))
        val = f"{count_up(self.value, t, 0.1, self.duration * 0.72):,}".replace(",", " ")
        val += self.suffix
        block_y = design.H // 2 - S(210)
        _centered_text(draw, self.title, block_y, f_title, pal.gold_dim)
        vb = draw.textbbox((0, 0), val, font=f_value, anchor="lt")
        _text(draw, ((design.W - (vb[2] - vb[0])) // 2, block_y + S(105)),
              val, f_value, pal.gold)
        line_w = S(design.underline_width)
        line_y = block_y + S(395)
        draw.rectangle(((design.W - line_w) // 2, line_y,
                        (design.W + line_w) // 2, line_y + S(10)), fill=pal.red)
        if self.subtitle:
            sb = draw.textbbox((0, 0), self.subtitle, font=f_sub, anchor="lt")
            _text(draw, ((design.W - (sb[2] - sb[0])) // 2, line_y + S(34)),
                  self.subtitle, f_sub, pal.gold_dim, shadow=False)
        return img


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, max(1, int(size)))


def _bg(design: Design) -> Image.Image:
    img = Image.new("RGB", design.resolution, design.palette.bg)
    rgba = img.convert("RGBA")
    rgba.alpha_composite(_vignette(design))
    return rgba.convert("RGB")


def _vignette(design: Design) -> Image.Image:
    W, H = design.W, design.H
    step = max(2, design.px(4))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cx, cy = W // 2, H // 2
    max_r = max(1.0, (cx * cx + cy * cy) ** 0.5)
    for y in range(0, H, step):
        for x in range(0, W, step):
            r = (((x - cx) ** 2 + (y - cy) ** 2) ** 0.5) / max_r
            alpha = int(105 * (r ** 1.8))
            layer.paste((0, 0, 0, alpha), (x, y, x + step, y + step))
    return layer.filter(ImageFilter.GaussianBlur(design.px(10)))


def _text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str,
          font: ImageFont.FreeTypeFont, fill: RGB,
          anchor: str = "lt", shadow: bool = True) -> None:
    if shadow:
        draw.text((xy[0] + 3, xy[1] + 3), text, font=font, fill=(0, 0, 0), anchor=anchor)
    draw.text(xy, text, font=font, fill=fill, anchor=anchor)


def _centered_text(draw: ImageDraw.ImageDraw, text: str, y: int,
                   font: ImageFont.FreeTypeFont, fill: RGB) -> tuple[int, int, int, int]:
    bbox = draw.textbbox((0, 0), text, font=font, anchor="lt")
    w = bbox[2] - bbox[0]
    x = (draw.im.size[0] - w) // 2
    _text(draw, (x, y), text, font, fill)
    return (x, y, x + w, y + (bbox[3] - bbox[1]))


def _title(draw: ImageDraw.ImageDraw, design: Design, title: str,
           subtitle: str = "", y: int | None = None) -> int:
    S = design.px
    y = S(72) if y is None else y
    title_font = _font(pick_font(title, design), S(104))
    bbox = _centered_text(draw, title, y, title_font, design.palette.gold)
    line_y = bbox[3] + S(18)
    line_w = S(design.underline_width)
    draw.rectangle(((design.W - line_w) // 2, line_y,
                    (design.W + line_w) // 2, line_y + S(8)), fill=design.palette.red)
    if subtitle:
        sub_font = _font(pick_font(subtitle, design), S(40))
        sb = draw.textbbox((0, 0), subtitle, font=sub_font, anchor="lt")
        _text(draw, ((design.W - (sb[2] - sb[0])) // 2, line_y + S(22)),
              subtitle, sub_font, design.palette.gold_dim, shadow=False)
        return line_y + S(76)
    return line_y + S(42)


def _normal_color(value: Any, default: RGB) -> RGB:
    if value is None:
        return default
    if isinstance(value, str):
        value = value.lstrip("#")
        if len(value) == 6:
            return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return (int(value[0]), int(value[1]), int(value[2]))
    return default


def scene_from_spec(spec: dict[str, Any]) -> GeneratedScene:
    typ = spec.get("type")
    if typ == "bar_chart":
        values = [
            BarDatum(
                label=str(v.get("label", i + 1)),
                value=float(v.get("value", 0)),
                color=_normal_color(v.get("color"), (0, 0, 0)) if v.get("color") else None,
            )
            for i, v in enumerate(spec.get("values", []))
        ]
        chart = BarChart(
            title=str(spec.get("title", "")),
            subtitle=str(spec.get("subtitle", "")),
            values=values,
            unit=str(spec.get("unit", "")),
            duration=float(spec.get("duration", 3.2)),
            highlight_index=spec.get("highlight_index"),
        )
        return GeneratedScene(typ, chart.duration, chart.frame)

    if typ == "timeline":
        items = [
            TimelineItem(
                label=str(v.get("label", "")),
                text=str(v.get("text", "")),
                at=float(v.get("at", 0)),
                color=_normal_color(v.get("color"), (0, 0, 0)) if v.get("color") else None,
            )
            for v in spec.get("items", [])
        ]
        chart = TimelineChart(
            title=str(spec.get("title", "")),
            subtitle=str(spec.get("subtitle", "")),
            items=items,
            duration=float(spec.get("duration", 3.4)),
        )
        return GeneratedScene(typ, chart.duration, chart.frame)

    if typ == "workflow":
        chart = WorkflowDiagram(
            title=str(spec.get("title", "")),
            subtitle=str(spec.get("subtitle", "")),
            steps=[str(s) for s in spec.get("steps", [])],
            duration=float(spec.get("duration", 3.0)),
        )
        return GeneratedScene(typ, chart.duration, chart.frame)

    if typ == "counter":
        chart = CounterCard(
            title=str(spec.get("title", "")),
            subtitle=str(spec.get("subtitle", "")),
            value=float(spec.get("value", 0)),
            suffix=str(spec.get("suffix", "")),
            duration=float(spec.get("duration", 2.4)),
        )
        return GeneratedScene(typ, chart.duration, chart.frame)

    raise ValueError(f"Unknown generated scene type {typ!r}")


def sample_spec(kind: Literal["bar", "timeline", "workflow", "counter"]) -> dict[str, Any]:
    if kind == "bar":
        return {
            "type": "bar_chart",
            "title": "273 COMMITS",
            "subtitle": "13 DAY JAM",
            "values": [
                {"label": "D1", "value": 8},
                {"label": "D2", "value": 23},
                {"label": "D3", "value": 80},
                {"label": "D4", "value": 31},
                {"label": "D5", "value": 18},
            ],
            "highlight_index": 2,
        }
    if kind == "timeline":
        return {
            "type": "timeline",
            "title": "13 DAYS",
            "subtitle": "FROM PROTOTYPE TO RELEASE",
            "items": [
                {"label": "D1", "text": "prototype", "at": 0.0},
                {"label": "D4", "text": "core loop", "at": 0.28},
                {"label": "D8", "text": "content", "at": 0.62},
                {"label": "D13", "text": "submit", "at": 1.0},
            ],
        }
    if kind == "workflow":
        return {
            "type": "workflow",
            "title": "WORKFLOW",
            "subtitle": "PROMPT TO RESULT",
            "steps": ["TASK", "AI\\nBUILDS", "I\\nCHECK"],
        }
    return {
        "type": "counter",
        "title": "TOTAL VIEWS",
        "value": 30000,
        "subtitle": "IN 30 DAYS",
    }
