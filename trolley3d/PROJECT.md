# trolley3d — видео-проект игры Not a Trolley Problem

Серия вертикальных рилсов о разработке игры (план: ~полгода, много
рилсов). Игра: `C:\projects\game-67-idle\games\private\game-not-a-trolley-problem`
(3D, собственный движок Neotolis, стиль «Playable Doodle»).

## Конвенции серии

- **Один рилс = один edit** `edits/<имя>/` (`__init__.py` + `beats.py` +
  `design.py`), dotted-путь `trolley3d.edits.<имя>`. Для новых рилсов —
  имена вида `r02_<slug>`, `r03_<slug>`… (исторически `main` == r01).
- **Общий пул ассетов** в `data/`: `music/`, `fonts/`, `images/`
  (канвас-рефы и мудборд уже лежат), `footage/` — футаж класть с
  префиксом рилса (`r02_boss.mp4`), сгенерированное — `infographics/`.
- **Дизайн-система серии**: бумага `#efece3`, чернила `#1c1b18`, красный
  трамвая `#c0392b`; шрифт `data/fonts/main.ttf`. Копируй `design.py` из
  `edits/main/` как основу — там же выверенные стили плашек.
- **Текст**: Overlay band, `y_ratio=0.73` (зона субтитров 0.66–0.78,
  платформенные safe zones — см. AGENTS.md «Reel defaults»), fade-вход
  0.25s, каждый текст ≥2s, хук в первые 0.5s.
- **Захват геймплея**: `scripts/capture_gameplay.py` — детерминированный
  devapi-захват, ПОРТРЕТ с суперсэмплингом (fb ~1622x2883 → 1080x1920).
  Никогда landscape+кроп; ошибка VQ-RES = пересъёмка.
- **Ролики «музыка + текст»** (без голоса): немые scratch-VO дорожки
  держат тайминги битов, текст — Overlay-карточки; вычитывай токены
  words JSON (Whisper врёт в английских названиях).

## Музыка

**Политика серии (директива лида): CC0 first.** Для новых рилсов (r02+)
подбирать CC0/public-domain треки (Pixabay Music, Free Music Archive
CC0, FreePD и т.п.) — без обязательной атрибуции. Attribution-required
трек допустим только с блокирующим предупреждением при доставке
(docs/CHECKLIST_VERTICAL_REEL.md, пункт A6).

Легаси r01: `data/music/groove_grove.mp3`, `retrofuture.mp3` — Kevin
MacLeod (incompetech.com), CC-BY 3.0 (источник — атрибуция в
опубликованном `neotolis_diary/data/publish/youtube_package.md`).
r01 выложен без атрибуции → **нужно дописать в подпись поста** (готовый
блок: `data/publish/reel_caption.md`). Если куплена incompetech
no-attribution лицензия — атрибуция не нужна, убрать её из файлов.

## Реестр рилсов

| # | edit | о чём | статус | дата |
|---|---|---|---|---|
| r01 | `main` | возвращение к игре: канвас (рефы+мудборд) → первый человечек → толпа и трамвай | ✅ выпущен | 2026-07-17 |

## Идеи следующих рилсов

- (пусто — добавляй сюда по ходу разработки игры)
