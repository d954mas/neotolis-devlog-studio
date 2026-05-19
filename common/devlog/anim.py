"""Small animation math helpers for generated devlog visuals.

The renderer is intentionally time-based, not frame-index-based: a scene
function receives seconds and maps them to 0..1 progress. This keeps assets
stable when an edit changes FPS.
"""
from __future__ import annotations

from collections.abc import Callable


EaseFn = Callable[[float], float]


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a float into a closed interval."""
    return max(lo, min(hi, value))


def lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation."""
    return a + (b - a) * clamp(t)


def ease_linear(t: float) -> float:
    return clamp(t)


def ease_in_cubic(t: float) -> float:
    t = clamp(t)
    return t * t * t


def ease_out_cubic(t: float) -> float:
    t = 1.0 - clamp(t)
    return 1.0 - t * t * t


def ease_in_out_cubic(t: float) -> float:
    t = clamp(t)
    if t < 0.5:
        return 4.0 * t * t * t
    return 1.0 - pow(-2.0 * t + 2.0, 3.0) / 2.0


def ease_out_back(t: float, overshoot: float = 1.70158) -> float:
    t = clamp(t) - 1.0
    return 1.0 + (overshoot + 1.0) * t * t * t + overshoot * t * t


EASES: dict[str, EaseFn] = {
    "linear": ease_linear,
    "in_cubic": ease_in_cubic,
    "out_cubic": ease_out_cubic,
    "in_out_cubic": ease_in_out_cubic,
    "out_back": ease_out_back,
}


def ease(name: str | EaseFn | None) -> EaseFn:
    if callable(name):
        return name
    if not name:
        return ease_out_cubic
    try:
        return EASES[name]
    except KeyError as exc:
        raise ValueError(f"Unknown easing {name!r}. Available: {', '.join(EASES)}") from exc


def progress(t: float, start: float = 0.0, duration: float = 1.0,
             easing: str | EaseFn | None = "out_cubic") -> float:
    """Return eased 0..1 progress for a time window."""
    if duration <= 0:
        return 1.0 if t >= start else 0.0
    raw = clamp((t - start) / duration)
    return ease(easing)(raw)


def staggered_progress(index: int, count: int, t: float, start: float = 0.0,
                       duration: float = 1.0, stagger: float = 0.08,
                       easing: str | EaseFn | None = "out_cubic") -> float:
    """Return per-item progress for sequential reveals."""
    if count <= 1:
        return progress(t, start, duration, easing)
    item_start = start + index * stagger
    item_duration = max(0.05, duration - index * stagger)
    return progress(t, item_start, item_duration, easing)


def count_up(target: float, t: float, start: float = 0.0, duration: float = 1.0,
             easing: str | EaseFn | None = "out_cubic") -> int:
    return int(round(target * progress(t, start, duration, easing)))
