"""Build code-stats infographics for devlog: commit bar chart, file treemap.
Output: data/infographics/*.png at 1920x1080 in brand palette."""
import os, math, subprocess
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

GAME_DIR = r"C:\projects\game-ai-gamedevjs2026"
OUT_DIR = Path(r"C:\projects\devlogs\trolley\data\infographics")
OUT_DIR.mkdir(parents=True, exist_ok=True)

W, H = 1920, 1080
COL_BG    = (26, 22, 18)
COL_GOLD  = (232, 182, 71)
COL_GOLD_DIM = (224, 174, 69)
COL_RED   = (192, 57, 43)
COL_FG_DIM = (140, 130, 110)

FONT_BLACK = r"C:\Windows\Fonts\tahomabd.ttf"
FONT_BOLD  = r"C:\Windows\Fonts\bahnschrift.ttf"
FONT_MONO  = r"C:\Windows\Fonts\consolab.ttf"


def vignette():
    """Radial vignette for cinematic darkening."""
    vg = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cx, cy = W // 2, H // 2
    max_r = math.hypot(cx, cy)
    for yy in range(0, H, 4):
        for xx in range(0, W, 4):
            r = math.hypot(xx - cx, yy - cy) / max_r
            alpha = int(110 * (r ** 1.8))
            vg.paste((0, 0, 0, alpha), (xx, yy, xx + 4, yy + 4))
    return vg.filter(ImageFilter.GaussianBlur(10))


def title_with_underline(draw, text, y, color=COL_GOLD, size=72, sub=None, sub_color=None):
    """Title + red underline below + optional subtitle."""
    f = ImageFont.truetype(FONT_BLACK, size)
    bbox = draw.textbbox((0, 0), text, font=f, anchor="lt")
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (W - tw) // 2
    # Shadow
    draw.text((tx + 3, y + 3), text, fill=(0, 0, 0), font=f, anchor="lt")
    draw.text((tx, y), text, fill=color, font=f, anchor="lt")
    # Red underline 480px centered below
    ul_y = y + th + 18
    draw.rectangle(((W - 480) // 2, ul_y, (W + 480) // 2, ul_y + 6), fill=COL_RED)
    if sub:
        sf = ImageFont.truetype(FONT_BLACK, int(size * 0.36))
        sb = draw.textbbox((0, 0), sub, font=sf, anchor="lt")
        sw = sb[2] - sb[0]
        draw.text(((W - sw) // 2, ul_y + 24), sub, fill=sub_color or COL_GOLD_DIM, font=sf, anchor="lt")
    return ul_y + 60


def get_commits_by_day():
    """Read git log, group commits by date in jam window 2026-04-14..2026-04-26."""
    r = subprocess.run(
        ["git", "-C", GAME_DIR, "log", "--pretty=format:%ad", "--date=short"],
        capture_output=True, text=True, encoding="utf-8"
    )
    counts = {}
    for line in r.stdout.splitlines():
        counts[line] = counts.get(line, 0) + 1
    # Filter jam window
    jam_start = "2026-04-14"
    jam_end = "2026-04-26"
    days = []
    from datetime import date, timedelta
    d = date.fromisoformat(jam_start)
    end = date.fromisoformat(jam_end)
    while d <= end:
        key = d.isoformat()
        days.append((key, counts.get(key, 0), (d - date.fromisoformat(jam_start)).days + 1))
        d += timedelta(days=1)
    return days


def build_commit_chart():
    """Bar chart of commits per day across 13-day jam."""
    canvas = Image.new("RGB", (W, H), COL_BG)
    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba.alpha_composite(vignette())
    canvas = canvas_rgba.convert("RGB")
    draw = ImageDraw.Draw(canvas)

    next_y = title_with_underline(draw, "273 КОММИТА", 90, size=120, sub="ЗА 13 ДНЕЙ ДЖЕМА")

    days = get_commits_by_day()
    total = sum(c for _, c, _ in days)

    # Bar chart area
    bar_area_top = next_y + 60
    bar_area_h = 540  # height for bars
    bar_area_bottom = bar_area_top + bar_area_h
    left_pad = 130
    right_pad = 130
    chart_w = W - left_pad - right_pad
    bar_count = len(days)
    bar_gap = 12
    bar_w = (chart_w - bar_gap * (bar_count - 1)) // bar_count

    # Baseline
    draw.line([(left_pad, bar_area_bottom), (W - right_pad, bar_area_bottom)], fill=COL_GOLD, width=4)

    max_count = max(c for _, c, _ in days)
    fnum = ImageFont.truetype(FONT_BOLD, 36)
    fday = ImageFont.truetype(FONT_BOLD, 30)

    for i, (date_str, count, day_n) in enumerate(days):
        bar_h = int(bar_area_h * (count / max_count)) if count > 0 else 0
        bx = left_pad + i * (bar_w + bar_gap)
        by_top = bar_area_bottom - bar_h
        # Bar with shadow
        if bar_h > 0:
            shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            sd = ImageDraw.Draw(shadow)
            sd.rectangle((bx + 4, by_top + 4, bx + bar_w + 4, bar_area_bottom),
                         fill=(0, 0, 0, 180))
            shadow = shadow.filter(ImageFilter.GaussianBlur(6))
            canvas_rgba = canvas.convert("RGBA")
            canvas_rgba.paste(shadow, (0, 0), shadow)
            canvas = canvas_rgba.convert("RGB")
            draw = ImageDraw.Draw(canvas)
            # Bar
            draw.rectangle((bx, by_top, bx + bar_w, bar_area_bottom), fill=COL_GOLD)
            # Count above
            cnt_str = str(count)
            cb = draw.textbbox((0, 0), cnt_str, font=fnum, anchor="lt")
            cw = cb[2] - cb[0]
            draw.text((bx + (bar_w - cw) // 2, by_top - 50), cnt_str, fill=COL_GOLD, font=fnum, anchor="lt")
        # Day number below
        day_str = f"Д{day_n}"
        db = draw.textbbox((0, 0), day_str, font=fday, anchor="lt")
        dw = db[2] - db[0]
        draw.text((bx + (bar_w - dw) // 2, bar_area_bottom + 20),
                  day_str, fill=COL_GOLD, font=fday, anchor="lt")

    # Bottom note
    f_note = ImageFont.truetype(FONT_BLACK, 36)
    note = "26 АПРЕЛЯ · СДАЧА В JAM"
    nb = draw.textbbox((0, 0), note, font=f_note, anchor="lt")
    nw = nb[2] - nb[0]
    draw.text(((W - nw) // 2, bar_area_bottom + 80),
              note, fill=COL_GOLD_DIM, font=f_note, anchor="lt")

    out = OUT_DIR / "commits_chart.png"
    canvas.save(out)
    print(f"wrote {out}  total commits in window: {total}")
    return out


def get_file_stats():
    """Count files and lines per type in src/, grouped by 3rd-level dir (src/features/<area>/<module>)."""
    src = Path(GAME_DIR) / "src"
    by_ext = {}
    by_dir = {}
    for f in src.rglob("*"):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext != ".js":  # JS only for cleaner breakdown
            continue
        try:
            n = sum(1 for _ in f.read_text(encoding="utf-8", errors="ignore").splitlines())
        except Exception:
            n = 0
        by_ext.setdefault(ext, [0, 0])
        by_ext[ext][0] += 1
        by_ext[ext][1] += n
        # Group by 3rd-level dir: src/features/trolley/<group>
        parts = f.relative_to(src).parts
        if len(parts) >= 3 and parts[0] == "features":
            group = f"{parts[1]}/{parts[2]}"  # trolley/ui, core/graphics
        elif len(parts) >= 2:
            group = parts[0]
        else:
            group = "root"
        by_dir.setdefault(group, [0, 0])
        by_dir[group][0] += 1
        by_dir[group][1] += n
    return by_ext, by_dir


def build_files_breakdown():
    """Stacked bar of file/line breakdown by top-level dir."""
    canvas = Image.new("RGB", (W, H), COL_BG)
    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba.alpha_composite(vignette())
    canvas = canvas_rgba.convert("RGB")
    draw = ImageDraw.Draw(canvas)

    next_y = title_with_underline(draw, "30 000 СТРОК КОДА", 50, size=100, sub="100% ИИ")

    by_ext, by_dir = get_file_stats()
    # Sort dirs by line count desc, top 8
    dirs = sorted(by_dir.items(), key=lambda kv: -kv[1][1])[:8]
    total_lines = sum(v[1] for v in by_dir.values())
    total_files = sum(v[0] for v in by_dir.values())

    # Right-side: horizontal bars per dir. Content must end before y=760 (bottom overlay band starts at ~780).
    list_top = next_y + 10
    row_h = 60
    f_dir = ImageFont.truetype(FONT_BLACK, 34)
    f_count = ImageFont.truetype(FONT_BOLD, 24)
    f_meta = ImageFont.truetype(FONT_BOLD, 28)
    max_lines = max(v[1] for _, v in dirs)
    bar_left = 620
    bar_max_w = W - bar_left - 200
    for i, (dname, (fcount, lcount)) in enumerate(dirs):
        ry = list_top + i * row_h
        draw.text((130, ry + 10), dname, fill=COL_GOLD, font=f_dir, anchor="lt")
        dir_w = draw.textbbox((0, 0), dname, font=f_dir, anchor="lt")[2]
        count_str = f"  {fcount} файлов"
        draw.text((130 + dir_w, ry + 16), count_str, fill=COL_GOLD_DIM, font=f_count, anchor="lt")
        bar_h = 38
        draw.rectangle((bar_left, ry + 12, bar_left + bar_max_w, ry + 12 + bar_h),
                       fill=(40, 35, 28))
        bw = int(bar_max_w * (lcount / max_lines))
        draw.rectangle((bar_left, ry + 12, bar_left + bw, ry + 12 + bar_h),
                       fill=COL_GOLD)
        lstr = f"{lcount:,}".replace(",", " ")
        draw.text((bar_left + bw + 16, ry + 16), lstr, fill=COL_GOLD, font=f_meta, anchor="lt")

    # No totals line — overlay plate text already carries "30 000 СТРОК / ВЕСЬ ПРОЕКТ — ИИ"

    out = OUT_DIR / "files_breakdown.png"
    canvas.save(out)
    print(f"wrote {out}  {total_files} files, {total_lines} lines")
    return out


def build_daily_views():
    """Daily-views infographic for itch stats reveal. Data approximated from analytics screenshot
    (2026-04-12 → 2026-05-12, with Apr 26 submission spike + May 5-7 Wavedash spike)."""
    # Days from Apr 12 to May 12 (31 days). Approximated values from the itch analytics chart.
    from datetime import date, timedelta
    start = date(2026, 4, 12)
    # Values from project memory: spike 1 ~Apr 26 (post-submission) ~2.5k/day, spike 2 ~May 7 ~6.5k/day
    days_data = [
        (0,  20), (1,  30), (2,  25), (3,  40), (4,  30), (5,  20), (6,  25),
        (7,  40), (8,  50), (9,  60), (10, 80), (11, 100), (12, 150), (13, 250),
        (14, 2500),  # Apr 26 — submission spike
        (15, 2200), (16, 1700), (17, 900), (18, 600), (19, 450), (20, 400),
        (21, 380), (22, 350), (23, 2000),  # May 5 spike start
        (24, 6500),  # May 7 — Wavedash / press peak (largest)
        (25, 4500), (26, 2500), (27, 1500), (28, 1000), (29, 800), (30, 700),
    ]

    canvas = Image.new("RGB", (W, H), COL_BG)
    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba.alpha_composite(vignette())
    canvas = canvas_rgba.convert("RGB")
    draw = ImageDraw.Draw(canvas)

    next_y = title_with_underline(draw, "30 000 ПРОСМОТРОВ", 70, size=100, sub="ЗА 30 ДНЕЙ · ITCH.IO")

    bar_area_top = next_y + 100  # extra room for spike annotations above bars
    bar_area_h = 380
    bar_area_bottom = bar_area_top + bar_area_h
    left_pad = 100
    right_pad = 100
    chart_w = W - left_pad - right_pad
    bar_count = len(days_data)
    bar_gap = 6
    bar_w = (chart_w - bar_gap * (bar_count - 1)) // bar_count

    draw.line([(left_pad, bar_area_bottom), (W - right_pad, bar_area_bottom)], fill=COL_GOLD, width=4)
    max_val = max(v for _, v in days_data)
    fnum = ImageFont.truetype(FONT_BOLD, 26)
    flbl = ImageFont.truetype(FONT_BOLD, 22)

    spike_dates = {14, 24}  # Apr 26 + May 7 are special — annotate
    for i, (day_idx, val) in enumerate(days_data):
        bar_h = int(bar_area_h * (val / max_val)) if val > 0 else 0
        bx = left_pad + i * (bar_w + bar_gap)
        by_top = bar_area_bottom - bar_h
        color = COL_RED if day_idx in spike_dates else COL_GOLD
        if bar_h > 0:
            draw.rectangle((bx, by_top, bx + bar_w, bar_area_bottom), fill=color)
        # Spike annotation on big bars
        if day_idx in spike_dates:
            lbl = "26 АПР · JAM" if day_idx == 14 else "7 МАЯ · ТОП-2"
            draw.text((bx - 30, by_top - 36), lbl, fill=COL_RED, font=flbl, anchor="lt")
            draw.text((bx + bar_w // 2, by_top - 70), str(val), fill=COL_GOLD, font=fnum, anchor="mt")

    # Axis labels at bottom
    f_axis = ImageFont.truetype(FONT_BOLD, 28)
    for week_n, label in [(0, "12 АПР"), (7, "19 АПР"), (14, "26 АПР"), (21, "3 МАЯ"), (28, "10 МАЯ")]:
        bx = left_pad + week_n * (bar_w + bar_gap)
        draw.text((bx, bar_area_bottom + 18), label, fill=COL_GOLD, font=f_axis, anchor="lt")

    # Bottom note removed — overlay band sits here in a3-6, would occlude
    out = OUT_DIR / "daily_views.png"
    canvas.save(out)
    print(f"wrote {out}")
    return out


def build_hype_curve():
    """Gartner-style AI hype curve. 'Вы здесь' marker at peak. For a2-2 ВОКРУГ ИИ ХАЙП beat."""
    canvas = Image.new("RGB", (W, H), COL_BG)
    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba.alpha_composite(vignette())
    canvas = canvas_rgba.convert("RGB")
    draw = ImageDraw.Draw(canvas)

    next_y = title_with_underline(draw, "ХАЙП-ЦИКЛ ИИ", 70, size=100, sub="ГДЕ МЫ СЕЙЧАС")

    # Curve area
    cx_left = 200
    cx_right = W - 200
    cy_base = 820
    cy_top = next_y + 60
    chart_w = cx_right - cx_left
    chart_h = cy_base - cy_top

    # Baseline axis
    draw.line([(cx_left, cy_base), (cx_right, cy_base)], fill=COL_GOLD, width=4)

    # Gartner hype curve: gentle rise → sharp peak → trough → plateau
    # Bezier-like via points
    pts = []
    n = 80
    for i in range(n + 1):
        x = cx_left + chart_w * (i / n)
        # piecewise: 0-0.25 slow rise, 0.25-0.4 peak, 0.4-0.6 trough, 0.6-1.0 slope of enlightenment + plateau
        t = i / n
        if t < 0.25:
            y_norm = 0.15 * (t / 0.25)
        elif t < 0.4:
            tt = (t - 0.25) / 0.15
            y_norm = 0.15 + 0.85 * (3 * tt ** 2 - 2 * tt ** 3)
        elif t < 0.6:
            tt = (t - 0.4) / 0.20
            y_norm = 1.0 - 0.75 * (3 * tt ** 2 - 2 * tt ** 3)
        else:
            tt = (t - 0.6) / 0.4
            y_norm = 0.25 + 0.30 * (3 * tt ** 2 - 2 * tt ** 3)
        y = cy_base - int(chart_h * y_norm)
        pts.append((x, y))

    # Draw curve as thick line segments
    for i in range(len(pts) - 1):
        draw.line([pts[i], pts[i + 1]], fill=COL_GOLD, width=8)

    # "ВЫ ЗДЕСЬ" marker at peak (~t=0.38)
    peak_idx = int(0.38 * n)
    px, py = pts[peak_idx]
    # Red dot
    r = 22
    draw.ellipse((px - r, py - r, px + r, py + r), fill=COL_RED, outline=COL_GOLD, width=4)
    # Label box
    f_mark = ImageFont.truetype(FONT_BLACK, 44)
    lbl = "ВЫ ЗДЕСЬ"
    lb = draw.textbbox((0, 0), lbl, font=f_mark, anchor="lt")
    lw = lb[2] - lb[0]
    lh = lb[3] - lb[1]
    bx1 = px + 40
    by1 = py - lh - 30
    bx2 = bx1 + lw + 50
    by2 = by1 + lh + 40
    draw.rounded_rectangle((bx1, by1, bx2, by2), radius=12, fill=COL_RED)
    draw.text((bx1 + 25 + 3, by1 + 17 + 3), lbl, fill=(0, 0, 0), font=f_mark, anchor="lt")
    draw.text((bx1 + 25, by1 + 17), lbl, fill=(255, 255, 255), font=f_mark, anchor="lt")
    # Line from dot to label
    draw.line([(px + r, py), (bx1, by1 + (by2 - by1) // 2)], fill=COL_RED, width=4)

    # X-axis stage labels
    f_stage = ImageFont.truetype(FONT_BOLD, 32)
    stages = [
        (cx_left + chart_w * 0.10, "ТРИГГЕР"),
        (cx_left + chart_w * 0.38, "ПИК ХАЙПА"),
        (cx_left + chart_w * 0.58, "РАЗОЧАРОВАНИЕ"),
        (cx_left + chart_w * 0.85, "ПЛАТО"),
    ]
    for x, label in stages:
        bb = draw.textbbox((0, 0), label, font=f_stage, anchor="lt")
        w = bb[2] - bb[0]
        draw.text((x - w // 2, cy_base + 22), label, fill=COL_GOLD, font=f_stage, anchor="lt")

    # Attribution moved to title subtitle (above overlay band area)

    out = OUT_DIR / "hype_curve.png"
    canvas.save(out)
    print(f"wrote {out}")
    return out


def _hype_curve_pts(cx_left, cx_right, cy_base, cy_top):
    """Return list of (x,y) points for the Gartner hype curve."""
    chart_w = cx_right - cx_left
    chart_h = cy_base - cy_top
    pts = []
    n = 80
    for i in range(n + 1):
        t = i / n
        if t < 0.25:
            y_norm = 0.15 * (t / 0.25)
        elif t < 0.4:
            tt = (t - 0.25) / 0.15
            y_norm = 0.15 + 0.85 * (3 * tt ** 2 - 2 * tt ** 3)
        elif t < 0.6:
            tt = (t - 0.4) / 0.20
            y_norm = 1.0 - 0.75 * (3 * tt ** 2 - 2 * tt ** 3)
        else:
            tt = (t - 0.6) / 0.4
            y_norm = 0.25 + 0.30 * (3 * tt ** 2 - 2 * tt ** 3)
        x = cx_left + chart_w * (i / n)
        y = cy_base - int(chart_h * y_norm)
        pts.append((x, y))
    return pts


def build_hype_curve_frame(progress, cx_left, cx_right, cy_base, cy_top, pts, title_img):
    """Render one animation frame. title_img: pre-rendered RGBA canvas with title+axes."""
    canvas = title_img.copy().convert("RGB")
    draw = ImageDraw.Draw(canvas)
    chart_w = cx_right - cx_left
    n_pts = len(pts)
    n_draw = max(2, int(progress * (n_pts - 1)))

    # Draw curve segments up to progress
    for i in range(n_draw - 1):
        draw.line([pts[i], pts[i + 1]], fill=COL_GOLD, width=8)

    # Stage labels appear as curve passes their x position
    stages = [
        (cx_left + chart_w * 0.10, "ТРИГГЕР"),
        (cx_left + chart_w * 0.38, "ПИК ХАЙПА"),
        (cx_left + chart_w * 0.58, "РАЗОЧАРОВАНИЕ"),
        (cx_left + chart_w * 0.85, "ПЛАТО"),
    ]
    f_stage = ImageFont.truetype(FONT_BOLD, 32)
    curve_x = pts[n_draw - 1][0]
    for sx, label in stages:
        if curve_x >= sx:
            bb = draw.textbbox((0, 0), label, font=f_stage, anchor="lt")
            w = bb[2] - bb[0]
            draw.text((sx - w // 2, cy_base + 22), label, fill=COL_GOLD, font=f_stage, anchor="lt")

    # "ВЫ ЗДЕСЬ" marker pops in when curve passes the peak
    peak_idx = int(0.38 * (n_pts - 1))
    if n_draw > peak_idx:
        marker_progress = min(1.0, (n_draw - peak_idx) / 8.0)
        alpha = int(255 * marker_progress)
        px, py = pts[peak_idx]
        r = 22
        draw.ellipse((px - r, py - r, px + r, py + r), fill=COL_RED, outline=COL_GOLD, width=4)
        if marker_progress > 0.3:
            f_mark = ImageFont.truetype(FONT_BLACK, 44)
            lbl = "ВЫ ЗДЕСЬ"
            lb = draw.textbbox((0, 0), lbl, font=f_mark, anchor="lt")
            lw = lb[2] - lb[0]
            lh = lb[3] - lb[1]
            # Label below the dot (avoids collision with title subtitle at top)
            bx1 = px - lw // 2 - 25
            by1 = py + r + 12
            bx2 = bx1 + lw + 50
            by2 = by1 + lh + 40
            a = int(255 * min(1.0, (marker_progress - 0.3) / 0.4))
            overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            od = ImageDraw.Draw(overlay)
            od.rounded_rectangle((bx1, by1, bx2, by2), radius=12,
                                  fill=(*COL_RED, a))
            od.text((bx1 + 28, by1 + 20), lbl, fill=(255, 255, 255, a), font=f_mark, anchor="lt")
            od.line([(px, py + r), (px, by1)],
                    fill=(*COL_RED, a), width=4)
            canvas = canvas.convert("RGBA")
            canvas.alpha_composite(overlay)
            canvas = canvas.convert("RGB")

    return np.array(canvas)


def build_hype_curve_anim():
    """Animated hype curve — line draws left to right, ВЫ ЗДЕСЬ marker pops in at peak. Output: MP4."""
    try:
        from moviepy import ImageSequenceClip
    except ImportError:
        print("moviepy not available for animation")
        return None

    cx_left, cx_right = 200, W - 200
    cy_base = 820
    # Build title+axes base image (no curve, no labels)
    # iter_70: city bg alpha-blend so chart has warm texture not flat #1a1612
    _city = Image.open(r"C:\projects\devlogs\trolley\data\itch\snap_city.png").convert("RGB").resize((W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(14))
    _bg_base = np.array(COL_BG, dtype=np.float32)
    _city_arr = np.array(_city, dtype=np.float32)
    base = Image.fromarray(np.clip(_bg_base + (_city_arr - _bg_base) * 0.20, 0, 255).astype(np.uint8))
    base_rgba = base.convert("RGBA")
    base_rgba.alpha_composite(vignette())
    base = base_rgba.convert("RGBA")
    bd = ImageDraw.Draw(base)
    title_with_underline(bd, "ХАЙП-ЦИКЛ ИИ", 70, size=100, sub="ГДЕ МЫ СЕЙЧАС")
    cy_top_approx = 260  # approximate title bottom
    bd.line([(cx_left, cy_base), (cx_right, cy_base)], fill=(*COL_GOLD, 255), width=4)

    pts = _hype_curve_pts(cx_left, cx_right, cy_base, cy_top_approx)

    FPS = 30
    anim_frames = int(FPS * 2.0)   # 2s draw
    hold_frames = int(FPS * 3.0)   # 3s hold

    frames = []
    for i in range(anim_frames):
        p = _ease_out_cubic(i / (anim_frames - 1))
        frame = build_hype_curve_frame(p, cx_left, cx_right, cy_base, cy_top_approx, pts, base)
        frames.append(frame)
    # Hold on fully-drawn frame
    frames.extend([frames[-1]] * hold_frames)

    out = OUT_DIR / "hype_curve_anim.mp4"
    clip = ImageSequenceClip(frames, fps=FPS)
    clip.write_videofile(str(out), codec="libx264", fps=FPS,
                         ffmpeg_params=["-crf", "18", "-pix_fmt", "yuv420p"],
                         logger=None)
    print(f"wrote {out}")
    return out


def build_workflow_diagram():
    """3-box workflow diagram: [ЗАДАЧА] → [CLAUDE CODE] → [РЕЗУЛЬТАТ]. For a2-1 Claude Code workflow beat."""
    canvas = Image.new("RGB", (W, H), COL_BG)
    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba.alpha_composite(vignette())
    canvas = canvas_rgba.convert("RGB")
    draw = ImageDraw.Draw(canvas)

    next_y = title_with_underline(draw, "КАК Я РАБОТАЮ", 70, size=100, sub="CLAUDE CODE · ЦИКЛ")

    # 3 boxes centered horizontally
    box_w = 420
    box_h = 280
    gap = 100
    total_w = box_w * 3 + gap * 2
    start_x = (W - total_w) // 2
    cy = (H - box_h) // 2 + 50

    boxes = [
        ("ЗАДАЧА", "я говорю", COL_GOLD),
        ("CLAUDE\nCODE", "пишет код", COL_GOLD),   # iter_61: was COL_RED — producer: "reads as error state"
        ("РЕЗУЛЬТАТ", "я проверяю", COL_GOLD),
    ]

    f_title = ImageFont.truetype(FONT_BLACK, 70)
    f_sub = ImageFont.truetype(FONT_BLACK, 36)
    f_arrow = ImageFont.truetype(FONT_BOLD, 100)

    for i, (title, sub, color) in enumerate(boxes):
        bx = start_x + i * (box_w + gap)
        # Shadow
        shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.rounded_rectangle((bx + 8, cy + 16, bx + box_w + 8, cy + box_h + 16),
                             radius=20, fill=(0, 0, 0, 200))
        shadow = shadow.filter(ImageFilter.GaussianBlur(20))
        canvas_rgba = canvas.convert("RGBA")
        canvas_rgba.paste(shadow, (0, 0), shadow)
        canvas = canvas_rgba.convert("RGB")
        draw = ImageDraw.Draw(canvas)
        # Box
        draw.rounded_rectangle((bx, cy, bx + box_w, cy + box_h),
                               radius=20, fill=(30, 24, 18), outline=color, width=6)
        # Title text
        lines = title.split("\n")
        line_h = 80
        ty = cy + (box_h - len(lines) * line_h) // 2 - 20
        for li, line in enumerate(lines):
            bb = draw.textbbox((0, 0), line, font=f_title, anchor="lt")
            tw = bb[2] - bb[0]
            draw.text((bx + (box_w - tw) // 2 + 3, ty + li * line_h + 3), line, fill=(0, 0, 0), font=f_title, anchor="lt")
            draw.text((bx + (box_w - tw) // 2, ty + li * line_h), line, fill=color, font=f_title, anchor="lt")
        # Subtitle
        bb = draw.textbbox((0, 0), sub, font=f_sub, anchor="lt")
        sw = bb[2] - bb[0]
        draw.text((bx + (box_w - sw) // 2, cy + box_h - 60), sub, fill=COL_GOLD_DIM, font=f_sub, anchor="lt")
        # Arrow to next box
        if i < 2:
            ax = bx + box_w + 20
            ay = cy + box_h // 2
            # Draw arrow as filled triangle pointing right
            draw.polygon([(ax, ay - 30), (ax + 60, ay), (ax, ay + 30)], fill=COL_GOLD)
            draw.line([(ax - 20, ay), (ax, ay)], fill=COL_GOLD, width=8)

    out = OUT_DIR / "workflow_diagram.png"
    canvas.save(out)
    print(f"wrote {out}")
    return out


def build_biggest_files():
    """Top-10 biggest source files by line count. For b4 "102 файла" chunk."""
    src = Path(GAME_DIR) / "src"
    files = []
    for f in src.rglob("*.js"):
        if not f.is_file():
            continue
        try:
            n = sum(1 for _ in f.read_text(encoding="utf-8", errors="ignore").splitlines())
        except Exception:
            n = 0
        rel = f.relative_to(src).as_posix()
        files.append((rel, n))
    files.sort(key=lambda x: -x[1])
    top = files[:10]

    canvas = Image.new("RGB", (W, H), COL_BG)
    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba.alpha_composite(vignette())
    canvas = canvas_rgba.convert("RGB")
    draw = ImageDraw.Draw(canvas)

    next_y = title_with_underline(draw, "ТОП-10 ФАЙЛОВ", 50, size=95, sub="ПО СТРОКАМ КОДА")

    list_top = next_y + 10
    row_h = 52
    f_path = ImageFont.truetype(FONT_MONO, 30)
    f_meta = ImageFont.truetype(FONT_BOLD, 28)
    max_lines = top[0][1]
    bar_left = 1050
    bar_max_w = W - bar_left - 230
    for i, (path, lcount) in enumerate(top):
        ry = list_top + i * row_h
        # Path (mono font for code-like feel)
        # Truncate path if too long
        display_path = path if len(path) <= 50 else "..." + path[-47:]
        draw.text((130, ry + 18), display_path, fill=COL_GOLD, font=f_path, anchor="lt")
        bar_h = 36
        draw.rectangle((bar_left, ry + 14, bar_left + bar_max_w, ry + 14 + bar_h),
                       fill=(40, 35, 28))
        bw = int(bar_max_w * (lcount / max_lines))
        draw.rectangle((bar_left, ry + 14, bar_left + bw, ry + 14 + bar_h),
                       fill=COL_GOLD)
        lstr = f"{lcount:,}".replace(",", " ")
        draw.text((bar_left + bw + 16, ry + 18), lstr, fill=COL_GOLD, font=f_meta, anchor="lt")

    out = OUT_DIR / "biggest_files.png"
    canvas.save(out)
    print(f"wrote {out}  top file: {top[0]}")
    return out


def build_art_grid_cover():
    """Branded 4×2 grid of game art — replaces raw Windows folder view for a2-4 'art iterations' beat."""
    ITCH_DIR = Path(r"C:\projects\devlogs\trolley\data\itch")
    art_files = [
        ITCH_DIR / "01_day1_first_trolley.png",
        ITCH_DIR / "02_day2_doodle_hud.png",
        ITCH_DIR / "04_forest_world.png",
        ITCH_DIR / "snap_city.png",
        ITCH_DIR / "07_choice_schrodinger.png",
        ITCH_DIR / "09_choice_truck_kun.png",
        ITCH_DIR / "boss_gameplay.png",
        ITCH_DIR / "tree_maxed.png",
    ]
    labels = ["ДЕНЬ 1", "ДЕНЬ 2 · HUD", "МИР · ЛЕС", "МИР · ГОРОД",
              "ВЫБОР · ШРЁДИНГЕР", "ВЫБОР · ИСЕКАЙ", "БОСС", "ДЕРЕВО · 59 НОД"]

    canvas = Image.new("RGB", (W, H), COL_BG)
    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba.alpha_composite(vignette())
    canvas = canvas_rgba.convert("RGB")
    draw = ImageDraw.Draw(canvas)

    next_y = title_with_underline(draw, "50 ИТЕРАЦИЙ ОБЛОЖКИ", 50, size=90,
                                  sub="ИИ ГЕНЕРИРУЕТ — Я ОТБИРАЮ")

    cols, rows = 4, 2
    margin_x = 60
    margin_bot = 40
    gap = 14
    grid_top = next_y + 24
    grid_bot = H - margin_bot
    cell_w = (W - margin_x * 2 - gap * (cols - 1)) // cols
    cell_h = (grid_bot - grid_top - gap * (rows - 1)) // rows

    label_font = ImageFont.truetype(FONT_BLACK, 26)

    for i, (art_path, label) in enumerate(zip(art_files, labels)):
        col = i % cols
        row = i // cols
        x = margin_x + col * (cell_w + gap)
        y = grid_top + row * (cell_h + gap)

        if art_path.exists():
            img = Image.open(art_path).convert("RGB")
            iw, ih = img.size
            target_ratio = cell_w / cell_h
            src_ratio = iw / ih
            if src_ratio > target_ratio:
                nh = cell_h
                nw = int(cell_h * src_ratio)
            else:
                nw = cell_w
                nh = int(cell_w / src_ratio)
            img = img.resize((nw, nh), Image.LANCZOS)
            left = (nw - cell_w) // 2
            top_c = (nh - cell_h) // 2
            img = img.crop((left, top_c, left + cell_w, top_c + cell_h))
            canvas.paste(img, (x, y))
        else:
            draw.rectangle((x, y, x + cell_w, y + cell_h), fill=(40, 35, 28))

        draw.rectangle((x - 2, y - 2, x + cell_w + 2, y + cell_h + 2), outline=COL_GOLD, width=3)

        # Label badge bottom-left (semi-transparent via RGBA composite)
        lb = draw.textbbox((0, 0), label, font=label_font, anchor="lt")
        lw = lb[2] - lb[0]
        lh = lb[3] - lb[1]
        pad = 8
        badge_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        bd = ImageDraw.Draw(badge_layer)
        bx1, by1 = x + 10, y + cell_h - lh - pad * 2 - 8
        bd.rectangle((bx1, by1, bx1 + lw + pad * 2, by1 + lh + pad * 2), fill=(0, 0, 0, 200))
        canvas_rgba = canvas.convert("RGBA")
        canvas_rgba.alpha_composite(badge_layer)
        canvas = canvas_rgba.convert("RGB")
        draw = ImageDraw.Draw(canvas)
        draw.text((bx1 + pad, by1 + pad), label, fill=COL_GOLD, font=label_font, anchor="lt")

    out = OUT_DIR / "art_grid_cover.png"
    canvas.save(out)
    print(f"wrote {out}")
    return out


def build_timeline_13days():
    """Horizontal 13-day jam timeline with key milestone labels. Sci-pop style."""
    canvas = Image.new("RGB", (W, H), COL_BG)
    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba.alpha_composite(vignette())
    canvas = canvas_rgba.convert("RGB")
    draw = ImageDraw.Draw(canvas)

    next_y = title_with_underline(draw, "13 ДНЕЙ РАЗРАБОТКИ", 60, size=100,
                                  sub="GAMEDEV.JS JAM 2026 · 273 КОММИТА")

    # Timeline bar
    tl_left = 120
    tl_right = W - 120
    tl_y = H // 2 + 40
    tl_w = tl_right - tl_left

    # Gold baseline
    draw.line([(tl_left, tl_y), (tl_right, tl_y)], fill=COL_GOLD, width=6)

    # Arrow head at right
    arr_x = tl_right + 10
    draw.polygon([(arr_x, tl_y - 12), (arr_x + 30, tl_y), (arr_x, tl_y + 12)], fill=COL_GOLD)

    node_r = 18
    f_day = ImageFont.truetype(FONT_BOLD, 30)
    f_label = ImageFont.truetype(FONT_BLACK, 32)
    f_milestone = ImageFont.truetype(FONT_BLACK, 34)

    # Only Day 1 is labeled — days 2-13 are empty rings (unknown future)
    milestones = {
        1: ("ПЕРВЫЙ\nТРАМВАЙ", "above"),
    }

    # Pass 1: connector lines (drawn first, so nodes + numbers appear on top)
    for day, (label, side) in milestones.items():
        t = (day - 1) / 12
        nx = int(tl_left + t * tl_w)
        lines = label.split("\n")
        line_h = 40
        total_h = line_h * len(lines)
        if side == "above":
            label_bot = tl_y - node_r - 14
            draw.line([(nx, tl_y - node_r - 2), (nx, label_bot)], fill=COL_RED, width=3)
        else:
            label_top = tl_y + node_r + 46
            draw.line([(nx, tl_y + node_r + 2), (nx, label_top - 10)], fill=COL_RED, width=3)

    # Pass 2: nodes + day numbers + labels (on top of lines)
    for day in range(1, 14):
        t = (day - 1) / 12
        nx = int(tl_left + t * tl_w)

        col = COL_RED if day in milestones else COL_GOLD
        draw.ellipse((nx - node_r, tl_y - node_r, nx + node_r, tl_y + node_r), fill=col)
        if day not in milestones:
            draw.ellipse((nx - node_r + 4, tl_y - node_r + 4, nx + node_r - 4, tl_y + node_r - 4),
                         fill=COL_BG)

        day_str = str(day)
        db = draw.textbbox((0, 0), day_str, font=f_day, anchor="lt")
        dw = db[2] - db[0]
        draw.text((nx - dw // 2, tl_y + node_r + 10), day_str, fill=COL_GOLD_DIM, font=f_day, anchor="lt")

        if day in milestones:
            label, side = milestones[day]
            lines = label.split("\n")
            line_h = 40
            total_h = line_h * len(lines)
            if side == "above":
                label_bot = tl_y - node_r - 14
                label_top = label_bot - total_h - 10
                for li, line in enumerate(lines):
                    lb = draw.textbbox((0, 0), line, font=f_milestone, anchor="lt")
                    lw = lb[2] - lb[0]
                    ty = label_top + li * line_h
                    draw.text((nx - lw // 2 + 2, ty + 2), line, fill=(0, 0, 0), font=f_milestone, anchor="lt")
                    draw.text((nx - lw // 2, ty), line, fill=COL_GOLD, font=f_milestone, anchor="lt")
            else:
                label_top = tl_y + node_r + 46
                for li, line in enumerate(lines):
                    lb = draw.textbbox((0, 0), line, font=f_milestone, anchor="lt")
                    lw = lb[2] - lb[0]
                    ty = label_top + li * line_h
                    draw.text((nx - lw // 2 + 2, ty + 2), line, fill=(0, 0, 0), font=f_milestone, anchor="lt")
                    draw.text((nx - lw // 2, ty), line, fill=COL_GOLD, font=f_milestone, anchor="lt")

    out = OUT_DIR / "timeline_13days.png"
    canvas.save(out)
    print(f"wrote {out}")
    return out


def _ease_out_cubic(t):
    return 1 - (1 - t) ** 3


def _ease_out_quart(t):
    return 1 - (1 - t) ** 4


def build_commits_chart_frame(days, max_count, bar_area_top, bar_area_h, bar_area_bottom,
                               left_pad, bar_w, bar_gap, progress, city_bg_arr=None):
    """Render one frame of the animated commit chart at given progress (0..1)."""
    if city_bg_arr is not None:
        bg_base = np.array(COL_BG, dtype=np.float32)
        canvas = Image.fromarray(np.clip(bg_base + (city_bg_arr - bg_base) * 0.20, 0, 255).astype(np.uint8))
    else:
        canvas = Image.new("RGB", (W, H), COL_BG)
    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba.alpha_composite(vignette())
    canvas = canvas_rgba.convert("RGB")
    draw = ImageDraw.Draw(canvas)
    # Title rendered by compose_beat overlay — no duplicate here
    draw.line([(left_pad, bar_area_bottom), (W - left_pad, bar_area_bottom)], fill=COL_GOLD, width=4)
    fnum = ImageFont.truetype(FONT_BOLD, 36)
    fday = ImageFont.truetype(FONT_BOLD, 30)
    n = len(days)
    # Staggered bar entrance: bar k starts at t_k = k/(n*1.5), finishes at t_k + 0.5
    for i, (date_str, count, day_n) in enumerate(days):
        t_start = i / (n * 1.4)
        t_end = t_start + 0.6
        local_p = max(0.0, min(1.0, (progress - t_start) / max(t_end - t_start, 0.001)))
        local_p_eased = _ease_out_quart(local_p)
        bar_h = int(bar_area_h * (count / max_count) * local_p_eased) if count > 0 else 0
        bx = left_pad + i * (bar_w + bar_gap)
        by_top = bar_area_bottom - bar_h
        if bar_h > 4:
            draw.rectangle((bx, by_top, bx + bar_w, bar_area_bottom), fill=COL_GOLD)
            # Count label (count proportional to height)
            display_count = int(count * local_p_eased)
            if display_count > 0:
                cnt_str = str(display_count)
                cb = draw.textbbox((0, 0), cnt_str, font=fnum, anchor="lt")
                cw = cb[2] - cb[0]
                alpha = min(255, int(255 * local_p * 2))
                draw.text((bx + (bar_w - cw) // 2, by_top - 50), cnt_str,
                          fill=tuple(int(c * alpha / 255) for c in COL_GOLD), font=fnum, anchor="lt")
        day_str = f"Д{day_n}"
        db = draw.textbbox((0, 0), day_str, font=fday, anchor="lt")
        dw = db[2] - db[0]
        draw.text((bx + (bar_w - dw) // 2, bar_area_bottom + 20),
                  day_str, fill=COL_GOLD, font=fday, anchor="lt")
    f_note = ImageFont.truetype(FONT_BLACK, 36)
    note = "26 АПРЕЛЯ · СДАЧА В JAM"
    nb = draw.textbbox((0, 0), note, font=f_note, anchor="lt")
    nw = nb[2] - nb[0]
    draw.text(((W - nw) // 2, bar_area_bottom + 80), note, fill=COL_GOLD_DIM, font=f_note, anchor="lt")
    return np.array(canvas)


def build_commits_chart_anim():
    """Animated commit bar chart — bars grow in staggered from left to right. Output: MP4."""
    try:
        from moviepy import ImageSequenceClip
    except ImportError:
        print("moviepy not available for animation")
        return None
    days = get_commits_by_day()
    max_count = max(c for _, c, _ in days)
    bar_area_top = 160
    bar_area_h = 490
    bar_area_bottom = bar_area_top + bar_area_h
    left_pad = 130
    chart_w = W - left_pad * 2
    bar_count = len(days)
    bar_gap = 12
    bar_w = (chart_w - bar_gap * (bar_count - 1)) // bar_count

    FPS = 30
    anim_frames = int(FPS * 1.8)   # 1.8s animation
    hold_frames = int(FPS * 2.5)   # 2.5s hold at end

    _city = Image.open(r"C:\projects\devlogs\trolley\data\itch\snap_city.png").convert("RGB").resize((W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(14))
    _city_arr = np.array(_city, dtype=np.float32)
    frames = []
    for i in range(anim_frames):
        p = i / (anim_frames - 1)
        frame = build_commits_chart_frame(days, max_count, bar_area_top, bar_area_h,
                                          bar_area_bottom, left_pad, bar_w, bar_gap, p,
                                          city_bg_arr=_city_arr)
        frames.append(frame)
    frames.extend([frames[-1]] * hold_frames)

    out = OUT_DIR / "commits_chart_anim.mp4"
    clip = ImageSequenceClip(frames, fps=FPS)
    clip.write_videofile(str(out), codec="libx264", fps=FPS,
                         ffmpeg_params=["-crf", "18", "-pix_fmt", "yuv420p"],
                         logger=None)
    print(f"wrote {out}")
    return out


def build_daily_views_frame(days_data, max_val, bar_area_top, bar_area_h, bar_area_bottom,
                             left_pad, bar_w, bar_gap, spike_dates, bar_progresses, city_bg_arr=None):
    """Single frame. bar_progresses[i] = 0..1 growth of each bar (left-to-right cascade)."""
    if city_bg_arr is not None:
        bg_base = np.array(COL_BG, dtype=np.float32)
        canvas = Image.fromarray(np.clip(bg_base + (city_bg_arr - bg_base) * 0.20, 0, 255).astype(np.uint8))
    else:
        canvas = Image.new("RGB", (W, H), COL_BG)
    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba.alpha_composite(vignette())
    canvas = canvas_rgba.convert("RGB")
    draw = ImageDraw.Draw(canvas)
    # Counter = sum of views from bars already / partially grown
    current_views = int(sum(v * min(bp, 1.0) for (_, v), bp in zip(days_data, bar_progresses)))
    thousands, remainder = divmod(current_views, 1000)
    counter_str = f"{thousands} {remainder:03d}" if thousands else str(remainder)
    f_counter = ImageFont.truetype(FONT_BOLD, 130)
    f_sub2 = ImageFont.truetype(FONT_BOLD, 32)
    draw.text((W // 2, 55), counter_str, fill=COL_GOLD, font=f_counter, anchor="mt")
    bbox = draw.textbbox((W // 2, 55), counter_str, font=f_counter, anchor="mt")
    uw = min(bbox[2] - bbox[0], 600)
    uy = bbox[3] + 14
    draw.rectangle([(W // 2 - uw // 2, uy), (W // 2 + uw // 2, uy + 7)], fill=COL_RED)
    draw.text((W // 2, uy + 22), "ПРОСМОТРОВ · ITCH.IO · ЗА 30 ДНЕЙ", fill=COL_GOLD_DIM, font=f_sub2, anchor="mt")
    draw.line([(left_pad, bar_area_bottom), (W - left_pad, bar_area_bottom)], fill=COL_GOLD, width=4)
    fnum = ImageFont.truetype(FONT_BOLD, 26)
    flbl = ImageFont.truetype(FONT_BOLD, 22)
    for i, (day_idx, val) in enumerate(days_data):
        bp = _ease_out_quart(min(bar_progresses[i], 1.0))
        bar_h = int(bar_area_h * (val / max_val) * bp) if val > 0 else 0
        bx = left_pad + i * (bar_w + bar_gap)
        by_top = bar_area_bottom - bar_h
        color = COL_RED if day_idx in spike_dates else COL_GOLD
        if bar_h > 2:
            draw.rectangle((bx, by_top, bx + bar_w, bar_area_bottom), fill=color)
        if day_idx in spike_dates and bar_h > 30:
            lbl = "26 АПР · JAM" if day_idx == 14 else "7 МАЯ · ТОП-2"
            draw.text((bx - 30, by_top - 36), lbl, fill=COL_RED, font=flbl, anchor="lt")
            draw.text((bx + bar_w // 2, by_top - 70), str(val), fill=COL_GOLD, font=fnum, anchor="mt")
    f_axis = ImageFont.truetype(FONT_BOLD, 28)
    for week_n, label in [(0, "12 АПР"), (7, "19 АПР"), (14, "26 АПР"), (21, "3 МАЯ"), (28, "10 МАЯ")]:
        bx = left_pad + week_n * (bar_w + bar_gap)
        draw.text((bx, bar_area_bottom + 18), label, fill=COL_GOLD, font=f_axis, anchor="lt")
    return np.array(canvas)

def build_daily_views_anim():
    """Animated daily views chart — bars grow left-to-right, one per day. Output: MP4."""
    try:
        from moviepy import ImageSequenceClip
    except ImportError:
        return None
    days_data = [
        (0,20),(1,30),(2,25),(3,40),(4,30),(5,20),(6,25),(7,40),(8,50),(9,60),
        (10,80),(11,100),(12,150),(13,250),(14,2500),(15,2200),(16,1700),(17,900),
        (18,600),(19,450),(20,400),(21,380),(22,350),(23,2000),(24,6500),
        (25,4500),(26,2500),(27,1500),(28,1000),(29,900),(30,700),
    ]
    max_val = max(v for _, v in days_data)
    spike_dates = {14, 24}
    bar_area_top = 340
    bar_area_h = 380
    bar_area_bottom = bar_area_top + bar_area_h
    left_pad = 100
    chart_w = W - left_pad * 2
    bar_count = len(days_data)
    bar_gap = 6
    bar_w = (chart_w - bar_gap * (bar_count - 1)) // bar_count

    FPS = 30
    N = len(days_data)
    total_anim_dur = 3.5   # seconds — bars cascade left→right
    grow_dur = 0.25        # each bar grows for this many seconds
    hold_dur = 6.0         # hold on full chart (covers ~8.78s total chart window)

    # Bar i starts growing at evenly spaced intervals so last bar finishes at total_anim_dur
    start_times = [i * (total_anim_dur - grow_dur) / (N - 1) for i in range(N)]

    total_frames = int(FPS * (total_anim_dur + hold_dur))
    _city = Image.open(r"C:\projects\devlogs\trolley\data\itch\snap_city.png").convert("RGB").resize((W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(14))
    _city_arr = np.array(_city, dtype=np.float32)
    frames = []
    for f in range(total_frames):
        t = f / FPS
        bar_progresses = []
        for i in range(N):
            elapsed = t - start_times[i]
            if elapsed <= 0:
                bar_progresses.append(0.0)
            elif elapsed >= grow_dur:
                bar_progresses.append(1.0)
            else:
                bar_progresses.append(elapsed / grow_dur)
        frame = build_daily_views_frame(days_data, max_val, bar_area_top, bar_area_h,
                                        bar_area_bottom, left_pad, bar_w, bar_gap,
                                        spike_dates, bar_progresses, city_bg_arr=_city_arr)
        frames.append(frame)

    out = OUT_DIR / "daily_views_anim.mp4"
    clip = ImageSequenceClip(frames, fps=FPS)
    clip.write_videofile(str(out), codec="libx264", fps=FPS,
                         ffmpeg_params=["-crf", "18", "-pix_fmt", "yuv420p"],
                         logger=None)
    print(f"wrote {out}")
    return out

def build_workflow_anim():
    """Animated workflow diagram — boxes appear sequentially with arrows. Output: MP4."""
    try:
        from moviepy import ImageSequenceClip
    except ImportError:
        return None

    FPS = 30
    phase_dur = 0.55   # seconds per box reveal phase
    hold_dur = 2.5
    total_anim = phase_dur * 3
    n_anim = int(FPS * total_anim)
    n_hold = int(FPS * hold_dur)

    # Layout: no burnt-in title — caller (compose_beat) supplies the overlay
    # label. Boxes are centered vertically; layout has room for an optional
    # bottom band without overlap.
    box_w, box_h, gap = 420, 280, 100
    total_w = box_w * 3 + gap * 2
    start_x = (W - total_w) // 2
    cy = (H - box_h) // 2          # true center now that no title eats the top
    boxes = [("ЗАДАЧА", "я говорю", COL_GOLD),
             ("CLAUDE\nCODE", "пишет код", COL_GOLD),
             ("РЕЗУЛЬТАТ", "я проверяю", COL_GOLD)]
    f_title = ImageFont.truetype(FONT_BLACK, 70)
    f_sub = ImageFont.truetype(FONT_BLACK, 36)
    # City bg loaded once, blended per-frame at low opacity for mood
    _city_wf = Image.open(r"C:\projects\devlogs\trolley\data\itch\snap_city.png").convert("RGB").resize((W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(14))
    _city_wf_arr = np.array(_city_wf, dtype=np.float32)
    _bg_base_wf = np.array(COL_BG, dtype=np.float32)

    def render_frame(phase_progress):
        canvas = Image.fromarray(np.clip(_bg_base_wf + (_city_wf_arr - _bg_base_wf) * 0.20, 0, 255).astype(np.uint8))
        canvas_rgba = canvas.convert("RGBA")
        canvas_rgba.alpha_composite(vignette())
        canvas = canvas_rgba.convert("RGB")
        draw = ImageDraw.Draw(canvas)
        # NOTE: removed burnt-in "КАК Я РАБОТАЮ" title. The overlay band from
        # the parent beat (e.g. "6 МЕСЯЦЕВ" or "1.  РАМКИ") supplies context
        # without competing for header real estate.

        for i, (title, sub, color) in enumerate(boxes):
            # Box i visible when phase_progress > i
            box_p = max(0.0, min(1.0, phase_progress - i))
            box_p_e = _ease_out_cubic(box_p)
            if box_p_e < 0.01:
                continue
            bx = start_x + i * (box_w + gap)
            alpha = int(255 * box_p_e)
            # Box fill
            shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            sd = ImageDraw.Draw(shadow)
            sd.rounded_rectangle((bx + 8, cy + 16, bx + box_w + 8, cy + box_h + 16),
                                 radius=20, fill=(0, 0, 0, int(200 * box_p_e)))
            shadow = shadow.filter(ImageFilter.GaussianBlur(20))
            canvas_rgba = canvas.convert("RGBA")
            canvas_rgba.paste(shadow, (0, 0), shadow)
            canvas = canvas_rgba.convert("RGB")
            draw = ImageDraw.Draw(canvas)
            draw.rounded_rectangle((bx, cy, bx + box_w, cy + box_h),
                                   radius=20, fill=(30, 24, 18),
                                   outline=tuple(int(c * box_p_e) for c in color), width=6)
            # Title text
            lines = title.split("\n")
            line_h = 80
            ty = cy + (box_h - len(lines) * line_h) // 2 - 20
            for li, line in enumerate(lines):
                bb = draw.textbbox((0, 0), line, font=f_title, anchor="lt")
                tw = bb[2] - bb[0]
                tc = tuple(int(c * box_p_e) for c in color)
                draw.text((bx + (box_w - tw) // 2 + 3, ty + li * line_h + 3), line,
                          fill=(0, 0, 0), font=f_title, anchor="lt")
                draw.text((bx + (box_w - tw) // 2, ty + li * line_h), line,
                          fill=tc, font=f_title, anchor="lt")
            bb = draw.textbbox((0, 0), sub, font=f_sub, anchor="lt")
            sw = bb[2] - bb[0]
            sc = tuple(int(c * box_p_e) for c in COL_GOLD_DIM)
            draw.text((bx + (box_w - sw) // 2, cy + box_h - 60), sub, fill=sc, font=f_sub, anchor="lt")
            # Arrow to next box (appears with next box)
            if i < 2:
                arr_p = max(0.0, min(1.0, phase_progress - (i + 0.7)))
                arr_p_e = _ease_out_cubic(arr_p)
                if arr_p_e > 0.01:
                    ax = bx + box_w + 20
                    ay = cy + box_h // 2
                    ac = tuple(int(c * arr_p_e) for c in COL_GOLD)
                    draw.line([(ax - 20, ay), (ax, ay)], fill=ac, width=8)
                    draw.polygon([(ax, ay - 30), (ax + 60, ay), (ax, ay + 30)], fill=ac)
        return np.array(canvas)

    frames = []
    for i in range(n_anim):
        phase_p = (i / (n_anim - 1)) * 3  # 0..3 over animation
        frames.append(render_frame(phase_p))
    frames.extend([frames[-1]] * n_hold)

    out = OUT_DIR / "workflow_diagram_anim.mp4"
    clip = ImageSequenceClip(frames, fps=FPS)
    clip.write_videofile(str(out), codec="libx264", fps=FPS,
                         ffmpeg_params=["-crf", "18", "-pix_fmt", "yuv420p"],
                         logger=None)
    print(f"wrote {out}")
    return out


def build_timeline_anim():
    """Animated 13-day timeline — nodes appear left to right. Output: MP4."""
    try:
        from moviepy import ImageSequenceClip
    except ImportError:
        return None

    FPS = 30
    node_interval = 0.12  # seconds between each node appearing
    total_anim = 13 * node_interval + 0.3
    hold_dur = 2.5
    n_anim = int(FPS * total_anim)
    n_hold = int(FPS * hold_dur)

    tl_left, tl_right = 120, W - 120
    tl_y = H // 2 + 40
    tl_w = tl_right - tl_left
    node_r = 18
    f_day = ImageFont.truetype(FONT_BOLD, 30)
    f_milestone = ImageFont.truetype(FONT_BLACK, 34)
    # Only Day 1 labeled — days 2-13 are empty rings (unknown future)
    milestones = {
        1: ("ПЕРВЫЙ\nТРАМВАЙ", "above"),
    }

    def render_frame(progress):
        canvas = Image.new("RGB", (W, H), COL_BG)
        canvas_rgba = canvas.convert("RGBA")
        canvas_rgba.alpha_composite(vignette())
        canvas = canvas_rgba.convert("RGB")
        draw = ImageDraw.Draw(canvas)
        title_with_underline(draw, "13 ДНЕЙ РАЗРАБОТКИ", 60, size=100,
                              sub="GAMEDEV.JS JAM 2026 · 273 КОММИТА")
        nodes_visible = min(13, int(progress * 13 + 1))
        if nodes_visible >= 1:
            last_t = (min(nodes_visible - 1, 12)) / 12
            last_x = int(tl_left + last_t * tl_w)
            draw.line([(tl_left, tl_y), (last_x, tl_y)], fill=COL_GOLD, width=6)
        if nodes_visible >= 13:
            draw.polygon([(tl_right + 10, tl_y - 12), (tl_right + 40, tl_y), (tl_right + 10, tl_y + 12)],
                         fill=COL_GOLD)

        # Pass 1: connector lines behind nodes
        for day in range(1, nodes_visible + 1):
            if day in milestones:
                t = (day - 1) / 12
                nx = int(tl_left + t * tl_w)
                label, side = milestones[day]
                lines = label.split("\n")
                total_lh = 40 * len(lines)
                if side == "above":
                    label_bot = tl_y - node_r - 14
                    draw.line([(nx, tl_y - node_r - 2), (nx, label_bot)], fill=COL_RED, width=3)
                else:
                    label_top = tl_y + node_r + 46
                    draw.line([(nx, tl_y + node_r + 2), (nx, label_top - 10)], fill=COL_RED, width=3)

        # Pass 2: nodes + numbers + labels on top
        for day in range(1, nodes_visible + 1):
            t = (day - 1) / 12
            nx = int(tl_left + t * tl_w)
            col = COL_RED if day in milestones else COL_GOLD
            draw.ellipse((nx - node_r, tl_y - node_r, nx + node_r, tl_y + node_r), fill=col)
            if day not in milestones:
                draw.ellipse((nx - node_r + 4, tl_y - node_r + 4, nx + node_r - 4, tl_y + node_r - 4),
                             fill=COL_BG)
            day_str = str(day)
            db = draw.textbbox((0, 0), day_str, font=f_day, anchor="lt")
            dw = db[2] - db[0]
            draw.text((nx - dw // 2, tl_y + node_r + 10), day_str, fill=COL_GOLD_DIM, font=f_day, anchor="lt")
            if day in milestones:
                label, side = milestones[day]
                lines = label.split("\n")
                line_h = 40
                total_lh = line_h * len(lines)
                if side == "above":
                    label_bot = tl_y - node_r - 14
                    label_top = label_bot - total_lh - 10
                    for li, line in enumerate(lines):
                        lb = draw.textbbox((0, 0), line, font=f_milestone, anchor="lt")
                        lw = lb[2] - lb[0]
                        ty = label_top + li * line_h
                        draw.text((nx - lw // 2 + 2, ty + 2), line, fill=(0, 0, 0), font=f_milestone, anchor="lt")
                        draw.text((nx - lw // 2, ty), line, fill=COL_GOLD, font=f_milestone, anchor="lt")
                else:
                    label_top = tl_y + node_r + 46
                    for li, line in enumerate(lines):
                        lb = draw.textbbox((0, 0), line, font=f_milestone, anchor="lt")
                        lw = lb[2] - lb[0]
                        ty = label_top + li * line_h
                        draw.text((nx - lw // 2 + 2, ty + 2), line, fill=(0, 0, 0), font=f_milestone, anchor="lt")
                        draw.text((nx - lw // 2, ty), line, fill=COL_GOLD, font=f_milestone, anchor="lt")
        return np.array(canvas)

    frames = []
    for i in range(n_anim):
        p = i / max(n_anim - 1, 1)
        frames.append(render_frame(p))
    frames.extend([frames[-1]] * n_hold)

    out = OUT_DIR / "timeline_13days_anim.mp4"
    clip = ImageSequenceClip(frames, fps=FPS)
    clip.write_videofile(str(out), codec="libx264", fps=FPS,
                         ffmpeg_params=["-crf", "18", "-pix_fmt", "yuv420p"],
                         logger=None)
    print(f"wrote {out}")
    return out


def build_day1_progression():
    """5-card progression grid from Day 1 git commits."""
    SNAPS = [
        ("data/itch/day1_snap_1207.png", "12:07", "РЕЛЬСЫ"),
        ("data/itch/day1_snap_1222.png", "12:22", "ПЕРВЫЙ ТРАМВАЙ"),
        ("data/itch/day1_snap_1258.png", "12:58", "ЛЮДИ НА ПУТИ"),
        ("data/itch/day1_snap_1417.png", "14:17", "АПГРЕЙДЫ"),
        ("data/itch/day1_snap_1847.png", "18:47", "РАНГИ"),
    ]
    DEVLOG = Path(r"C:\projects\devlogs\trolley")

    canvas = Image.new("RGB", (W, H), COL_BG)
    canvas = canvas.convert("RGBA")
    canvas.alpha_composite(vignette())
    canvas = canvas.convert("RGB")
    draw = ImageDraw.Draw(canvas)

    f_header = ImageFont.truetype(FONT_BLACK, 58)
    f_time   = ImageFont.truetype(FONT_BOLD,  52)
    f_desc   = ImageFont.truetype(FONT_BLACK, 32)

    hdr = "ДЕНЬ 1"
    hb = draw.textbbox((0, 0), hdr, font=f_header)
    hx = (W - (hb[2] - hb[0])) // 2
    draw.text((hx + 3, 33), hdr, fill=(0, 0, 0), font=f_header)
    draw.text((hx, 30), hdr, fill=COL_GOLD, font=f_header)
    ul_y = 30 + (hb[3] - hb[1]) + 14
    draw.rectangle(((W - 280) // 2, ul_y, (W + 280) // 2, ul_y + 5), fill=COL_RED)

    CARD_W  = 560
    GAME_H  = 315    # 16:9 of 560
    LABEL_H = 80
    CARD_H  = GAME_H + LABEL_H
    BORDER  = 2
    ROW_GAP = 44

    # Row 1: cards 0-2
    r1_y = ul_y + 36
    r1_gap = (W - 3 * CARD_W) // 4
    r1_xs = [r1_gap, r1_gap * 2 + CARD_W, r1_gap * 3 + CARD_W * 2]

    # Row 2: cards 3-4 centered
    r2_y = r1_y + CARD_H + ROW_GAP
    r2_gap = (W - 2 * CARD_W) // 3
    r2_xs = [r2_gap, r2_gap * 2 + CARD_W]

    card_positions = [(r1_xs[0], r1_y), (r1_xs[1], r1_y), (r1_xs[2], r1_y),
                      (r2_xs[0], r2_y), (r2_xs[1], r2_y)]

    for idx, (snap_rel, time_str, desc_str) in enumerate(SNAPS):
        cx, cy = card_positions[idx]
        snap_path = DEVLOG / snap_rel

        # Load and resize screenshot
        snap = Image.open(snap_path).convert("RGB")
        snap_thumb = snap.resize((CARD_W, GAME_H), Image.LANCZOS)

        # Gold border rect
        draw.rectangle(
            (cx - BORDER, cy - BORDER, cx + CARD_W + BORDER, cy + GAME_H + BORDER),
            outline=COL_GOLD, width=BORDER
        )
        canvas.paste(snap_thumb, (cx, cy))

        # Label strip
        label_rect = (cx, cy + GAME_H, cx + CARD_W, cy + CARD_H)
        label_bg = Image.new("RGB", (CARD_W, LABEL_H), (18, 15, 12))
        canvas.paste(label_bg, (cx, cy + GAME_H))

        draw_card = ImageDraw.Draw(canvas)

        # Time (left-aligned inside label)
        tb = draw_card.textbbox((0, 0), time_str, font=f_time)
        tw = tb[2] - tb[0]
        # Center time in label horizontally
        tx = cx + (CARD_W - tw) // 2
        ty = cy + GAME_H + (LABEL_H - (tb[3] - tb[1])) // 2 - 14
        draw_card.text((tx + 2, ty + 2), time_str, fill=(0, 0, 0), font=f_time)
        draw_card.text((tx, ty), time_str, fill=COL_GOLD, font=f_time)

        # Desc (below time)
        db = draw_card.textbbox((0, 0), desc_str, font=f_desc)
        dw = db[2] - db[0]
        dx = cx + (CARD_W - dw) // 2
        dy = ty + (tb[3] - tb[1]) + 6
        draw_card.text((dx, dy), desc_str, fill=COL_GOLD_DIM, font=f_desc)

    out = DEVLOG / "data/infographics/day1_progression.png"
    canvas.save(str(out))
    print(f"wrote {out}")
    return out


def build_day1_progression_anim():
    """Animated card grid: cards fade in one by one, left→right, row1 then row2."""
    from moviepy import ImageSequenceClip
    FPS = 30
    FADE  = 10   # frames to fade in one card
    GAP   = 18   # frames between card starts
    HOLD  = 35   # hold frames after last card fully visible
    TOTAL = GAP * 4 + FADE + HOLD  # 5 cards: starts at 0,18,36,54,72 + fade10 + hold35 = 117

    SNAPS = [
        ("data/itch/day1_snap_1207.png", "12:07", "РЕЛЬСЫ"),
        ("data/itch/day1_snap_1222.png", "12:22", "ПЕРВЫЙ ТРАМВАЙ"),
        ("data/itch/day1_snap_1258.png", "12:58", "ЛЮДИ НА ПУТИ"),
        ("data/itch/day1_snap_1417.png", "14:17", "АПГРЕЙДЫ"),
        ("data/itch/day1_snap_1847.png", "18:47", "РАНГИ"),
    ]
    DEVLOG = Path(r"C:\projects\devlogs\trolley")

    CARD_W  = 560
    GAME_H  = 315
    LABEL_H = 80
    CARD_H  = GAME_H + LABEL_H
    BORDER  = 2
    ROW_GAP = 44

    f_header = ImageFont.truetype(FONT_BLACK, 58)
    f_time   = ImageFont.truetype(FONT_BOLD,  52)
    f_desc   = ImageFont.truetype(FONT_BLACK, 32)

    ul_y_val = 30 + 58 + 14   # approx header bottom
    r1_y = ul_y_val + 36
    r1_gap = (W - 3 * CARD_W) // 4
    r1_xs  = [r1_gap, r1_gap * 2 + CARD_W, r1_gap * 3 + CARD_W * 2]
    r2_y   = r1_y + CARD_H + ROW_GAP
    r2_gap = (W - 2 * CARD_W) // 3
    r2_xs  = [r2_gap, r2_gap * 2 + CARD_W]
    card_positions = [(r1_xs[0], r1_y), (r1_xs[1], r1_y), (r1_xs[2], r1_y),
                      (r2_xs[0], r2_y), (r2_xs[1], r2_y)]

    # Pre-render background (vignette + header)
    bg = Image.new("RGB", (W, H), COL_BG).convert("RGBA")
    bg.alpha_composite(vignette())
    bg = bg.convert("RGB")
    bg_draw = ImageDraw.Draw(bg)
    hdr = "ДЕНЬ 1"
    hb = bg_draw.textbbox((0, 0), hdr, font=f_header)
    hx = (W - (hb[2] - hb[0])) // 2
    ul_y = 30 + (hb[3] - hb[1]) + 14
    bg_draw.text((hx + 3, 33), hdr, fill=(0, 0, 0), font=f_header)
    bg_draw.text((hx, 30), hdr, fill=COL_GOLD, font=f_header)
    bg_draw.rectangle(((W - 280) // 2, ul_y, (W + 280) // 2, ul_y + 5), fill=COL_RED)

    # Pre-render each card as RGBA
    card_images = []
    for snap_rel, time_str, desc_str in SNAPS:
        card = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        cx, cy = card_positions[len(card_images)]
        snap = Image.open(DEVLOG / snap_rel).convert("RGB")
        snap_thumb = snap.resize((CARD_W, GAME_H), Image.LANCZOS)
        card.paste(snap_thumb, (cx, cy))
        # label bg
        label_bg = Image.new("RGBA", (CARD_W, LABEL_H), (18, 15, 12, 255))
        card.paste(label_bg, (cx, cy + GAME_H))
        # gold border
        cd = ImageDraw.Draw(card)
        cd.rectangle((cx - BORDER, cy - BORDER, cx + CARD_W + BORDER, cy + GAME_H + BORDER),
                      outline=(*COL_GOLD, 255), width=BORDER)
        # time
        tb = cd.textbbox((0, 0), time_str, font=f_time)
        tw = tb[2] - tb[0]
        tx = cx + (CARD_W - tw) // 2
        ty = cy + GAME_H + (LABEL_H - (tb[3] - tb[1])) // 2 - 14
        cd.text((tx + 2, ty + 2), time_str, fill=(0, 0, 0, 255), font=f_time)
        cd.text((tx, ty), time_str, fill=(*COL_GOLD, 255), font=f_time)
        # desc
        db = cd.textbbox((0, 0), desc_str, font=f_desc)
        dw = db[2] - db[0]
        cd.text((cx + (CARD_W - dw) // 2, ty + (tb[3] - tb[1]) + 6),
                desc_str, fill=(*COL_GOLD_DIM, 255), font=f_desc)
        card_images.append(card)

    card_starts = [i * GAP for i in range(5)]

    def render_frame(f):
        canvas = bg.copy().convert("RGBA")
        for idx, card_img in enumerate(card_images):
            elapsed = f - card_starts[idx]
            if elapsed <= 0:
                continue
            alpha = min(1.0, elapsed / FADE)
            if alpha <= 0:
                continue
            faded = card_img.copy()
            r, g, b, a = faded.split()
            a = a.point(lambda x: int(x * alpha))
            faded = Image.merge("RGBA", (r, g, b, a))
            canvas.alpha_composite(faded)
        return np.array(canvas.convert("RGB"))

    frames = [render_frame(f) for f in range(TOTAL)]

    out = OUT_DIR / "day1_progression_anim.mp4"
    clip = ImageSequenceClip(frames, fps=FPS)
    clip.write_videofile(str(out), codec="libx264", fps=FPS,
                         ffmpeg_params=["-crf", "18", "-pix_fmt", "yuv420p"],
                         logger=None)
    print(f"wrote {out}")
    return out


# Alias for the frame rendering function (avoids long inline call)
def builds_commits_chart_frame_call(days, max_count, bar_area_top, bar_area_h,
                                     bar_area_bottom, left_pad, bar_w, bar_gap, progress):
    return build_commits_chart_frame(days, max_count, bar_area_top, bar_area_h,
                                     bar_area_bottom, left_pad, bar_w, bar_gap, progress)


def build_worlds_collage():
    """5-world card grid for b3 '5 МИРОВ' segment."""
    DEVLOG = Path(r"C:\projects\devlogs\trolley")
    WORLDS = [
        ("data/itch/snap_village.png",    "ДЕРЕВНЯ"),
        ("data/itch/snap_suburbs.png",    "ПРИГОРОД"),
        ("data/itch/snap_city.png",       "ГОРОД"),
        ("data/itch/snap_metropolis.png", "МЕТРОПОЛИС"),
        ("data/itch/snap_hell.png",       "АД"),
    ]

    canvas = Image.new("RGB", (W, H), COL_BG)
    canvas = canvas.convert("RGBA")
    canvas.alpha_composite(vignette())
    canvas = canvas.convert("RGB")

    # Cards sit in upper 78% — bottom 22% left empty for bottom overlay text
    BOTTOM_RESERVE = int(H * 0.22)   # ~238px
    TOP_PAD        = 40
    AVAIL_H        = H - BOTTOM_RESERVE - TOP_PAD   # usable height

    CARD_W  = 490   # slightly narrower than before (was 560)
    GAME_H  = 275   # proportionally shorter
    LABEL_H = 64
    CARD_H  = GAME_H + LABEL_H
    BORDER  = 2
    ROW_GAP = 28

    # Vertically center within the available upper band
    r1_y = TOP_PAD + max(0, (AVAIL_H - (CARD_H * 2 + ROW_GAP)) // 2)
    r1_gap = (W - 3 * CARD_W) // 4
    r1_xs = [r1_gap, r1_gap * 2 + CARD_W, r1_gap * 3 + CARD_W * 2]

    r2_y = r1_y + CARD_H + ROW_GAP
    r2_gap = (W - 2 * CARD_W) // 3
    r2_xs = [r2_gap, r2_gap * 2 + CARD_W]

    card_positions = [(r1_xs[0], r1_y), (r1_xs[1], r1_y), (r1_xs[2], r1_y),
                      (r2_xs[0], r2_y), (r2_xs[1], r2_y)]

    f_label = ImageFont.truetype(FONT_BLACK, 42)
    draw = ImageDraw.Draw(canvas)

    for idx, (snap_rel, world_name) in enumerate(WORLDS):
        cx, cy = card_positions[idx]
        snap = Image.open(DEVLOG / snap_rel).convert("RGB")
        sw, sh = snap.size
        target_ratio = CARD_W / GAME_H
        if sw / sh > target_ratio:
            new_w = int(sh * target_ratio)
            left = (sw - new_w) // 2
            snap = snap.crop((left, 0, left + new_w, sh))
        else:
            new_h = int(sw / target_ratio)
            top = (sh - new_h) // 2
            snap = snap.crop((0, top, sw, top + new_h))
        snap_thumb = snap.resize((CARD_W, GAME_H), Image.LANCZOS)

        draw.rectangle(
            (cx - BORDER, cy - BORDER, cx + CARD_W + BORDER, cy + GAME_H + BORDER),
            outline=COL_GOLD, width=BORDER
        )
        canvas.paste(snap_thumb, (cx, cy))

        label_bg = Image.new("RGB", (CARD_W, LABEL_H), (18, 15, 12))
        canvas.paste(label_bg, (cx, cy + GAME_H))

        draw_card = ImageDraw.Draw(canvas)
        lb = draw_card.textbbox((0, 0), world_name, font=f_label)
        lw, lh = lb[2] - lb[0], lb[3] - lb[1]
        lx = cx + (CARD_W - lw) // 2
        ly = cy + GAME_H + (LABEL_H - lh) // 2
        draw_card.text((lx + 2, ly + 2), world_name, fill=(0, 0, 0), font=f_label)
        draw_card.text((lx, ly), world_name, fill=COL_GOLD, font=f_label)

    out = DEVLOG / "data/infographics/worlds_collage.png"
    canvas.save(str(out))
    print(f"wrote {out}")
    return out


def build_sticky_finger_illustration():
    """Sticky finger: one big pointing index finger drags 4 scared people on a rope."""
    import math as _math

    canvas = Image.new("RGB", (W, H), COL_BG)
    canvas = canvas.convert("RGBA")
    canvas.alpha_composite(vignette())
    canvas = canvas.convert("RGB")
    draw = ImageDraw.Draw(canvas)

    WHITE     = (240, 236, 228)
    OUTLINE   = (20, 16, 12)
    EYE_COL   = (20, 16, 12)
    RED_DOT   = (192, 57, 43)
    ROPE_COL  = COL_GOLD
    SPEED_COL = (60, 52, 40)
    OW = 5

    CY = H // 2 - 20   # vertical center of the scene

    # ─── FINGER: large side-profile index finger, tip on the LEFT ───────────
    # Profile view: sausage shape (finger) + tapered base exiting right frame.
    # Finger points LEFT; the hand is moving RIGHT, dragging people behind.

    TIP_X = 1050     # fingertip x (left edge of finger capsule)
    TIP_Y = CY

    FING_W   = 96    # finger thickness (height)
    FING_LEN = 300   # finger length

    # ── main finger capsule ───────────────────────────────────────────────────
    fx0, fy0 = TIP_X, TIP_Y - FING_W // 2
    fx1, fy1 = TIP_X + FING_LEN, TIP_Y + FING_W // 2
    draw.rounded_rectangle([fx0, fy0, fx1, fy1],
                            radius=FING_W // 2, fill=WHITE, outline=OUTLINE, width=OW)

    # Knuckle creases: two straight vertical lines across the finger
    for kx_off in [FING_LEN // 3, (FING_LEN * 2) // 3]:
        kx = TIP_X + kx_off
        draw.line([(kx, fy0 + 12), (kx, fy1 - 12)], fill=OUTLINE, width=4)

    # ── tapered palm base: widens from finger width to PALM_W, exits right ───
    # Drawn as a polygon (trapezoid) from finger-end to right frame edge.
    PALM_W = 300   # palm height at right edge
    px0 = fx1 - 20  # overlaps finger end slightly
    draw.polygon(
        [(px0, fy0), (px0, fy1),              # left edge (finger width)
         (W + 10, TIP_Y + PALM_W // 2),       # right bottom corner (off-screen)
         (W + 10, TIP_Y - PALM_W // 2)],      # right top corner (off-screen)
        fill=WHITE, outline=OUTLINE
    )

    # Re-draw outline on the two sides of the trapezoid visible on screen
    draw.line([(px0, fy0), (W, TIP_Y - PALM_W // 2)], fill=OUTLINE, width=OW)
    draw.line([(px0, fy1), (W, TIP_Y + PALM_W // 2)], fill=OUTLINE, width=OW)

    # ── red glowing dot at fingertip ─────────────────────────────────────────
    for r, alpha in [(28, 50), (20, 120), (13, 255)]:
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse(
            [TIP_X - r, TIP_Y - r, TIP_X + r, TIP_Y + r],
            fill=(*RED_DOT, alpha)
        )
        canvas_rgba = canvas.convert("RGBA")
        canvas_rgba.alpha_composite(glow)
        canvas = canvas_rgba.convert("RGB")
        draw = ImageDraw.Draw(canvas)

    # ── speed lines (drawn to the right, OUTSIDE the palm area) ─────────────
    # These show the hand came from the right, moving right.
    # Draw them above and below the palm silhouette.
    for dy, length in [(-PALM_W // 2 - 40, 260), (-PALM_W // 2 - 80, 200),
                       (PALM_W // 2 + 40, 260),  (PALM_W // 2 + 80, 200)]:
        x0 = W - length - 30
        draw.line([(x0, CY + dy), (W - 20, CY + dy)], fill=SPEED_COL, width=3)

    # ─── PEOPLE: 4 stick figures trailing LEFT of the fingertip ──────────────
    HEAD_R = 65
    BODY_W = 46
    BODY_H = 56
    GAP    = 218  # center-to-center

    # Person 1 closest to finger; chain extends left
    p_xs = [TIP_X - 90 - GAP * i for i in range(4)]
    leans = [30, 18, 8, 0]  # each person leans right (pulled toward finger)

    def draw_person(cx, cy, lean=0):
        hx = cx + lean
        hy = cy - BODY_H // 2 - HEAD_R - 2
        # Body
        draw.rounded_rectangle(
            [cx - BODY_W // 2, cy - BODY_H // 2,
             cx + BODY_W // 2, cy + BODY_H // 2],
            radius=16, fill=WHITE, outline=OUTLINE, width=OW
        )
        # Head
        draw.ellipse([hx - HEAD_R, hy - HEAD_R, hx + HEAD_R, hy + HEAD_R],
                     fill=WHITE, outline=OUTLINE, width=OW)
        # Eyes — solid black dots (wide, scared)
        for ex in [hx - 21, hx + 21]:
            draw.ellipse([ex - 9, hy - 16 - 9, ex + 9, hy - 16 + 9], fill=EYE_COL)
        # Mouth — screaming O: filled dark oval
        draw.ellipse([hx - 13, hy + 6, hx + 13, hy + 30], fill=EYE_COL)
        # Lighter oval inside to show it's open (not a dot)
        draw.ellipse([hx - 7, hy + 10, hx + 7, hy + 26],
                     fill=(60, 30, 20))

    def draw_rope(x0, y0, x1, y1, sag=24):
        n = max(5, int(_math.hypot(x1 - x0, y1 - y0) // 8))
        pts = [(x0 + (x1 - x0) * t / n,
                y0 + (y1 - y0) * t / n + _math.sin(t / n * _math.pi) * sag)
               for t in range(n + 1)]
        for i in range(len(pts) - 1):
            draw.line([pts[i], pts[i + 1]], fill=ROPE_COL, width=7)

    # Ropes (under people)
    draw_rope(TIP_X, TIP_Y, p_xs[0] + BODY_W // 2, CY, sag=14)
    for i in range(3):
        draw_rope(p_xs[i] - BODY_W // 2, CY, p_xs[i + 1] + BODY_W // 2, CY)

    # Draw people right→left (person 1 drawn last = on top)
    for i in range(3, -1, -1):
        draw_person(p_xs[i], CY, lean=leans[i])

    out = OUT_DIR / "sticky_finger_illustration.png"
    canvas.save(str(out))
    print(f"wrote {out}")
    return out


def build_playtime_infographic():
    """Clock infographic for '15-20 минут полное прохождение'."""
    import math as _math
    canvas = Image.new("RGB", (W, H), COL_BG)
    draw = ImageDraw.Draw(canvas)

    cx, cy = W // 2, H // 2 - 40

    # Clock face
    R = int(H * 0.30)
    draw.ellipse((cx - R, cy - R, cx + R, cy + R), outline=COL_GOLD, width=6)

    # Hour marks
    for i in range(12):
        angle = _math.radians(i * 30 - 90)
        r_inner = R - 28 if i % 3 == 0 else R - 16
        x1 = cx + int(_math.cos(angle) * r_inner)
        y1 = cy + int(_math.sin(angle) * r_inner)
        x2 = cx + int(_math.cos(angle) * (R - 6))
        y2 = cy + int(_math.sin(angle) * (R - 6))
        w = 4 if i % 3 == 0 else 2
        draw.line([(x1, y1), (x2, y2)], fill=COL_GOLD, width=w)

    # Hands pointing ~17 min (12→ slightly past 15, approaching 20)
    # Hour hand at ~12:17 → points slightly left of 12 o'clock
    hour_angle = _math.radians(-83)   # just before 12
    draw.line([(cx, cy),
               (cx + int(_math.cos(hour_angle) * R * 0.55),
                cy + int(_math.sin(hour_angle) * R * 0.55))],
              fill=COL_GOLD, width=8)
    # Minute hand at ~20 min → pointing at 4 (120°)
    min_angle = _math.radians(30)   # 20 min → 120° clockwise from top
    draw.line([(cx, cy),
               (cx + int(_math.cos(min_angle) * R * 0.80),
                cy + int(_math.sin(min_angle) * R * 0.80))],
              fill=COL_GOLD, width=6)
    # Center dot
    draw.ellipse((cx - 10, cy - 10, cx + 10, cy + 10), fill=COL_GOLD)

    # No text — overlay in compose_beat.py provides "15-20 МИНУТ / ПОЛНОЕ ПРОХОЖДЕНИЕ"

    out = Path(r"C:\projects\devlogs\trolley") / "data/infographics/playtime_clock.png"
    canvas.save(str(out))
    print(f"wrote {out}")
    return out


if __name__ == "__main__":
    build_commit_chart()
    build_files_breakdown()
    build_biggest_files()
    build_daily_views()
    build_hype_curve()
    build_workflow_diagram()
    build_art_grid_cover()
    build_timeline_13days()
    print("Building animated infographics...")
    build_commits_chart_anim()
    build_daily_views_anim()
    build_workflow_anim()
    build_timeline_anim()
    build_hype_curve_anim()
    build_day1_progression()
    build_worlds_collage()
    build_playtime_infographic()
