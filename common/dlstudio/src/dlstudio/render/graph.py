"""Typed FFmpeg filter-graph AST + input-file registry.

This is the v2 replacement for v1's string-concatenated `_Graph` (legacy
common/devlog/render/compose_ffmpeg.py). Instead of hand-building
`filter_complex` strings, callers assemble a small AST of `FilterNode` /
`Chain` objects and a `Graph` renders it. Every v1 ffmpeg trap becomes an
encoded, unit-tested invariant living in one of these helpers:

- `scene_input_args`  -> the -ss / -loop / -t / -stream_loop matrix +
                         EOF-offset clamp + short-source freeze-pad
                         (ports legacy `_scene_input_args`).
- `xfade_offsets` / `build_xfade_chain` -> the cumulative-offset math
                         (ports legacy `_chain_xfade`; offset == sum of PRIOR
                         segment durations, NOT sum-minus-crossfade).
- `format_arg`        -> filtergraph option escaping (colons/commas/paths).

Nothing here shells out; `scene_input_args` takes an already-probed
`source_duration`, so the whole module is pure and cheaply unit-testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:                      # type-only: keeps graph.py import-cycle-free
    from dlstudio.model.edit import Duck


# ─── option-value formatting / escaping ────────────────────────────────────

# Characters that force single-quoting of a filter option value. `:` and `,`
# and `;` and `[]` are filtergraph structure; a space or quote or backslash
# would otherwise be mis-parsed. Windows paths (C:\...) hit the `:` case.
_TRIGGER = set(":,;[]' \t\\")


def _num(v: float) -> str:
    """Fixed 3-decimal formatting (matches legacy `{x:.3f}` conventions so
    ported tests can assert on `offset=5.000` style substrings)."""
    s = f"{v + 0.0:.3f}"
    return "0.000" if s == "-0.000" else s


def format_arg(v: object) -> str:
    """Render a single option value, quoting/escaping when required.

    - bool  -> "1"/"0" (ffmpeg boolean options)
    - int   -> as-is
    - float -> 3-decimal
    - str   -> single-quoted iff it contains filtergraph-special chars.
               Inside ffmpeg single quotes everything is literal except a
               single quote, which is written as the `'\\''` sequence.
    """
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float):
        return _num(v)
    if isinstance(v, int):
        return str(v)
    s = str(v)
    if s and any(c in _TRIGGER for c in s):
        return "'" + s.replace("'", "'\\''") + "'"
    return s


# ─── filter-graph AST ──────────────────────────────────────────────────────

@dataclass
class FilterNode:
    """One ffmpeg filter instance.

    `positional` values render first (e.g. scale=1920:1080), then `args` as
    key=value pairs. `inputs`/`outputs` are pad labels WITHOUT brackets; when
    non-empty the node renders as a standalone filterchain
    (`[in]name=...[out]`). A "bare" node (no inputs/outputs) renders as just
    `name=...` and is meant to be composed inside a `Chain`.
    """

    name: str
    args: dict[str, object] = field(default_factory=dict)
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    positional: list[object] = field(default_factory=list)

    def render_filter(self) -> str:
        """The `name=opt:opt` body, without pad labels."""
        opts = [format_arg(v) for v in self.positional]
        opts += [f"{k}={format_arg(v)}" for k, v in self.args.items()]
        return self.name + ("=" + ":".join(opts) if opts else "")

    def render(self) -> str:
        pre = "".join(f"[{p}]" for p in self.inputs)
        post = "".join(f"[{p}]" for p in self.outputs)
        return pre + self.render_filter() + post


@dataclass
class Chain:
    """A filterchain: several filters applied in sequence to one stream,
    comma-joined, with pad labels only at the ends
    (`[in]f1,f2,f3[out]`). The inner `FilterNode`s must be bare."""

    inputs: list[str]
    filters: list[FilterNode]
    outputs: list[str]

    def render(self) -> str:
        pre = "".join(f"[{p}]" for p in self.inputs)
        mid = ",".join(f.render_filter() for f in self.filters)
        post = "".join(f"[{p}]" for p in self.outputs)
        return pre + mid + post


class Graph:
    """Accumulates filterchains and renders the `-filter_complex` string.

    Owns auto-label allocation: `new_label(prefix)` returns process-unique
    pad names ("s1", "xf2", ...). Labels declared as node/chain outputs are
    registered so a later `new_label` can never collide with them.
    """

    def __init__(self) -> None:
        self._segments: list[str] = []
        self._counter = 0
        self._used: set[str] = set()

    def new_label(self, prefix: str = "v") -> str:
        while True:
            self._counter += 1
            lbl = f"{prefix}{self._counter}"
            if lbl not in self._used:
                self._used.add(lbl)
                return lbl

    def add(self, node: FilterNode | Chain) -> None:
        for o in getattr(node, "outputs", []):
            self._used.add(o)
        self._segments.append(node.render())

    def add_raw(self, segment: str) -> None:
        self._segments.append(segment)

    def render(self) -> str:
        return ";".join(self._segments)


# ─── input-file registry ───────────────────────────────────────────────────

class InputList:
    """Ordered ffmpeg `-i` input registry.

    `add(flags)` appends one input's full flag list (including its trailing
    `-i <path>`) and returns its stream index. `args()` flattens every input
    back into the ffmpeg argv in registration order. Index 0 is whatever is
    added first (the beat renderer registers the VO wav there)."""

    def __init__(self) -> None:
        self._inputs: list[list[str]] = []

    def add(self, flags: list[str]) -> int:
        idx = len(self._inputs)
        self._inputs.append(list(flags))
        return idx

    def __len__(self) -> int:
        return len(self._inputs)

    def args(self) -> list[str]:
        out: list[str] = []
        for flags in self._inputs:
            out.extend(flags)
        return out


# ─── ported invariant: scene input args ────────────────────────────────────

def scene_input_args(
    *,
    kind: str,
    src: str,
    offset: float,
    eff_dur: float,
    loop: bool = False,
    source_duration: float | None = None,
) -> tuple[list[str], float]:
    """ffmpeg input flags for one background segment + `pad_needed` (seconds
    of last-frame freeze required when the source is shorter than `eff_dur`).

    Direct port of legacy `_scene_input_args` — encodes three hard-won traps:

    * OFFSET-PAST-EOF: `offset >= dur-0.1` makes ffmpeg silently emit no video
      stream and the whole beat renders audio-only. We clamp offset to 0 and
      warn (v1's trailer_final offset=22-on-20s bug).
    * SHORT-SOURCE: a source shorter than `eff_dur` reads its whole tail
      (no `-t`) and reports `pad_needed`, which the normalize filter turns
      into a `tpad` last-frame freeze (v1's 5s-anim-in-6s-slot bug).
    * IMAGE: always `-loop 1 -t eff_dur` so a still fills the slot.

    `source_duration` is passed in (probed by the caller) so this stays pure.
    """
    if kind == "video":
        actual = source_duration if source_duration is not None else 0.0
        if offset >= actual - 0.1:
            print(
                f"[graph] WARNING: scene offset {offset:.2f}s is past source "
                f"duration {actual:.2f}s for {src}. Falling back to offset=0."
            )
            offset = 0.0
        available = max(0.0, actual - offset)
        if loop:
            # explicit "loop this ambient clip": read forever, -t cuts it
            return (
                ["-stream_loop", "-1", "-ss", f"{offset:.3f}",
                 "-t", f"{eff_dur:.3f}", "-i", src],
                0.0,
            )
        if available < eff_dur - 0.05:
            # source shorter than needed: read whole tail, freeze remainder
            return (["-ss", f"{offset:.3f}", "-i", src], eff_dur - available)
        # long enough: trim to eff_dur
        return (
            ["-ss", f"{offset:.3f}", "-t", f"{eff_dur:.3f}", "-i", src],
            0.0,
        )
    if kind == "image":
        return (["-loop", "1", "-t", f"{eff_dur:.3f}", "-i", src], 0.0)
    raise ValueError(f"unknown scene kind: {kind!r}")


# ─── ported invariant: xfade chain offset math ─────────────────────────────

def xfade_offsets(seg_durs: list[float]) -> list[float]:
    """Output-time offsets where each transition begins.

    offset[i] = sum(seg_durs[0..i]) — the cumulative duration of all PRIOR
    segments. This is the fix for v1's bug where offsets were computed as
    cumulative-minus-crossfade and every scene started 0.6s early.
    Returns len(seg_durs)-1 offsets.
    """
    offs: list[float] = []
    cum = 0.0
    for i in range(1, len(seg_durs)):
        cum += seg_durs[i - 1]
        offs.append(cum)
    return offs


# ffmpeg xfade transition names for our Transition.kind values.
XFADE_TRANSITION = {
    "fade": "fade",
    "cut": "fade",          # duration 0 -> hard cut
    "dip_black": "fadeblack",
    "slide_left": "slideleft",
    "slide_right": "slideright",
}


def build_xfade_chain(
    graph: Graph,
    labels: list[str],
    seg_durs: list[float],
    xfade_durs: float | list[float],
    transitions: list[str] | None = None,
) -> str:
    """Chain `labels` with xfade transitions and return the final pad label.

    `xfade_durs` may be a scalar (uniform crossfade, the legacy behaviour) or
    a per-boundary list of length len(labels)-1. `transitions` is an optional
    per-boundary list of ffmpeg transition names (default "fade"). Each
    positive-duration xfade's offset comes from `xfade_offsets`. A zero-
    duration boundary uses the concat filter: FFmpeg's ``xfade=duration=0``
    is degenerate and emits roughly only its second input, so it is not a
    hard cut. A single label is returned unchanged (no transition needed).
    """
    n = len(labels)
    if n <= 1:
        return labels[0] if labels else ""
    if isinstance(xfade_durs, (int, float)):
        xfade_durs = [float(xfade_durs)] * (n - 1)
    if transitions is None:
        transitions = ["fade"] * (n - 1)
    offs = xfade_offsets(seg_durs)
    prev = labels[0]
    for i in range(1, n):
        out = graph.new_label("xf")
        dur = float(xfade_durs[i - 1])
        if dur <= 0.0:
            graph.add(FilterNode(
                "concat",
                args={"n": 2, "v": 1, "a": 0},
                inputs=[prev, labels[i]],
                outputs=[out],
            ))
        else:
            graph.add(FilterNode(
                "xfade",
                args={
                    "transition": transitions[i - 1],
                    "duration": dur,
                    "offset": offs[i - 1],
                },
                inputs=[prev, labels[i]],
                outputs=[out],
            ))
        prev = out
    return prev


# ─── small builders shared by beat.py ──────────────────────────────────────

def color_source(graph: Graph, color: str, w: int, h: int, dur: float,
                 fps: int, label: str) -> str:
    """A solid-color background segment (`color=...,format=yuv420p`)."""
    graph.add(Chain(
        inputs=[],
        filters=[
            FilterNode("color", args={"c": color, "s": f"{w}x{h}",
                                      "d": float(dur), "r": fps}),
            # concat outputs AVTB (1/1_000_000).  Keep every background
            # source on that same timebase so a cut can be followed by xfade.
            FilterNode("settb", args={"expr": "AVTB"}),
            FilterNode("format", positional=["yuv420p"]),
        ],
        outputs=[label],
    ))
    return label


# ─── audio mix graph (assemble.py) ─────────────────────────────────────────
#
# The edit-level mix lays VO stems, music beds and SFX one-shots onto a single
# ABSOLUTE edit-timeline via `adelay`, ducks music under a summed VO bus with
# `sidechaincompress`, and sums everything with `amix`. Every builder here is a
# pure function returning a `FilterNode`/`Chain` (unit-tested by asserting on
# `.render()`), so the whole mix graph is assembled without string templating.

# Common audio normalization applied to every leaf input so mono VO, arbitrary
# music sample rates and stereo SFX meet at one format before summing (and so
# sidechaincompress's main/key inputs match, which it requires).
_MIX_SR = 48000
_MIX_LAYOUT = "stereo"


def db_to_linear(db: float) -> float:
    """dB (relative to full scale) -> linear amplitude ratio (10**(db/20))."""
    return 10.0 ** (db / 20.0)


def delay_ms(t: float) -> int:
    """Absolute placement time (seconds) -> integer milliseconds for `adelay`.
    Negative times clamp to 0 (nothing is placed before the edit start)."""
    return max(0, round(t * 1000.0))


def _aformat_node() -> FilterNode:
    return FilterNode("aformat", args={"sample_rates": _MIX_SR,
                                       "channel_layouts": _MIX_LAYOUT})


def _adelay_node(t: float) -> FilterNode:
    """`adelay=delays=<ms>:all=1` — one value applied to all channels
    regardless of channel count (mono VO or stereo music alike)."""
    return FilterNode("adelay", args={"delays": delay_ms(t), "all": 1})


def duck_params(duck: "Duck") -> dict[str, object]:
    """Map model `Duck` fields to ffmpeg `sidechaincompress` options.

    sidechaincompress compresses its FIRST input (the music) whenever its
    SECOND input (the VO sidechain key) rises above `threshold`. Mapping:

    - ``threshold``  <- ``db_to_linear(threshold_db)``. sidechaincompress's
      threshold is a LINEAR amplitude (0..1), NOT dB, so the model's
      ``threshold_db`` (default -30 dB) is converted (-30 dB -> ~0.0316).
    - ``ratio``      <- derived from ``amount_db`` (the desired duck depth):
      ``clamp(1 + |amount_db|/2, 2, 20)``. A deeper requested duck maps to a
      more aggressive ratio (amount_db=-12 -> ratio 7, in the ~8:1 ballpark
      the architecture calls for). Exact gain reduction still depends on how
      far VO sits above threshold, so this is a documented approximation, not
      a guaranteed -amount_db of attenuation.
    - ``attack``/``release`` <- ``attack_ms``/``release_ms`` straight through
      (sidechaincompress attack/release are already in milliseconds).
    - ``makeup`` pinned to 1 (no make-up gain): ducking must make music
      quieter under VO, never louder.
    """
    ratio = max(2.0, min(20.0, 1.0 + abs(duck.amount_db) / 2.0))
    return {
        "threshold": round(db_to_linear(duck.threshold_db), 6),
        "ratio": round(ratio, 3),
        "attack": int(duck.attack_ms),
        "release": int(duck.release_ms),
        "makeup": 1,
    }


def vo_stem_chain(in_stream: str, out_label: str, delay_t: float) -> Chain:
    """One VO stem -> stereo/48k, delayed to its beat's absolute start."""
    return Chain(
        inputs=[in_stream],
        filters=[_aformat_node(), _adelay_node(delay_t)],
        outputs=[out_label],
    )


def sfx_chain(in_stream: str, out_label: str, *, gain_db: float,
              delay_t: float, max_len: float | None = None) -> Chain:
    """One SFX one-shot -> stereo/48k, gain, delayed to its absolute anchor.

    `max_len` (when given) caps the SFX with an `atrim` BEFORE the delay, so a
    clip whose natural length would push it past the edit end is clamped: after
    the `adelay=delay_t`, the trimmed SFX ends no later than
    `delay_t + max_len`. The caller passes `max(0, total_duration - delay_t)` so
    a long SFX anchored near the finale can't extend the mixed audio (and thus
    the muxed output) past the video track. `None` (the default) keeps the SFX
    untrimmed — the legacy behaviour the pure unit tests assert on."""
    filters: list[FilterNode] = [
        _aformat_node(),
        FilterNode("volume", positional=[f"{gain_db}dB"]),
    ]
    if max_len is not None and max_len > 0.0:
        filters.append(FilterNode("atrim", args={"duration": round(max_len, 4)}))
    filters.append(_adelay_node(delay_t))
    return Chain(inputs=[in_stream], filters=filters, outputs=[out_label])


def music_span_chain(in_stream: str, out_label: str, *, span_len: float,
                     gain_db: float, fade_in: float, fade_out: float,
                     delay_t: float) -> Chain:
    """One music span -> stereo/48k, padded+trimmed to exactly `span_len`
    (short sources are silence-padded so the bed always fills its window),
    PTS reset, gain, fade in/out, then delayed to its absolute start `delay_t`.

    The caller additionally seeks the file with input-level `-ss offset`, so
    this chain works on a stream already positioned at the span's seek point;
    `apad`+`atrim` here guarantee the exact placed length regardless of how
    much material the source actually had after the seek."""
    filters: list[FilterNode] = [
        _aformat_node(),
        FilterNode("apad"),
        FilterNode("atrim", args={"duration": round(span_len, 4)}),
        FilterNode("asetpts", positional=["N/SR/TB"]),
        FilterNode("volume", positional=[f"{gain_db}dB"]),
    ]
    if fade_in > 0.001:
        filters.append(FilterNode("afade", args={"t": "in", "st": 0.0,
                                                  "d": round(fade_in, 4)}))
    if fade_out > 0.001:
        st = round(max(0.0, span_len - fade_out), 4)
        filters.append(FilterNode("afade", args={"t": "out", "st": st,
                                                  "d": round(fade_out, 4)}))
    filters.append(_adelay_node(delay_t))
    return Chain(inputs=[in_stream], filters=filters, outputs=[out_label])


def sidechain_duck_node(music_label: str, key_label: str, out_label: str,
                        duck: "Duck") -> FilterNode:
    """`[music][key]sidechaincompress=...[out]` — duck `music_label` under the
    VO `key_label` using `duck_params(duck)`."""
    return FilterNode("sidechaincompress", args=duck_params(duck),
                      inputs=[music_label, key_label], outputs=[out_label])


def amix_sum_node(in_labels: list[str], out_label: str,
                  duration: str = "longest") -> FilterNode:
    """`amix=inputs=N:normalize=0:duration=longest` — a straight SUM (not the
    default input-count average, which would attenuate) of `in_labels`."""
    return FilterNode(
        "amix",
        args={"inputs": len(in_labels), "normalize": 0, "duration": duration},
        inputs=list(in_labels), outputs=[out_label],
    )


def asplit_node(in_label: str, out_labels: list[str]) -> FilterNode:
    """`[in]asplit=N[o1][o2]...` — fan `in_label` out to N identical taps
    (used to feed the summed VO bus to the final mix AND to each ducking
    sidechain key)."""
    return FilterNode("asplit", positional=[len(out_labels)],
                      inputs=[in_label], outputs=list(out_labels))
