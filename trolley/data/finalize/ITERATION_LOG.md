# Iteration Log — Full Akt 0-3 Video Pipeline

## 🏆 LATEST DELIVERABLE (iter_46)
**`data/finalize/iterations/iter_46_LESS_KARAOKE.mp4`** — 3:57, 55 MB, 1080p30

Major architectural shift iter_42→46:
- iter_41: b10 (Results finale) recorded by user, integrated as full Akt 0-3 climax
- iter_42: `kind: "video"` added — trailer segments replace static cards in b3
- iter_43: REAL infographics from git log (273 commits per day) + file breakdown (139 files JS) plug into b4
- iter_44: `scene + overlay` system added — beat-level background that plays continuously, text overlays as bottom-band badges. Eliminates karaoke. Applied to b3, a2-3, a2-4 (asset_sheet_promo as scene = 50 cover iterations visible!), b10
- iter_45: scene+overlay applied to a1-1, a1-2, a2-1, a2-2

Now ~70% of video has continuous gameplay/infographic background with text overlays. Static text plates only for stand-alone punchline moments ($1000, СПАСИБО).

## 🏆 EARLIER DELIVERABLE (iter_40)
**`data/finalize/iterations/iter_40_BRIGHT2.mp4`** — 3:31, 15 MB, 1080p30

Order: a0-1 → a1-1 → a1-2 → b3 → b4 → a2-1 → a2-2 → a2-3 → a2-4 → a2-5 → a3-6.
Missing: b10 (Results — Wavedash 1st, $1000, #18/489, top-2 itch) — pending user recording.
Verdict: SOLID (iter_39 critic, blocked from HOOK-WORTHY until b10 landed for proper payoff).

### iter_36 → iter_40 changes
- iter_36: new order debut (b3/b4 added, dropped a0-2/a3-1..a3-5)
- iter_37: b3 chunk 0 → chaos_gameplay Day 13 card; b3 chunk 2 → snap_city card; b4 "30 000" bumped to 380; "ЗА 13 ДНЕЙ" subtitles on 273/102/30k; a1-1 "ТРАМВАЙ = МАШИНА" bumped 200→240 + brighter subtitle. Critic: HOOK-WORTHY.
- iter_38: COL_GOLD_DIM 83% → 90% for mobile contrast (all beats re-rendered).
- iter_39: a2-1 chunk 0 plate changed from duplicate "ВСЁ НАПИСАЛ ИИ" to "ПРИМИТИВЫ · НАПИСАЛ ИИ" — eliminated back-to-back identical plates with b4.
- iter_40: COL_GOLD_DIM 90% → 96% for full mobile readability (224,174,69).

## 🏁 EARLIER DELIVERABLE (iter_33)
**`data/finalize/iterations/iter_33_FULL_v4.mp4`** — 4:46, 19 MB, 1080p30 (pre-restructure, contained dropped beats)

### Pipeline summary
- 34 iterations of compose → render → critic cycle
- Audio: -14 LUFS two-pass loudnorm, 14 beats cached
- Whisper word-level sync: medium model, all 14 transcripts cached
- Visual composer: PIL plates + MoviePy framed cards + radial vignettes
- 15 beats rendered (a0-1 → a3-6)
- 8 image-card replacements integrated for visual variety
- Design system locked: chocolate #1a1612 + gold #e8b647 + accent red #c0392b
- Typography: Bahnschrift (Latin/numbers) + Tahoma Bold (Cyrillic, clean Й)

### Per-cycle progression
- iter_01–10: pipeline calibration on a0-2 hook
- iter_11–18: design system refinement (cards, vignettes, typography)
- iter_19–22: parallel Whisper processing for all 14 beats
- iter_23: first 4-beat concat = 59.4s
- iter_24: 🎯 HIGHLY-POLISHED verdict on 4-beat preview
- iter_25–30: scale pipeline to all 15 beats, first full concat
- iter_31–33: visual variety upgrades (image cards replace text plates)
- iter_34: final critique

---

# a0-2 Iteration Log (early cycles 1-22)

Goal: incredible-quality first beat ($1000 hook). Iterative cycle:
1. Edit composition (`scripts/compose_beat.py`)
2. Render (`python scripts/compose_beat.py a0-2`)
3. Critic review (subagent vision-based)
4. Apply feedback → next iteration

Each iteration saved as `iterations/iter_NN.mp4`.

---

## 🏁 MILESTONE: iter_33 = LATEST FULL VIDEO
**Path:** `data/finalize/iterations/iter_33_FULL_v4.mp4` — **4:46 minutes, 19 MB**

### Image cards now integrated (visual variety fix):
- a2-2 ("даже большие, даже долгие"): chaos gameplay framed card
- a2-3 ("3 практики"): trolley progression sheet at the end
- a2-3 chunk 0: "ЛОШАДЬ БЕЗ ТОРМОЗОВ" text plate (no emoji)
- a3-2: "ЛИПКИЙ ПАЛЕЦ" Day 1 gameplay card
- a3-3 chunk 0: "#2 БОССЫ" real boss gameplay (instead of pure text announce)
- a3-3 chunk 3: "ПЕРЕПИСАЛ · СТАЛО ЛУЧШЕ" city snap framed card
- a3-4: "10 КАРТ · 2 347 СТРОК" real choice modal (clean, no debug panel)
- a3-5: "ДЕРЕВО · 59 НОД" real upgrade tree

### Текстовые плашки (с системой red_underline + dim-gold subtitle):
- a0-1: 0 СТРОК КОДА
- a0-2: 7 chunks ($1000, 13 дней, 30k ИИ, Day 1 gameplay card, 1-Е МЕСТО WAVEDASH, #18/489, ТОП-2 ITCH.IO)
- a1-1: 6 chunks (GAMEDEV.JS JAM, MACHINES, 13 ДНЕЙ, ТРАМВАЙ = МАШИНА, ПРОБЛЕМА ВАГОНЕТКИ, А ЧТО ЕСЛИ)
- a1-2: 4 chunks (ДЕНЬ ПЕРВЫЙ, РЕЛЬСЫ КРУЖОЧКИ, ТЕСТ МЕХАНИКИ card, ТАЩИШЬ→БРОСАЕШЬ)
- a2-1: 7 chunks (workflow methodology)
- a2-3: "1. РАМКИ", "2. ДЕКОМПОЗИЦИЯ", "3. КОНФИГИ" + 3 практики
- a2-4: 50 ИТЕРАЦИЙ
- a2-5: ИГРОКИ ПРАВЫ + защита
- a3-1: 13 ДНЕЙ РАБОТЫ
- a3-3: ДЕНЬ 12 / 24 ЧАСА / ПЕРЕПИСАЛ
- a3-6: 26 АПРЕЛЯ / ЗАГРУЖЕНО / А ДАЛЬШЕ

## 🏁 MILESTONE: iter_32 = FULL 4:46 VIDEO RENDERED
After 32 cycles of compose→render→critic loop:
- All 15 beats rendered (a0-1 through a3-6)
- All 14 cached audio+Whisper transcripts ready
- Final preview: `data/finalize/iterations/iter_32_FULL_v3.mp4`
- Duration: **4:46** (target was 5 min — попадание)
- File size: 19 MB, H.264, 1080p30
- Emoji 1️⃣/2️⃣/3️⃣ replaced with "1.", "2.", "3." (fonts didn't support enclosed digit emojis)
- 4 text plates replaced with real game screenshots (trolley progression, city snap, choice modal, upgrade tree) for visual variety

## 🎯 MILESTONE: iter_24 = HIGHLY-POLISHED (verdict)
After 24 cycles, critic verdict reached HIGHLY-POLISHED for 4-beat concat preview (a0-1 + a0-2 + a1-1 + a1-2 = 59.4s).

Key wins consolidated:
- Audio chain: -14 LUFS two-pass loudnorm
- Whisper word-level timing (cached per beat, 14 beats processed in parallel)
- Typography system: bahnschrift+tahomabd, palette chocolate/gold/red, dim-gold subtitles
- Red underline as design token (480px fixed width)
- Framed cards for game footage (inset label, gold border, radial vignette)
- Visual peak hierarchy: 1-Е МЕСТО bumped 280→380 to mark climax
- ДЕНЬ ПЕРВЫЙ chapter title differentiated from ДЕНЬ 1 inset label

Remaining flow improvements suggested by critic:
- Narrative bridge between beats 1 (0 строк) and 2 ($1000)
- Beat 3 (jam results) needs anchor (day counter?)
- t32 "ТРАМВАЙ = МАШИНА" needs subtitle context

## iter_03 → iter_04 fixes (per iter_03 critic)
- Double-489: drop denominator from chunk 5 subtitle (replace with "ТОП 4%")
- Medal: replace 🥈 emoji with custom-drawn silver #2 in brand palette
- ДЕНЬ 1 pill: bigger, anchored to dark zone, semi-transparent backdrop
- Red divider chunk 2: move to under-text underline-style
- Й clip safety: increase top padding for tall Cyrillic glyphs

## iter_02 → iter_03 changes (applied per iter_02 critic)
- Chunk 1: "РАЗРАБОТКИ" subtitle added
- Chunk 3: "ДЕНЬ 1" label branded style
- Chunk 4: Wavedash subtitle WHITE
- Chunk 5: "GAMEDEV.JS JAM · 489 ИГР" subtitle
- Chunk 6: 🥈 medal instead of duplicate 🏆

## iter_01 → iter_02 changes (applied per iter_01 critic)
- Standardized plate sizes (hero 240-280, subtitle 52-60)
- Red full-card → gold-on-dark + red accent line + ИИ chip
- Day 1 gameplay: added "ДЕНЬ 1" label
- Wavedash hierarchy: hero vs subtitle split
- itch screenshot → ТОП-2 plate

## iter_01 (baseline = v3)
- Audio: -15.9 LUFS, two-pass loudnorm, silenceremove leading
- Whisper word-timestamps (medium model), 38 words mapped
- 7 chunks: $1000 / 13дней / 30k+ИИ / Day1геймплей / Wavedash / #18 / itch top-2
- Typography: arialbd for Cyrillic, bahnschrift for Latin/numbers, auto-shrink, vignette, accent_card mode
- Motion: plates fade-in + 4% punch-zoom, images fade + 6% Ken Burns
- Known weak points:
  - Chunk 6 (itch top-2 screenshot) — не считывается как "мы там №2"
  - Hard cuts между chunk'ами (нет crossfade overlap)

---

## Open questions for user (when returns)

- (none yet)
