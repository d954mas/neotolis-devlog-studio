"""Reusable, render-ready HyperFrames visual-block scaffolds.

The blocks intentionally stay presentation-only: they annotate or frame
existing gameplay without changing the product footage. Content is supplied
through HyperFrames composition variables, so a scaffold can be reused across
beats without editing its deterministic GSAP timeline.
"""
from __future__ import annotations

import html
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class VisualBlockTemplate:
    """Public metadata for one built-in visual block."""

    id: str
    label: str
    purpose: str
    required_variables: tuple[str, ...]


VISUAL_BLOCK_TEMPLATES: dict[str, VisualBlockTemplate] = {
    "day-card": VisualBlockTemplate(
        id="day-card",
        label="Day / chapter card",
        purpose="A deliberate chapter boundary with a short public-facing claim.",
        required_variables=("day", "title", "subtitle", "background_image"),
    ),
    "before-after": VisualBlockTemplate(
        id="before-after",
        label="Before / after comparison",
        purpose="An aligned proof frame that keeps both visual states visible.",
        required_variables=("before_image", "after_image", "claim"),
    ),
    "focus-callout": VisualBlockTemplate(
        id="focus-callout",
        label="Focus callout",
        purpose="A restrained annotation that directs attention inside gameplay.",
        required_variables=("image", "label", "explanation", "focus_x", "focus_y"),
    ),
    "cta-endcard": VisualBlockTemplate(
        id="cta-endcard",
        label="Canonical wishlist CTA",
        purpose="A deliberate ending that asks viewers to wishlist an existing Steam page.",
        required_variables=(
            "game_title", "eyebrow", "cta", "steam_url",
            "episode", "background_image",
        ),
    ),
    "explain-steps": VisualBlockTemplate(
        id="explain-steps",
        label="Four-step explainer",
        purpose="A sequential visual explanation instead of a dense note or debug card.",
        required_variables=("title", "step_1", "step_2", "step_3", "step_4"),
    ),
}

ORIENTATIONS: dict[str, tuple[int, int]] = {
    "landscape": (1920, 1080),
    "vertical": (1080, 1920),
}

_PALETTE_CSS = """
    :root {
      --ink: #151515;
      --black: #0B0B0C;
      --paper: #F4F1EA;
      --red: #E23B35;
      --muted: #A7A3A0;
    }
"""

_BASE_CSS = """
    * { box-sizing: border-box; }
    html, body {
      margin: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      background: #0B0B0C;
      color: #F4F1EA;
      font-family: "JetBrains Mono", monospace;
    }
    .root {
      position: relative;
      width: 100%;
      height: 100%;
      overflow: hidden;
      isolation: isolate;
      background-color: #0B0B0C;
    }
    .grain {
      position: absolute;
      inset: 0;
      opacity: .12;
      pointer-events: none;
      background-image:
        repeating-linear-gradient(8deg, rgba(244,241,234,.12) 0 1px, rgba(244,241,234,0) 1px 7px);
      mix-blend-mode: soft-light;
    }
    .route {
      position: absolute;
      height: 8px;
      border-radius: 99px;
      background: #E23B35;
      transform-origin: left center;
    }
    .route::after {
      content: "";
      position: absolute;
      right: -14px;
      top: -10px;
      width: 28px;
      height: 28px;
      border: 7px solid #E23B35;
      border-radius: 50%;
      background: #0B0B0C;
    }
    .kicker {
      text-transform: uppercase;
      letter-spacing: .18em;
      font-weight: 350;
      color: #A7A3A0;
    }
    .display {
      margin: 0;
      font-weight: 900;
      letter-spacing: -.045em;
      line-height: .9;
      text-transform: uppercase;
    }
"""


def render_visual_block_html(
    template: str,
    *,
    orientation: str = "landscape",
) -> str:
    """Return a standalone deterministic HyperFrames composition."""
    if template not in VISUAL_BLOCK_TEMPLATES:
        raise ValueError(
            f"unknown visual-block template: {template!r}. "
            f"Use one of {sorted(VISUAL_BLOCK_TEMPLATES)}."
        )
    if orientation not in ORIENTATIONS:
        raise ValueError(
            f"unknown orientation: {orientation!r}. Use one of {sorted(ORIENTATIONS)}."
        )
    width, height = ORIENTATIONS[orientation]
    builders = {
        "day-card": _day_card,
        "before-after": _before_after,
        "focus-callout": _focus_callout,
        "cta-endcard": _cta_endcard,
        "explain-steps": _explain_steps,
    }
    return builders[template](width, height, orientation)


def _variables_attr(items: list[dict[str, object]]) -> str:
    payload = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
    # The attribute itself is single-quoted, so JSON's double quotes must stay
    # literal: HyperFrames' static linter parses the source declaration before
    # a browser has decoded HTML entities.
    return payload.replace("'", "&#39;")


def _document(
    *,
    title: str,
    width: int,
    height: int,
    duration: float,
    variables: list[dict[str, object]],
    css: str,
    body: str,
    script: str,
) -> str:
    return f"""<!doctype html>
<html lang="ru" data-composition-variables='{_variables_attr(variables)}'>
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)}</title>
  <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
  <style>
{_PALETTE_CSS}
{_BASE_CSS}
{css}
  </style>
</head>
<body>
  <div id="root" class="root" data-composition-id="root"
       data-start="0" data-duration="{duration}" data-width="{width}" data-height="{height}">
{body}
  </div>
  <script>
    window.__timelines = window.__timelines || {{}};
    const vars = window.__hyperframes.getVariables();
{script}
    window.__timelines["root"] = tl;
  </script>
</body>
</html>
"""


def _day_card(width: int, height: int, orientation: str) -> str:
    vertical = orientation == "vertical"
    variables = [
        {"id": "day", "type": "string", "label": "Day number", "default": "ДЕНЬ 1"},
        {"id": "title", "type": "string", "label": "Chapter title", "default": "НОВАЯ ГЛАВА"},
        {
            "id": "subtitle",
            "type": "string",
            "label": "One-line explanation",
            "default": "Коротко объясните, что изменилось",
        },
        {"id": "accent", "type": "color", "label": "Accent", "default": "#E23B35"},
        {"id": "background_image", "type": "string", "label": "Next chapter frame", "default": ""},
    ]
    css = f"""
    .oversize {{
      position: absolute;
      right: {-70 if vertical else -40}px;
      top: {150 if vertical else -110}px;
      color: #F4F1EA;
      opacity: .055;
      font-size: {520 if vertical else 620}px;
      font-weight: 900;
      line-height: .8;
    }}
    .content {{
      position: absolute;
      left: {90 if vertical else 150}px;
      right: {90 if vertical else 150}px;
      top: {480 if vertical else 270}px;
    }}
    .kicker {{ font-size: {34 if vertical else 30}px; }}
    .display {{
      max-width: {900 if vertical else 1460}px;
      margin-top: 34px;
      font-size: {118 if vertical else 150}px;
    }}
    .subtitle {{
      max-width: {800 if vertical else 1020}px;
      margin-top: 42px;
      font-size: {40 if vertical else 38}px;
      line-height: 1.24;
      font-weight: 350;
      color: #F4F1EA;
    }}
    .route {{ left: {90 if vertical else 150}px; bottom: {290 if vertical else 120}px; width: {720 if vertical else 980}px; }}
    .backdrop {{
      position: absolute;
      inset: 0;
      background-size: cover;
      background-position: center;
      opacity: .24;
      filter: grayscale(1) contrast(1.08);
    }}
    .backdrop-shade {{
      position: absolute;
      inset: 0;
      background: linear-gradient(90deg, rgba(11,11,12,.97) 0%, rgba(11,11,12,.78) 62%, rgba(11,11,12,.5) 100%);
    }}
    """
    body = """    <div id="backdrop" class="backdrop"></div>
    <div class="backdrop-shade"></div>
    <div id="oversize" class="oversize" aria-hidden="true" data-layout-allow-overflow>04</div>
    <main class="content">
      <div id="day" class="kicker"></div>
      <h1 id="title" class="display"></h1>
      <p id="subtitle" class="subtitle"></p>
    </main>
    <div id="route" class="route"></div>
    <div class="grain"></div>"""
    script = """
    document.documentElement.style.setProperty("--red", String(vars.accent));
    document.getElementById("backdrop").style.backgroundImage = `url("${vars.background_image}")`;
    document.getElementById("day").textContent = vars.day;
    document.getElementById("title").textContent = vars.title;
    document.getElementById("subtitle").textContent = vars.subtitle;
    document.getElementById("oversize").textContent =
      String(vars.day).replace(/\\D/g, "").padStart(2, "0");
    document.getElementById("route").style.backgroundColor = vars.accent;

    const tl = gsap.timeline({ paused: true });
    tl.fromTo("#oversize", { opacity: 0, x: 80 }, { opacity: .055, x: 0, duration: .8, ease: "expo.out" }, .18);
    tl.fromTo("#day", { opacity: 0, x: -36 }, { opacity: 1, x: 0, duration: .32, ease: "power3.out" }, .26);
    tl.fromTo("#title", { opacity: 0, y: 72 }, { opacity: 1, y: 0, duration: .58, ease: "power4.out" }, .4);
    tl.fromTo("#subtitle", { opacity: 0 }, { opacity: 1, duration: .46, ease: "sine.out" }, .78);
    tl.fromTo("#route", { scaleX: 0 }, { scaleX: 1, duration: .66, ease: "power2.out" }, .62);
    tl.to("#oversize", { x: -18, duration: 2.3, ease: "none" }, .98);
    tl.to(".content, #route, #oversize", { opacity: 0, y: -18, duration: .42, ease: "power2.in" }, 3.18);
    tl.to(".backdrop-shade, .grain", { opacity: 0, duration: .5, ease: "sine.inOut" }, 3.18);
    tl.to("#backdrop", { opacity: 1, filter: "grayscale(0) contrast(1)", scale: 1.01, duration: .56, ease: "sine.inOut" }, 3.16);
"""
    return _document(
        title="Day card", width=width, height=height, duration=3.8,
        variables=variables, css=css, body=body, script=script,
    )


def _before_after(width: int, height: int, orientation: str) -> str:
    vertical = orientation == "vertical"
    variables = [
        {"id": "before_image", "type": "string", "label": "Before image", "default": ""},
        {"id": "after_image", "type": "string", "label": "After image", "default": ""},
        {"id": "before_label", "type": "string", "label": "Before label", "default": "ДО"},
        {"id": "after_label", "type": "string", "label": "After label", "default": "ПОСЛЕ"},
        {
            "id": "claim",
            "type": "string",
            "label": "What changed",
            "default": "Ключевое изменение видно в одной сцене",
        },
    ]
    css = f"""
    .media {{
      position: absolute;
      inset: {210 if vertical else 110}px {60 if vertical else 100}px {310 if vertical else 145}px;
      display: grid;
      grid-template-columns: {("1fr" if vertical else "1fr 1fr")};
      grid-template-rows: {("1fr 1fr" if vertical else "1fr")};
      gap: {22 if vertical else 28}px;
    }}
    .card {{
      position: relative;
      overflow: hidden;
      border: 3px solid rgba(244,241,234,.7);
      background: #151515;
      box-shadow: 12px 16px 0 rgba(0,0,0,.42);
    }}
    .image {{
      position: absolute;
      inset: 0;
      background-position: center;
      background-size: cover;
      background-repeat: no-repeat;
    }}
    .label {{
      position: absolute;
      top: 24px;
      padding: 12px 18px 10px;
      background: #F4F1EA;
      color: #151515;
      font-size: {30 if vertical else 28}px;
      font-weight: 900;
      letter-spacing: .1em;
    }}
    #before-label {{ left: 24px; }}
    #after-label {{ left: 24px; background: #E23B35; color: #F4F1EA; }}
    .claim {{
      position: absolute;
      left: {60 if vertical else 100}px;
      right: {60 if vertical else 100}px;
      bottom: {125 if vertical else 54}px;
      margin: 0;
      font-size: {48 if vertical else 44}px;
      font-weight: 800;
      line-height: 1.05;
      letter-spacing: -.025em;
    }}
    .topline {{
      position: absolute;
      left: {60 if vertical else 100}px;
      top: {90 if vertical else 46}px;
      font-size: {30 if vertical else 26}px;
    }}
    """
    body = """    <div class="topline kicker">ОДНА СЦЕНА · ДВА ВИЗУАЛА</div>
    <div id="media" class="media">
      <div id="before-card" class="card">
        <div id="before" class="image" data-layout-allow-overflow></div>
        <div id="before-label" class="label"></div>
      </div>
      <div id="after-card" class="card">
        <div id="after" class="image" data-layout-allow-overflow></div>
        <div id="after-label" class="label"></div>
      </div>
    </div>
    <p id="claim" class="claim"></p>
    <div class="grain"></div>"""
    script = """
    const before = document.getElementById("before");
    const after = document.getElementById("after");
    if (vars.before_image) before.style.backgroundImage = `url("${vars.before_image}")`;
    if (vars.after_image) after.style.backgroundImage = `url("${vars.after_image}")`;
    document.getElementById("before-label").textContent = vars.before_label;
    document.getElementById("after-label").textContent = vars.after_label;
    document.getElementById("claim").textContent = vars.claim;

    const tl = gsap.timeline({ paused: true });
    tl.fromTo("#before-card", { opacity: 0, x: -52 }, { opacity: 1, x: 0, duration: .58, ease: "power3.out" }, .16);
    tl.fromTo("#after-card", { opacity: 0, x: 52 }, { opacity: 1, x: 0, duration: .58, ease: "power3.out" }, .28);
    tl.fromTo("#before-label", { opacity: 0, x: -28 }, { opacity: 1, x: 0, duration: .28, ease: "expo.out" }, .48);
    tl.fromTo("#after-label", { opacity: 0, x: 28 }, { opacity: 1, x: 0, duration: .34, ease: "power4.out" }, .54);
    tl.fromTo("#claim", { opacity: 0, y: 34 }, { opacity: 1, y: 0, duration: .42, ease: "sine.out" }, .72);
    tl.to("#before", { scale: 1.018, duration: 3.0, ease: "none" }, .8);
    tl.to("#after", { scale: 1.018, duration: 3.0, ease: "none" }, .8);
"""
    return _document(
        title="Before / after", width=width, height=height, duration=4.2,
        variables=variables, css=css, body=body, script=script,
    )


def _focus_callout(width: int, height: int, orientation: str) -> str:
    vertical = orientation == "vertical"
    variables = [
        {"id": "image", "type": "string", "label": "Gameplay image", "default": ""},
        {"id": "label", "type": "string", "label": "Callout label", "default": "ГЛАВНАЯ ДЕТАЛЬ"},
        {
            "id": "explanation",
            "type": "string",
            "label": "Short explanation",
            "default": "Объясните, на что смотреть",
        },
        {"id": "focus_x", "type": "number", "label": "Focus X percent", "default": 68},
        {"id": "focus_y", "type": "number", "label": "Focus Y percent", "default": 42},
    ]
    css = f"""
    .game {{
      position: absolute;
      inset: {170 if vertical else 74}px {56 if vertical else 78}px {310 if vertical else 74}px;
      overflow: hidden;
      border: 3px solid rgba(244,241,234,.65);
      background:
        radial-gradient(circle at 68% 42%, rgba(226,59,53,.25), rgba(21,21,21,.15) 24%, #151515 65%);
      box-shadow: 20px 24px 0 rgba(0,0,0,.42);
    }}
    #image {{
      position: absolute;
      inset: -1.5%;
      background-size: cover;
      background-position: center;
    }}
    .shade {{
      position: absolute;
      inset: 0;
      background: linear-gradient(180deg, rgba(11,11,12,.05) 45%, rgba(11,11,12,.88) 100%);
    }}
    .ring {{
      position: absolute;
      width: {210 if vertical else 190}px;
      height: {210 if vertical else 190}px;
      margin: {-105 if vertical else -95}px 0 0 {-105 if vertical else -95}px;
      border: 10px solid #E23B35;
      border-radius: 50%;
      box-shadow: 0 0 0 5px rgba(11,11,12,.65);
    }}
    .copy {{
      position: absolute;
      left: {82 if vertical else 118}px;
      right: {82 if vertical else 118}px;
      bottom: {335 if vertical else 100}px;
      display: flex;
      align-items: center;
      gap: 24px;
      padding: 20px 24px;
      background: rgba(11,11,12,.92);
      border-left: 10px solid #E23B35;
      box-shadow: 12px 14px 0 rgba(0,0,0,.35);
    }}
    .copy strong {{
      flex: 0 0 auto;
      padding: 13px 18px 11px;
      background: #E23B35;
      font-size: {34 if vertical else 32}px;
      letter-spacing: .06em;
    }}
    .copy span {{
      font-size: {40 if vertical else 38}px;
      font-weight: 500;
      line-height: 1.12;
      color: #F4F1EA;
    }}
    """
    body = """    <div id="game" class="game">
      <div id="image" data-layout-allow-overflow></div>
      <div class="shade"></div>
      <div id="ring" class="ring"></div>
    </div>
    <div class="copy"><strong id="label"></strong><span id="explanation"></span></div>
    <div class="grain"></div>"""
    script = """
    const fx = Math.max(8, Math.min(92, Number(vars.focus_x)));
    const fy = Math.max(8, Math.min(92, Number(vars.focus_y)));
    if (vars.image) document.getElementById("image").style.backgroundImage = `url("${vars.image}")`;
    const ring = document.getElementById("ring");
    ring.style.left = `${fx}%`;
    ring.style.top = `${fy}%`;
    document.getElementById("label").textContent = vars.label;
    document.getElementById("explanation").textContent = vars.explanation;

    const tl = gsap.timeline({ paused: true });
    tl.fromTo("#game", { opacity: 0, y: 42 }, { opacity: 1, y: 0, duration: .58, ease: "power3.out" }, .15);
    tl.fromTo("#ring", { opacity: 0, scale: 1.7 }, { opacity: 1, scale: 1, duration: .42, ease: "expo.out" }, .6);
    tl.fromTo(".copy", { opacity: 0, x: -36 }, { opacity: 1, x: 0, duration: .46, ease: "power4.out" }, .82);
    tl.to("#image", { scale: 1.035, duration: 3.2, ease: "none" }, .7);
    tl.to("#ring", { scale: 1.06, duration: .8, repeat: 2, yoyo: true, ease: "sine.inOut" }, 1.1);
"""
    return _document(
        title="Focus callout", width=width, height=height, duration=4.4,
        variables=variables, css=css, body=body, script=script,
    )


def _cta_endcard(width: int, height: int, orientation: str) -> str:
    vertical = orientation == "vertical"
    variables = [
        {
            "id": "game_title",
            "type": "string",
            "label": "Public game title",
            "default": "YOUR GAME",
        },
        {
            "id": "eyebrow",
            "type": "string",
            "label": "Context",
            "default": "СТРАНИЦА ИГРЫ",
        },
        {
            "id": "cta",
            "type": "string",
            "label": "Call to action",
            "default": "ДОБАВЬ В ВИШЛИСТ",
        },
        {
            "id": "steam_url",
            "type": "string",
            "label": "Canonical Steam URL",
            "default": "store.steampowered.com",
        },
        {
            "id": "episode",
            "type": "string",
            "label": "Public episode label",
            "default": "DEVLOG",
        },
        {
            "id": "background_image",
            "type": "string",
            "label": "Real product frame",
            "default": "",
        },
    ]
    css = f"""
    .frame {{
      position: absolute;
      inset: {80 if vertical else 58}px;
      border: 3px solid rgba(244,241,234,.5);
    }}
    .number {{
      position: absolute;
      right: {24 if vertical else 66}px;
      top: {210 if vertical else -75}px;
      font-size: {500 if vertical else 560}px;
      font-weight: 900;
      line-height: .8;
      color: #F4F1EA;
      opacity: .045;
    }}
    .content {{
      position: absolute;
      left: {100 if vertical else 150}px;
      right: {100 if vertical else 150}px;
      top: {450 if vertical else 245}px;
    }}
    .kicker {{ font-size: {31 if vertical else 28}px; color: #E23B35; }}
    .title {{
      max-width: {860 if vertical else 1450}px;
      margin-top: 34px;
      font-size: {108 if vertical else 132}px;
    }}
    .cta {{
      display: inline-block;
      margin-top: 58px;
      padding: 22px 28px 18px;
      background: #E23B35;
      color: #F4F1EA;
      font-size: {48 if vertical else 46}px;
      font-weight: 900;
      letter-spacing: -.02em;
    }}
    .url {{
      position: absolute;
      left: {100 if vertical else 150}px;
      bottom: {240 if vertical else 105}px;
      font-family: "JetBrains Mono", monospace;
      font-size: {26 if vertical else 25}px;
      color: #A7A3A0;
      font-variant-ligatures: none;
    }}
    .route {{ left: {100 if vertical else 150}px; bottom: {340 if vertical else 175}px; width: {710 if vertical else 920}px; }}
    .backdrop {{
      position: absolute;
      inset: 0;
      background-size: cover;
      background-position: center;
      opacity: .46;
      filter: grayscale(.45) contrast(1.08);
    }}
    .backdrop-shade {{
      position: absolute;
      inset: 0;
      background: linear-gradient(90deg, rgba(11,11,12,.96) 0%, rgba(11,11,12,.72) 58%, rgba(11,11,12,.28) 100%);
    }}
    """
    body = """    <div id="backdrop" class="backdrop"></div>
    <div class="backdrop-shade"></div>
    <div class="frame"></div>
    <div id="number" class="number" aria-hidden="true"></div>
    <main class="content">
      <div id="eyebrow" class="kicker"></div>
      <h1 id="game-title" class="display title"></h1>
      <div id="cta" class="cta"></div>
    </main>
    <div id="route" class="route"></div>
    <div id="url" class="url"></div>
    <div class="grain"></div>"""
    script = """
    document.getElementById("game-title").textContent = vars.game_title;
    document.getElementById("eyebrow").textContent = vars.eyebrow;
    document.getElementById("cta").textContent = vars.cta;
    document.getElementById("url").textContent = vars.steam_url;
    document.getElementById("number").textContent = vars.episode;
    document.getElementById("backdrop").style.backgroundImage = `url("${vars.background_image}")`;

    const tl = gsap.timeline({ paused: true });
    tl.fromTo(".frame", { opacity: 0 }, { opacity: 1, duration: .72, ease: "sine.out" }, .18);
    tl.fromTo("#number", { opacity: 0, x: 90 }, { opacity: .045, x: 0, duration: .85, ease: "expo.out" }, .22);
    tl.fromTo("#eyebrow", { opacity: 0, x: -32 }, { opacity: 1, x: 0, duration: .32, ease: "power3.out" }, .34);
    tl.fromTo("#game-title", { opacity: 0, y: 64 }, { opacity: 1, y: 0, duration: .6, ease: "power4.out" }, .5);
    tl.fromTo("#route", { scaleX: 0 }, { scaleX: 1, duration: .68, ease: "power2.out" }, .76);
    tl.fromTo("#cta", { opacity: 0, scale: .92 }, { opacity: 1, scale: 1, duration: .4, ease: "back.out(1.35)" }, .92);
    tl.fromTo("#url", { opacity: 0 }, { opacity: 1, duration: .5, ease: "sine.out" }, 1.18);
    tl.to("#number", { x: -20, duration: 3.1, ease: "none" }, 1.12);
"""
    return _document(
        title="Wishlist CTA", width=width, height=height, duration=4.8,
        variables=variables, css=css, body=body, script=script,
    )


def _explain_steps(width: int, height: int, orientation: str) -> str:
    vertical = orientation == "vertical"
    variables = [
        {"id": "title", "type": "string", "label": "Explainer title", "default": "КАК СОБРАЛСЯ ВИЗУАЛ"},
        {"id": "step_1", "type": "string", "label": "Step 1", "default": "ПЕРВЫЙ ШАГ"},
        {"id": "step_2", "type": "string", "label": "Step 2", "default": "ВТОРОЙ ШАГ"},
        {"id": "step_3", "type": "string", "label": "Step 3", "default": "ТРЕТИЙ ШАГ"},
        {"id": "step_4", "type": "string", "label": "Step 4", "default": "ИТОГ"},
    ]
    css = f"""
    .content {{
      position: absolute;
      inset: {230 if vertical else 130}px {70 if vertical else 110}px;
    }}
    .title {{
      max-width: {900 if vertical else 1500}px;
      font-size: {86 if vertical else 108}px;
    }}
    .steps {{
      display: grid;
      grid-template-columns: {("1fr" if vertical else "repeat(4, 1fr)")};
      grid-template-rows: {("repeat(4, 1fr)" if vertical else "1fr")};
      gap: {20 if vertical else 26}px;
      margin-top: {70 if vertical else 90}px;
    }}
    .step {{
      position: relative;
      min-height: {220 if vertical else 340}px;
      padding: {34 if vertical else 38}px;
      border: 2px solid rgba(244,241,234,.32);
      background: rgba(244,241,234,.055);
      overflow: hidden;
    }}
    .step::before {{
      content: attr(data-number);
      display: block;
      margin-bottom: {22 if vertical else 60}px;
      color: #E23B35;
      font-size: {31 if vertical else 28}px;
      font-weight: 900;
    }}
    .step span {{
      display: block;
      font-size: {42 if vertical else 39}px;
      font-weight: 800;
      line-height: 1.05;
      letter-spacing: -.03em;
    }}
    .sample {{
      position: absolute;
      left: 38px;
      right: 38px;
      bottom: 34px;
      height: {48 if vertical else 74}px;
      border: 2px solid rgba(244,241,234,.38);
      background-color: #F4F1EA;
    }}
    .graphite {{
      background-image: repeating-linear-gradient(165deg, #151515 0 3px, transparent 3px 11px);
    }}
    .paper {{
      background-image:
        repeating-linear-gradient(8deg, rgba(21,21,21,.25) 0 1px, transparent 1px 7px),
        linear-gradient(#F4F1EA, #D9D4C9);
    }}
    .shadow {{
      background: radial-gradient(ellipse at 55% 65%, rgba(21,21,21,.8), transparent 55%), #F4F1EA;
    }}
    .contrast {{
      background: linear-gradient(100deg, #0B0B0C 0 48%, #E23B35 48% 56%, #F4F1EA 56%);
    }}
    .step-bar {{
      position: absolute;
      left: 0;
      right: 0;
      bottom: 0;
      height: 9px;
      background: #E23B35;
      transform-origin: left;
    }}
    """
    body = """    <main class="content">
      <h1 id="title" class="display title"></h1>
      <div class="steps">
        <div class="step" data-number="01"><span id="step-1"></span><i class="sample graphite"></i><i class="step-bar"></i></div>
        <div class="step" data-number="02"><span id="step-2"></span><i class="sample paper"></i><i class="step-bar"></i></div>
        <div class="step" data-number="03"><span id="step-3"></span><i class="sample shadow"></i><i class="step-bar"></i></div>
        <div class="step" data-number="04"><span id="step-4"></span><i class="sample contrast"></i><i class="step-bar"></i></div>
      </div>
    </main>
    <div class="grain"></div>"""
    script = """
    document.getElementById("title").textContent = vars.title;
    [vars.step_1, vars.step_2, vars.step_3, vars.step_4].forEach((value, index) => {
      document.getElementById(`step-${index + 1}`).textContent = value;
    });

    const tl = gsap.timeline({ paused: true });
    tl.fromTo("#title", { opacity: 0, x: -54 }, { opacity: 1, x: 0, duration: .5, ease: "power4.out" }, .18);
    tl.fromTo(".step", { opacity: 0, y: 46 }, { opacity: 1, y: 0, duration: .46, stagger: .11, ease: "power3.out" }, .48);
    tl.fromTo(".sample", { opacity: 0, scaleX: .2 }, { opacity: 1, scaleX: 1, duration: .46, stagger: .62, ease: "power3.out" }, 1.02);
    tl.fromTo(".step-bar", { scaleX: 0 }, { scaleX: 1, duration: .5, stagger: .62, ease: "expo.out" }, 1.12);
    tl.to(".step", { backgroundColor: "rgba(226,59,53,.11)", duration: .36, stagger: .62, ease: "sine.inOut" }, 1.12);
"""
    return _document(
        title="Four-step explainer", width=width, height=height, duration=4.8,
        variables=variables, css=css, body=body, script=script,
    )
