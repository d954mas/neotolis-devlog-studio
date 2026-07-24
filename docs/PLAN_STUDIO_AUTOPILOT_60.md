# Studio Autopilot 60 — план производства девлога менее чем за час

Дата: 2026-07-18

## 1. Цель

Стандартный горизонтальный девлог длительностью 2–4 минуты должен проходить
путь от утверждённого текста/VO и доступного проекта до готового delivery-
пакета не более чем за **60 минут wall time**.

Целевой бюджет:

- до 15 минут — первое watchable storyboard-preview;
- до 20 минут личного времени автора, включая запись и одно пакетное ревью;
- не более одного содержательного checkpoint;
- не более двух рендеров: 540p storyboard и 1080p final;
- ноль пользовательских исправлений детерминированных ошибок;
- не более 3 узких AI-ролей без передачи им полной истории чата;
- одна игра хранится в одном product root независимо от формата ролика;
- production-папки имеют вид `YYYY_MM_DD_<kind>_<number>`;
- delivery-папка содержит video, metadata и thumbnail/cover;
- сценарий проходит human approval до записи, а Studio даёт полноценный
  karaoke/teleprompter;
- publish package содержит отдельно tags, hashtags и Telegram copy;
- wall/human time и tokens атрибутируются конкретному product/production/stage.

Если отсутствует обязательный настоящий footage или финальный VO, SLA
останавливается на раннем consolidated request, а не расходуется на монтаж
с плохими заменителями.

Этот документ ужесточает старую метрику `devlog final — за день` из
`PLAN_STUDIO_V2.md` для повторяемого 2–4-минутного формата.

## 2. Что сломалось в Devlog 01

Рендер не был bottleneck: FFmpeg/audio заняли минуты, а весь production run —
около 5 ч 35 мин. Время потеряно в поздних циклах проверки.

Studio пропустила:

- повтор фразы/трейлера про 13 дней;
- повтор одного Canvas-фрагмента и возврат старых сцен в финале;
- кадры, которые исчезали раньше, чем зритель успевал их прочитать;
- слишком долгие статичные кадры;
- portrait/reel Canvas низкого качества внутри landscape-девлога;
- псевдо-трамвай при наличии настоящих 2D/3D кадров;
- tofu-глиф, пустой низ montage и ступенчатый zoom;
- шум в первых секундах VO;
- разрозненный delivery и неготовые hashtags.

Текущие engine-checks покрывают только VQ-ASSET, VQ-WORDS, VQ-RES,
VQ-OFFSET и VQ-SYNC. Пейсинг, повтор, свежесть источника, читаемость,
заполнение кадра и completeness публикации остаются поздним человеческим
judgment. Это и есть основной архитектурный разрыв.

## 3. Целевой production flow

| Время | Стадия | Автоматический результат | Human action |
|---:|---|---|---|
| 00–03 | Intake | формат, длина, цель, product root, time budget | нет |
| 03–07 | Inventory | каталог доступных assets с качеством, датой, ориентацией и provenance | нет |
| 07–12 | Shot plan | VO → shot ledger; каждый тезис получает источник и длительность | нет |
| 12–15 | Storyboard | 540p hard-cut preview, contact sheet, boundary strip | нет |
| 15–20 | Preflight | blockers: duplicate/pacing/source/readability/audio/delivery | нет |
| 20–30 | Checkpoint | одно окно: сценарий + shots + все спорные решения | approve одним пакетом |
| 30–40 | Safe fixes | автоматическая замена/тайминг/motion/capture существующих сцен | нет |
| 40–48 | Regression | blind artifact review + constraint regression | нет |
| 48–55 | Final | 1080p, loudnorm, exact-hash verification | нет |
| 55–60 | Delivery | MP4 + metadata + thumbnail/cover + hashtags | финальное открытие папки |

## 4. Workstream A — Shot и Source Contract

### A1. Shot ledger как обязательный вход

Добавить `data/plan/shot_manifest.json`. Одна строка на один визуальный shot:

```json
{
  "id": "b03_s02",
  "vo_range": [12, 24],
  "purpose": "show_real_2d_limitation",
  "src": "data/footage/old2d/tram_turn.mp4",
  "source_role": "real_product",
  "t0": 33.4,
  "t1": 37.0,
  "min_readable_duration": 2.4,
  "reuse": "forbidden",
  "motion": "native",
  "approved": true
}
```

Планировщик обязан доказать до рендера:

- каждый VO-тезис покрыт визуалом;
- повтор источника явно помечен как `callback`, иначе запрещён;
- real-product claim использует настоящий capture;
- text shot имеет вычисленное время чтения;
- один source не используется для двух разных смыслов случайно.

### A2. Asset catalog

Добавить `data/assets/catalog.json`, автоматически построенный через ffprobe,
hash/perceptual hash и project metadata:

- source path и content hash;
- resolution, orientation, fps, duration;
- captured/modified date;
- `intended_for`: landscape, vertical, both;
- provenance: game capture, Canvas, Steam, Diary, generated;
- `source_role`: real product, reference, illustration, generated;
- quality flags: upscale, letterbox, stale, unreadable, duplicate;
- usage history по другим роликам продукта.

Выбор источников: newest native real capture first. Старый reel-source не
может стать full-bleed landscape-shot без явного override.

### A3. Внешний capture agent

Studio не получает встроенный gameplay recorder. Канонический skill вызывает
внешний capture agent через devapi и принимает результат через asset catalog.
Все недостающие captures отправляются одним parallel batch до минуты 10.

## 5. Workstream B — Mechanical QC и safe autofix

Расширить `dlstudio/check` следующими IR-native правилами.

| Код | Что ловит | Draft | Final |
|---|---|---|---|
| VQ-DUP | одинаковый src/offset или perceptual duplicate в несмежных shots | warn | block |
| VQ-PACE | shot слишком короткий/длинный для своего типа | warn | block при грубом нарушении |
| VQ-READ | overlay исчезает раньше вычисленного времени чтения | block | block |
| VQ-SOURCE | wrong orientation, stale/reel source, upscale, wrong product role | block | block |
| VQ-GLYPH | отсутствующие глифы во всём overlay/caption тексте | block | block |
| VQ-FRAME | чрезмерная пустая область/letterbox/малый полезный контент | warn | block для generated montage |
| VQ-AUDIO-START | click/noise burst/аномальный noise floor в первых 3 секундах | warn | block при impulse/clipping |
| VQ-BOUNDARY | loading/black/stale flash за ±0.25 s вокруг каждого cut | warn | block |
| VQ-MOTION-SMOOTH | повтор соседних кадров и ступенчатый zoom/pan | warn | block |
| VQ-DELIVER | нет video/metadata/image либо hashtags невалидны | — | block delivery |

Базовые pacing defaults для profile `landscape_devlog`:

- любой читаемый текст: минимум `max(2.0 s, 0.5 + chars / 15)`;
- обычный shot короче 1.2 s требует intent `flash/montage`;
- статичный screenshot дольше 4 s требует motion/crop change;
- статичный screenshot дольше 6 s без intent `deliberate_hold` блокирует final;
- повтор non-contiguous source требует intent `callback`;
- generated schematic не заменяет real product при наличии подходящего capture.

### Safe autofix contract

После тестирования расширить автономно разрешённые операции:

- выровнять shot duration внутри существующего VO/chunk;
- заменить source на catalog asset с тем же purpose и более высоким quality;
- добавить плавный subpixel Ken Burns к статичному shot;
- заменить повтор другим offset/crop только если смысл остаётся тем же;
- пересобрать montage без пустых ячеек;
- применить локальный denoise/crossfade без удаления слов;
- исправить delivery metadata и hashtags.

Изменение смысла, VO, состава beats или спорного claim остаётся stop-condition.

## 6. Workstream C — Autopilot, Studio UI и Delivery

### C1. Детерминированные команды

Не добавлять AI-runtime внутрь `dlstudio`. CLI/UI предоставляют факты и
операции, а канонический skill оркестрирует их:

```text
dl2 inventory <edit>    # asset catalog
dl2 storyboard <edit>   # shot manifest + быстрый 540p hard-cut
dl2 preflight <edit>    # все VQ rules + JSON autofix suggestions
dl2 deliver <edit>      # датированный publish bundle
```

### C2. Канонический autopilot skill

`dl-make-video` запускает стадии как state machine с deadline budget.
Вместо 24 full-history agents используются максимум три узких контекста:

1. planner: brief + script + asset catalog → shot manifest;
2. reviewer: exact MP4 + IR + keyframes → machine-readable findings;
3. packager: final facts → metadata/thumbnail/delivery.

Каждой роли передаются только нужные артефакты. История пользовательских
предпочтений хранится компактно в project profile, а не размножается в каждом
agent fork.

### C3. Один Studio checkpoint

Studio UI показывает одну таблицу:

- слева VO-тезис;
- по центру выбранный shot и source provenance;
- справа duration, quality flags и proposed fix;
- сверху wall-time budget и blockers;
- действия: `Approve all`, `Replace shot`, `Request capture`, `Change text`.

Все вопросы пользователю консолидируются в одном checkpoint, а не приходят
по одному после каждого рендера.

### C4. Delivery

`dl2 deliver` создаёт:

```text
not_a_trolley_problem/
  delivery/
    devlogs/
      2026_07_17_devlog_01/
        video.mp4
        metadata.md
        thumbnail.png
```

`metadata.md` содержит отдельные title, description, YouTube tags, copy-ready
hashtags и chapters. Hashtag обязан соответствовать
`^#[\p{L}\p{N}_]+$`.

## 7. Реализация по волнам

Полный scope требует не 4–6, а ориентировочно **8–12 инженерных дней**.
Быстрый QC-only patch не решит структуру проектов, запись, упаковку и
наблюдаемость, поэтому порядок ниже является зависимостным.

### Wave 0 — regression corpus и product contract (1 день)

- сохранить fixtures всех ошибок Devlog 01;
- добавить `ProductManifest` и `ProductionManifest`;
- закрепить target tree, production id и output isolation;
- добавить stage timer и token/agent counters.

Gate: каждый feedback item ниже связан с тестом или явным human preference.

### Wave 1 — безопасная миграционная инфраструктура (1–2 дня)

- path-based production loader с backward compatibility для dotted modules;
- production-scoped `review/finalize/publish/delivery`;
- `dl2 migrate-product --dry-run` и hash manifest;
- collision/dedup report для shared assets.

Gate: `trolley_devlog` и `trolley3d` компилируются из нового product root,
старые финальные MP4 сохраняют SHA-256, старые папки ещё не удалены.

### Wave 2 — Script/VO/Teleprompter (1–2 дня)

- natural-language script profile и duration estimate;
- approval snapshot перед записью;
- полноценная karaoke-строка с current/next/full-text context;
- first-3s audio, transcript proper nouns и join preflight.

Gate: один утверждённый script id однозначно связан с take и words JSON;
запись не может потерять начало фразы или суфлёр.

### Wave 3 — Shot/Source Contract (1–2 дня)

- модели `ShotManifest` и `AssetCatalog`;
- `dl2 inventory` и `dl2 storyboard`;
- VQ-DUP, VQ-PACE, VQ-READ, VQ-SOURCE, VQ-GLYPH;
- batch gameplay/Canvas/Diary capture через внешний capture agent.

Gate: старые, repeated, too-short, too-long, fake-product и tofu fixtures
блокируются до полного render.

### Wave 4 — Visual/audio/delivery gates (1–2 дня)

- VQ-FRAME и VQ-AUDIO-START;
- `dl2 deliver` и VQ-DELIVER;
- thumbnail/cover, YouTube package, Telegram copy и hashtags validation;
- product/production token attribution.

Gate: delivery открывается как одна папка; metadata можно копировать без
ручного редактирования.

### Wave 5 — Autopilot skill + UI checkpoint (1–2 дня)

- deadline state machine;
- 3-role compact context routing;
- one-screen approval и safe autofix batch;
- preference profile и known-constraints regression.

Gate: clean-room agent производит video без ручных CLI-команд пользователя.

### Wave 6 — два контрольных ролика (1 день тестирования)

Прогнать один reel и один 2–4-минутный devlog из общего product root. Не
чинить pipeline вручную во время теста: любое отклонение записывается как
failed metric или новый gate.

## 8. Acceptance criteria

Autopilot 60 считается готовым, когда два последовательных реальных ролика:

- завершаются за ≤60 минут каждый;
- требуют ≤20 минут личного времени автора;
- имеют first storyboard ≤15 минут;
- требуют ≤1 пакетного review;
- имеют 0 deterministic corrections после handoff;
- используют ≤3 AI roles и не fork'ают полную историю;
- укладываются ориентировочно в ≤100M processed / ≤8M non-cached tokens;
- проходят exact-hash regression review;
- выдают одну полную delivery-папку.

Если ролик не проходит эти критерии, Studio не объявляет `SHIP`; отчёт должен
назвать конкретный failed gate и stage, который превысил бюджет.

## 9. Первый implementation slice

Начать не с UI и не с нового генератора монтажа. Первый вертикальный slice:

1. `ProductManifest` + `ProductionManifest`;
2. path-based loader и production-scoped output roots;
3. `dl2 migrate-product --dry-run` с hash/collision report;
4. перенести копированием оба существующих edits в новый root без удаления
   старых папок;
5. доказать semantic IR parity и сохранение SHA-256 финальных MP4.

Следующий slice сразу после migration foundation:

1. `ShotManifest` + `dl2 storyboard`;
2. VQ-DUP + VQ-PACE + VQ-READ + VQ-SOURCE;
3. fixtures из Devlog 01;
4. повторная компиляция существующего edit должна найти дубли, плохой Canvas
   и неверные длительности до рендера.

Так Studio сначала получает правильную product/production структуру, а затем
убирает «детские ошибки» до первого рендера.

## 10. Полная миграция `trolley_devlog` + `trolley3d`

### 10.1. Почему простого move недостаточно

Сейчас обе production-папки являются отдельными Python packages:

- `trolley_devlog.edits.main`;
- `trolley3d.edits.main`.

Они используют общие относительные пути `data/...`, а CLI по умолчанию пишет
в project-wide `data/review`, `data/finalize` и `data/publish`. Если просто
положить два edits в один package, результаты начнут перезаписывать друг
друга. Если просто переименовать директории с датой в начале, текущая команда
`new-video` отвергнет их как невалидные Python identifiers.

Миграция требует сначала отделить **публичный production path** от внутреннего
Python module id и сделать outputs production-scoped.

### 10.2. Целевая структура

```text
not_a_trolley_problem/
  product.toml
  shared/
    assets/
      gameplay/
      steam/
      diary/
      canvas/
      fonts/
      music/
      sfx/
    preferences.toml
  devlogs/
    2026_07_17_devlog_01/
      production.toml
      edit/
        __init__.py
        beats.py
        design.py
      data/
        audio/
        recordings/
        scratch/
        footage/
        images/
        hyperframes/
        infographics/
        plan/
        review/
        finalize/
        publish/
  reels/
    2026_07_17_reel_01/
      production.toml
      edit/
      data/
  delivery/
    devlogs/
      2026_07_17_devlog_01/
        video.mp4
        metadata.md
        thumbnail.png
    reels/
      2026_07_17_reel_01/
        video.mp4
        metadata.md
        cover.png
```

Пользовательские папки имеют точный prefix `YYYY_MM_DD`. Loader загружает
`edit/__init__.py` по filesystem path под синтетическим безопасным module id,
поэтому имя production-папки больше не обязано быть Python identifier.

### 10.3. Manifest contracts

`product.toml`:

```toml
id = "not_a_trolley_problem"
title = "Not a Trolley Problem"
game_root = "C:/projects/game-67-idle"

[sources]
steam = "..."
itch = "..."
diary = "https://neotolis-diary.dev"
```

`production.toml`:

```toml
id = "2026_07_17_devlog_01"
kind = "devlog"
date = "2026-07-17"
orientation = "landscape"
edit_path = "edit"
data_root = "data"
delivery_root = "../../delivery/devlogs/2026_07_17_devlog_01"
```

Manifest является единственным источником путей для Studio, CLI, review,
publish и telemetry.

### 10.4. Команды

```text
dl2 new-product not_a_trolley_problem
dl2 new-production not_a_trolley_problem --kind devlog --date 2026-07-18
dl2 list-productions not_a_trolley_problem
dl2 migrate-product --to not_a_trolley_problem \
  --from trolley_devlog --from trolley3d --dry-run
dl2 migrate-product --plan data/migration/plan.json --apply
dl2 deliver not_a_trolley_problem:2026_07_17_devlog_01
```

Старый `dl2 new-video <python-package>` остаётся как backward-compatible
legacy entrypoint, но новые production создаются product-first.

### 10.5. Порядок безопасной миграции

1. Зафиксировать список файлов, sizes, SHA-256 и старые dotted edit ids.
2. Создать новый root и manifests без изменения старых папок.
3. Скопировать production-specific files; общие assets дедуплицировать по
   content hash в `shared/assets`.
4. Переписать пути через manifest-aware resolver, не regex по исходникам.
5. Скомпилировать старый и новый IR; сравнить durations, shot sources,
   overlays, mix и resolution семантически.
6. Запустить `dl2 check`, 540p preview и exact-frame regression для reel и
   devlog.
7. Скопировать существующие final MP4 в delivery без перекодирования и
   подтвердить сохранение SHA-256.
8. Переключить Studio index/default production на новый root.
9. Старые папки оставить read-only на один успешный production cycle.
10. Архивировать их только после явного подтверждения пользователя; ничего
    автоматически не удалять.

### 10.6. Migration acceptance

- оба production видны в одной Studio project page;
- данные reel и devlog не пересекаются;
- shared assets хранятся в одном экземпляре;
- `check/preview/final/publish/deliver` работают по production id;
- старые final hashes сохранены;
- rollback = переключение manifest/default обратно, без восстановления из
  backup и без потери файлов.

## 11. Сценарий, авторский голос и запись

### 11.1. Script writer contract

Сценарный агент получает не общую просьбу «напиши красиво», а project voice
profile:

- всегда первое лицо единственного числа: `я`, не `мы`;
- автор — соло-разработчик и говорит от собственного опыта;
- короткие разговорные предложения;
- одна мысль на фразу;
- никаких нейросетевых вводных, резюме и искусственного пафоса;
- технические детали только когда они объясняют видимое решение;
- hook, contradiction, proof, decision, current state, next step;
- target words вычисляется из реального темпа автора;
- каждое утверждение связано с proof asset или помечено opinion/plan;
- перед записью пользователь получает финальный текст и predicted duration.

Для Devlog 01 профиль обязан был сохранить конкретику: новая 3D-версия с
нуля, собственный engine, сложность вращать 2D-трамвай и добавлять руки,
AI Studio как инструмент, Diary как продвижение, автор выбирает направление.

### 11.2. Script quality gates

- `VQ-SCRIPT-VOICE`: нет `мы`, если production profile = solo;
- `VQ-SCRIPT-LENGTH`: predicted duration попадает в target ±10%;
- `VQ-SCRIPT-DENSITY`: нет двух повторных формулировок одного факта;
- `VQ-SCRIPT-PROOF`: у product claim есть shot purpose/source request;
- `VQ-SCRIPT-AI`: список запрещённых шаблонных оборотов и reviewer score;
- `VQ-SCRIPT-APPROVAL`: recording привязан к approved script hash.

### 11.3. Karaoke/teleprompter

Studio recording screen должна вернуть:

- полный текст, текущую фразу и следующую фразу одновременно;
- word-level karaoke по мере записи;
- ручное перемещение по фразам без потери take;
- размер/ширину/скорость отдельно от captions в ролике;
- countdown, restart phrase и resume;
- take → approved script hash → transcript words lineage;
- индикацию, если запись началась до готовности микрофона.

### 11.4. VO preflight

До монтажа автоматически проверить:

- первые 3 секунды: noise floor, impulse/click, clipped consonant;
- silence gaps и резкие joins;
- transcript proper nouns: Not a Trolley Problem, Neotolis, Steam;
- соответствие approved script и фактически произнесённого текста;
- loudness/energy по фразам;
- отсутствие обрезанного первого/последнего слова.

Локальный denoise допустим, если diff-report показывает сохранение речи.
Иначе Studio формирует один точный re-record request до начала монтажа.

## 12. Publishing, delivery и promotion feedback

### 12.1. Полный publish contract

Packager создаёт не один `youtube_package.md`, а структурированный
`publish.json`, из которого детерминированно собираются:

- `metadata.md`: выбранный title, варианты, description, chapters;
- YouTube keyword tags — могут содержать пробелы;
- copy-ready hashtags — каждый token начинается с `#`, пробелов внутри нет;
- Telegram post;
- thumbnail/cover;
- `video.mp4` рядом с metadata/cover — exact reviewed final, hardlink без
  дублирования места там, где это поддерживает filesystem;
- attribution block, если он нужен;
- exact video path/hash/duration/resolution/loudness;
- upload checklist со всеми фактически пройденными gates.

### 12.2. `dl2 deliver`

Delivery завершается только когда присутствуют:

```text
video.mp4
metadata.md
thumbnail.png | cover.png
```

Для нескольких видео одной игры создаются отдельные вложенные папки по type и
date. Никаких поисков между `data/finalize` и `data/publish` перед загрузкой.

### 12.3. Promotion loop

Через 48 часов и 7 дней отдельная follow-up задача сопоставляет:

- YouTube retention/CTR/views;
- Telegram/Instagram/Reddit post events;
- Diary timeline;
- wishlist delta.

Production reflection не объявляет контент успешным по факту рендера. Эти
данные используются для следующего hook/thumbnail/content experiment.

## 13. Orchestration и наблюдаемость

### 13.1. Production state machine

Каждая стадия имеет owner, вход, выход, deadline и stop reason:

```text
brief → script_approved → vo_ready → assets_ready → shot_plan_ready
→ storyboard_passed → final_passed → delivered → metrics_pending
```

Нельзя перейти к final, если storyboard не прошёл mechanical gates. Нельзя
получить `SHIP`, если known-constraints regression отсутствует или stale.

### 13.2. Agent budget

- максимум 3 production agents;
- `fork_turns=none`/минимальный context package по умолчанию;
- каждый agent получает production id, manifest и нужные artifacts;
- reviewer не получает пользовательские corrections;
- orchestrator применяет corrections отдельным regression pass;
- нет polling каждые 30 секунд: completion events/state transitions;
- large images передаются как thumbnails/contact strips, full-resolution —
  только для flagged timestamps.

### 13.3. Time/token attribution

Каждый tool/agent event записывает:

```text
product_id
production_id
stage
agent_role
wall_ms
human_wait_ms
input_tokens
cached_input_tokens
output_tokens
artifact_paths
```

Dashboard показывает отдельно:

- wall production time;
- активное human time;
- render compute;
- agent/model latency;
- tokens всего и по stage;
- cached и non-cached;
- direct production, tooling fixes, review, packaging, reflection.

Telegram summary никогда не называет весь thread tree «токенами видео» без
этой атрибуции.

## 14. Матрица покрытия пользовательского фидбека

| Feedback | Причина | Изменение | Автоматическая приёмка |
|---|---|---|---|
| `trolley_devlog` и `trolley3d` про одну игру | format-first roots | ProductManifest + migration | оба production видны под `not_a_trolley_problem` |
| Нужны `devlogs/reels` и дата `2026_07_17` | loader связан с Python id | path-based production loader | exact folder prefix, import/check green |
| Видео, текст и картинка разбросаны | нет delivery stage | `dl2 deliver` | три обязательных файла в одной папке |
| Tags выданы как hashtags | нет metadata contract | separate tags/hashtags + regex | invalid hashtag блокирует delivery |
| Текст похож на нейросетевой | нет voice profile | script writer contract | style review + banned-pattern gate |
| Слишком много текста | нет duration budget до записи | words/time estimate | predicted duration ±10% |
| Нужно `я`, не `мы` | persona не формализована | solo voice profile | `VQ-SCRIPT-VOICE` |
| Текст нужно approve до записи | script lineage отсутствует | approved script hash | take не обрабатывается без approval |
| Пропал karaoke-суфлёр | recording UI regression | full/current/next teleprompter | browser regression test |
| Шум в начале | audio проверялся поздно | first-3s preflight | noise/click fixture блокируется |
| Дважды рассказано про 13 дней | script/shot duplication | semantic claim + VQ-DUP | duplicate claim/source fixture fails |
| Повтор старого трейлера/карточки | нет reuse policy | `reuse=forbidden/callback` | non-contiguous repeat blocks |
| Loading или старый кадр мелькает на переходе | boundaries не проверялись покадрово | VQ-BOUNDARY | ±0.25 s strip каждого cut без flash |
| Кадр мелькает | нет min readable duration | VQ-PACE/VQ-READ | short text fixture blocks |
| Steam-кадр слишком долгий | нет shot type budget | static max + intent | long still fixture blocks |
| Плохие пиксельные плашки | generated output не проверялся | native-size/glyph/frame checks | upscale/edge artifact warning/block |
| Псевдо-трамвай вместо настоящего | proof policy поздний | real-product source role | generated substitute blocks claim |
| 2D/3D трамвай нужно сравнить реально | отсутствовал planned proof shot | shot purpose + catalog | manifest требует оба real sources |
| Zoom ступенчатый | integer scaling | subpixel Ken Burns regression | 0 repeated adjacent frames |
| Повтор Canvas-анимации | source usage не отслеживался | pHash/src-offset duplicate check | повтор блокируется |
| Canvas был старым vertical reel | нет orientation/freshness | VQ-SOURCE + captured_at | portrait full-bleed landscape blocks |
| Canvas надо снять качественно для PC | capture request не профилирован | landscape capture profile | ≥1920×1080 native capture |
| Tofu в `до 400` | glyph check не охватывал текст | VQ-GLYPH all overlays | missing glyph blocks render |
| Нужен scroll Canvas, а не один ref | purpose не включал visual behavior | shot motion requirement | reference-context shot требует scroll |
| Tools shots слишком короткие | pacing не связан с narration | shot duration from VO range | min duration pass |
| Большая пустая область внизу | montage occupancy не проверялся | VQ-FRAME | occupancy threshold passes |
| Diary нужны реальные feed/chart | proof assets не закреплены | source role + required shots | manifest содержит оба captures |
| Promotion/marketing важны | publish не связан с Diary | promotion follow-up | 48h/7d events attached |
| Видео делает агент, направление выбирает автор | тезис мог исказиться | locked narrative facts | script regression preserves wording |
| Долго и много агентов | full-history forks/polling | 3-role compact contexts | agent/token/time budgets pass |
| Токены неверно отнесены к видео | нет stage attribution | product/production telemetry | report splits production/tooling/review |
| Нужна рефлексия после выпуска | reflection была ручным хвостом | automatic post-run report | report saved with exact artifact hash |

## 15. Итоговый порядок приоритетов

1. **Сначала migration foundation и output isolation.** Иначе новый autopilot
   закрепит неправильную структуру двух проектов.
2. **Затем script/teleprompter и Shot/Source Contract.** Именно здесь рождаются
   повторы, старые кадры и неверная длительность.
3. **После этого mechanical gates/autofix и delivery.** Проверки должны
   блокировать ошибку до preview.
4. **Только затем UI autopilot.** UI поверх слабого контракта ускорит выпуск
   плохих роликов.
5. **Финал — reel + devlog clean-room run менее чем за час каждый.**

Следующая инженерная задача должна начинаться с Wave 0–1, а не с Devlog 02.
