import type { Timeline } from "../api/types";
import { basename } from "../lib/format";

interface Props {
  ir: Timeline;
}

const PX_PER_SEC = 26;
const PAD_L = 10;
const PAD_R = 28;
const RULER_H = 22;
const GAP = 8;
const BEAT_H = 36;
const MUSIC_H = 26;
const SFX_H = 26;
const LABEL_W = 58; // left gutter for lane labels

function niceStep(total: number): number {
  const steps = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
  for (const s of steps) if (total / s <= 22) return s;
  return 600;
}

interface Row<T> {
  end: number;
  items: T[];
}

/** Greedy interval packing so overlapping spans stack into separate rows. */
function packRows<T>(
  spans: T[],
  t0: (s: T) => number,
  t1: (s: T) => number,
): T[][] {
  const rows: Row<T>[] = [];
  for (const s of [...spans].sort((a, b) => t0(a) - t0(b))) {
    let placed = false;
    for (const r of rows) {
      if (t0(s) >= r.end - 1e-6) {
        r.items.push(s);
        r.end = t1(s);
        placed = true;
        break;
      }
    }
    if (!placed) rows.push({ end: t1(s), items: [s] });
  }
  return rows.map((r) => r.items);
}

export function MixTimeline({ ir }: Props) {
  const beatById = new Map(ir.beats.map((b) => [b.id, b]));

  // Absolute total duration from placements + beat durations.
  let total = 0;
  for (const p of ir.placements) {
    const b = beatById.get(p.beat_id);
    if (b) total = Math.max(total, p.t0 + b.duration);
  }
  if (total <= 0) total = 1;

  const x = (t: number) => PAD_L + LABEL_W + t * PX_PER_SEC;
  const contentW = PAD_L + LABEL_W + total * PX_PER_SEC + PAD_R;

  const musicRows = packRows(
    ir.mix.music,
    (m) => m.t0,
    (m) => m.t1,
  );

  // Lane Y offsets.
  const beatsY = RULER_H + GAP;
  const musicY0 = beatsY + BEAT_H + GAP;
  const musicRowsH = Math.max(musicRows.length, 1) * (MUSIC_H + 2);
  const sfxY = musicY0 + musicRowsH + GAP;
  const height = sfxY + SFX_H + 8;

  const step = niceStep(total);
  const ticks: number[] = [];
  for (let t = 0; t <= total + 1e-6; t += step) ticks.push(t);

  // SFX absolute markers.
  const sfxMarkers: Array<{ t: number; label: string }> = [];
  for (const p of ir.placements) {
    const b = beatById.get(p.beat_id);
    if (!b) continue;
    for (const s of b.sfx) {
      sfxMarkers.push({
        t: p.t0 + s.t,
        label: `${basename(s.src)} ${s.gain_db}dB @${(p.t0 + s.t).toFixed(2)}s`,
      });
    }
  }

  const beatFills = ["#2f6b47", "#3a5a72"];
  const musicFill = "#4a6d99";

  return (
    <div>
      <div class="mix-legend">
        <span>
          total <b>{total.toFixed(2)}s</b>
        </span>
        <span>
          target LUFS <b>{ir.mix.target_lufs}</b>
        </span>
        {ir.mix.true_peak_db != null && (
          <span>
            true peak <b>{ir.mix.true_peak_db} dB</b>
          </span>
        )}
        <span>
          duck <b>{ir.mix.duck.amount_db}dB</b> / thr{" "}
          {ir.mix.duck.threshold_db}dB / {ir.mix.duck.attack_ms}·
          {ir.mix.duck.release_ms}ms
        </span>
        <span>
          music beds <b>{ir.mix.music.length}</b>
        </span>
        <span>
          sfx <b>{sfxMarkers.length}</b>
        </span>
      </div>
      <div class="mix-timeline">
        <svg
          width={contentW}
          height={height}
          viewBox={`0 0 ${contentW} ${height}`}
          style={{ display: "block" }}
        >
          {/* gridlines + ruler */}
          {ticks.map((t, i) => (
            <g key={"tick" + i}>
              <line
                x1={x(t)}
                y1={RULER_H}
                x2={x(t)}
                y2={height}
                stroke="#2a251d"
                stroke-width="1"
              />
              <text x={x(t) + 3} y={14} fill="#746a5a" font-size="10">
                {t}s
              </text>
            </g>
          ))}

          {/* lane labels */}
          <text x={PAD_L} y={beatsY + BEAT_H / 2 + 3} fill="#a99e8b" font-size="10">
            beats
          </text>
          <text x={PAD_L} y={musicY0 + 12} fill="#a99e8b" font-size="10">
            music
          </text>
          <text x={PAD_L} y={sfxY + SFX_H / 2 + 3} fill="#a99e8b" font-size="10">
            sfx
          </text>

          {/* beats lane */}
          {ir.placements.map((p, i) => {
            const b = beatById.get(p.beat_id);
            if (!b) return null;
            const bx = x(p.t0);
            const bw = Math.max(2, b.duration * PX_PER_SEC);
            return (
              <g key={"beat" + i}>
                <rect
                  x={bx}
                  y={beatsY}
                  width={bw}
                  height={BEAT_H}
                  rx={3}
                  fill={beatFills[i % beatFills.length]}
                  stroke="#14110d"
                />
                {bw > 30 && (
                  <text
                    x={bx + 5}
                    y={beatsY + 15}
                    fill="#f2ede0"
                    font-size="10"
                    font-weight="600"
                  >
                    {p.beat_id}
                  </text>
                )}
                {bw > 44 && (
                  <text x={bx + 5} y={beatsY + 28} fill="#c9c0af" font-size="9">
                    {b.duration.toFixed(2)}s
                  </text>
                )}
                <title>
                  {p.beat_id} · {b.duration.toFixed(2)}s @ {p.t0.toFixed(2)}s
                </title>
              </g>
            );
          })}

          {/* music lanes */}
          {musicRows.map((row, ri) =>
            row.map((m, mi) => {
              const mx = x(m.t0);
              const mw = Math.max(2, (m.t1 - m.t0) * PX_PER_SEC);
              const my = musicY0 + ri * (MUSIC_H + 2);
              return (
                <g key={`m${ri}-${mi}`}>
                  <rect
                    x={mx}
                    y={my}
                    width={mw}
                    height={MUSIC_H}
                    rx={3}
                    fill={musicFill}
                    fill-opacity={m.duck ? 0.9 : 0.6}
                    stroke="#14110d"
                  />
                  {mw > 40 && (
                    <text x={mx + 5} y={my + 12} fill="#f2ede0" font-size="9">
                      {basename(m.src)}
                    </text>
                  )}
                  {mw > 40 && (
                    <text x={mx + 5} y={my + 22} fill="#d7e0ee" font-size="9">
                      {m.gain_db}dB{m.duck ? " · duck" : ""}
                    </text>
                  )}
                  <title>
                    {m.src} · {m.gain_db}dB {m.duck ? "· ducked" : ""} · {m.t0.toFixed(2)}–
                    {m.t1.toFixed(2)}s
                  </title>
                </g>
              );
            }),
          )}

          {/* sfx markers */}
          {sfxMarkers.map((s, i) => {
            const sx = x(s.t);
            return (
              <g key={"sfx" + i}>
                <line
                  x1={sx}
                  y1={sfxY}
                  x2={sx}
                  y2={sfxY + SFX_H}
                  stroke="#e8b647"
                  stroke-width="2"
                />
                <polygon
                  points={`${sx - 4},${sfxY} ${sx + 4},${sfxY} ${sx},${sfxY + 6}`}
                  fill="#e8b647"
                />
                <title>{s.label}</title>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
