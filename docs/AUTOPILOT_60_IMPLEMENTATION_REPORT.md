# Studio Autopilot 60 — итоговый implementation-аудит

Дата аудита: 2026-07-18

## Speed follow-up — 2026-07-18

Три изменения из cross-run reflection реализованы:

1. До storyboard вертикальный production блокируется без структурного
   `story_contract.json`; viewer-visible HyperFrames text проверяется на
   внутренние `REEL/PART/VERSION/CUT ##` только для реально используемых
   motion-assets.
2. `dl2 autopilot-run` ведёт один resumable `run_id` через prepare → author
   checkpoint → final → exact review → publish/delivery. Failed run продолжает
   упавшую фазу, не возвращаясь к storyboard. `--human-minutes` записывает
   активное авторское время в run-scoped telemetry.
3. Storyboard и final автоматически получают exact-hash
   `data/review/review_pack.json` и компактный `review_pack_sheet.jpg` — не
   более 16 thumbnails шириной 320 px плюс timing/source/story/preflight facts.

Exact finals двух текущих reels прошли обновлённый preflight с 0 errors.
Review packs содержат по 15 кадров; JSON занимает 5–6 КБ, sheets — 272–364 КБ.
Полный verification: UI production build + **734 passed**, одно внешнее
Starlette/httpx deprecation warning.

Это реализует ускоряющий pipeline, но не заменяет следующий clean-room замер:
сертификация SLA всё ещё требует один новый последовательный reel и затем один
2–4-минутный devlog без engine changes во время прогона.

## Результат

Инженерная часть плана реализована: единый product root, безопасная миграция,
контракты script/VO/source/shot, mechanical gates, Studio checkpoint,
product overview, batch capture contract, exact-hash review, delivery,
publishing evidence и stage telemetry работают как один v2 pipeline.

Два новых вертикальных рилса исправлены после авторского просмотра и готовы к
публикации. В обоих удалены служебные надписи `REEL 1/2`. Reel 02 больше не
выглядит продолжением: первая фраза и первый экран самостоятельно объясняют,
что автор переделывает свою игру из 2D в 3D.

При этом маркетинговое имя **Autopilot 60 пока не сертифицировано по разделу 8
плана**. Код готов, но контрольный прогон не выполнил все acceptance-условия:
первые storyboard заняли 21,3–21,5 минуты вместо 15; два рилса производились
параллельно; не было последовательной пары `reel → 2–4-минутный devlog`; после
первого handoff понадобилась авторская коррекция. Поэтому Studio не должна
выдавать ложное утверждение, что SLA уже доказан.

## Что реализовано

### Product и миграция

- Канонический root: `not_a_trolley_problem` с отдельными `devlogs/`, `reels/`,
  `shared/` и `delivery/`.
- Production id имеют формат `YYYY_MM_DD_<kind>_<number>`.
- `ProductManifest`, `ProductionManifest`, path-based loader и production-
  scoped `review/finalize/publish/delivery`.
- Универсальный `dl2 migrate-product`: dry-run, explicit plan, apply,
  collision/hash report, scoped rollback и повторный idempotent apply.
- `trolley_devlog` и `trolley3d` скопированы без удаления исходников;
  semantic IR parity и старые final SHA-256 сохранены.
- Shared-asset dedup: 13 exact-hash groups / 32 aliases сведены к hardlinks.
- Повторный migration apply: `0 copied / 503 unchanged`.
- Studio product overview показывает все productions одной игры на одной
  странице и отмечает текущую production.

### Сценарий, голос и запись

- Creator profile: первое лицо, solo-разработчик, запрещённые клише,
  pronunciation и CTA defaults.
- Script lint, predicted duration, approval hash и lineage
  `approved script → take → words`.
- Studio karaoke: весь текст, current/next phrase и подсветка текущего слова.
- Запись блокируется до script approval.
- VO preflight: первые три секунды, шум/click, proper-name token scan.

### Shot/source contract и capture

- Asset catalog и shot manifest с provenance, source role, orientation,
  freshness, purpose, reuse policy и quality facts.
- Gates VQ-DUP, VQ-PACE, VQ-READ, VQ-SOURCE, VQ-GLYPH, VQ-FRAME,
  VQ-AUDIO-START, VQ-BOUNDARY и VQ-MOTION-SMOOTH.
- `dl2 capture-batch <edit> --prepare` собирает все недостающие реальные кадры
  в один JSON-запрос внешнему capture-agent.
- `--ingest` проверяет production id, target, SHA-256, размеры и длительность,
  затем обновляет catalog. Встроенного второго recorder в Studio нет.
- Исправлен long-form contact sheet: прежний FFmpeg `tile` сбрасывал накопленные
  кадры при смене color metadata между битами и оставлял большую часть листа
  чёрной. Теперь кадры сначала извлекаются независимо, затем детерминированно
  собираются Pillow; листы обоих рилсов и девлога перегенерированы полностью.

### Autopilot, review, telemetry и delivery

- Один Studio checkpoint: `VO → source → duration/flags/fix`, approve-all и
  structured requests. Смысл и VO safe-fix не меняет.
- Канонический skill `.agents/skills/dl-make-video`: state machine, максимум
  три узкие роли, blind review, known-constraints regression и reflection.
- Append-only telemetry по stage и agent role; отдельная команда
  `dl2 record-stage` принимает wall/human wait/token counters и artifacts.
- Автоматически пишутся deterministic timings inventory/capture/preflight/
  storyboard/final/publish/evidence/delivery. Нулевые AI token-поля не
  интерпретируются как «агент не потратил токены».
- `dl2 publish-evidence` блокирует пакет при stale/missing exact preflight,
  review, hash или невалидных hashtags; после успешных gates материализует
  exact `data/publish/video.mp4` рядом с metadata/cover (hardlink либо
  SHA-проверенная fallback-копия).
- `dl2 deliver` идемпотентно собирает отдельную папку с `video.mp4`,
  `metadata.md`, `cover.png`, publish JSON, Telegram copy и license evidence.

## Два готовых рилса

| Production | Длительность | Exact delivery SHA-256 | Review |
|---|---:|---|---|
| `2026_07_18_reel_01` | 17,500 s | `4cadee44698df6fe7deb7c54ebe04d0da6d1a2dfb602e9964f32fe54e872e6ae` | `ship` |
| `2026_07_18_reel_02` | 17,533 s | `63fbf382d39673bf7fabcbbf453c3a84570639f481c1cc75ffd5adbab5eb16a1` | `ship`, standalone |

Оба: 1080×1920, loudnorm около −14 LUFS, exact final preflight с 0 errors.
Оставшиеся notices не блокируют выпуск: начало речи после тишины; у Reel 02
две намеренно тёмные карточки с negative space.

После последнего пользовательского фидбека correction→final занял 31:29,6
для Reel 01 и 31:44,2 для Reel 02. Это elapsed revision wall, а не чистое
production time: одновременно шла инженерная работа над Studio. Точное human
time и model-token attribution этого revision задним числом неизвестны.

Новые reflection-отчёты сохранены рядом с каждым exact final и предлагают
три следующих gate: standalone-story contract, запрет служебного `REEL ##`
в кадре и run-scoped telemetry с первого события.

## Проверки

- `dl2 verify --changed`: UI production build и полный Python suite прошли.
- Python: **727 passed**, без skipped; единственное предупреждение — deprecation
  внутри FastAPI/Starlette TestClient dependency.
- HyperFrames lint обоих master assets: 0 errors / 0 warnings.
- `dl2 check` обоих рилсов: 0 errors / 0 warnings.
- Exact final preflight: 0 errors у обоих.
- Blind review exact artifacts: `ship` у обоих, hashes совпадают с delivery.
- Delivery повторён: `0 copied / 4 unchanged` у каждого.

## Acceptance matrix плана

| Условие раздела 8 | Статус | Доказательство |
|---|---|---|
| ≤60 минут на ролик | частично | initial exact finals 42:24/42:39; revision 31:30/31:44, но runs шли параллельно с tooling |
| ≤20 минут автора | не измерено | ночью автор не участвовал, но активное human time до ночи не атрибутировано |
| first storyboard ≤15 минут | **fail** | 21,3–21,5 минуты |
| ≤1 пакетного review | **fail для первого handoff** | после просмотра потребовалась коррекция обоих labels и standalone-истории Reel 02 |
| 0 deterministic corrections после handoff | **fail для первого handoff** | служебные labels и framing второй истории обнаружил автор |
| ≤3 AI roles, compact context | pass для production contract | ограничение встроено в skill; reflection/reviewer запускались узко |
| token budget | не измерено per production | telemetry включена после начала run; ретроатрибуция была бы выдумкой |
| exact-hash regression review | pass | свежий review обоих delivery hashes |
| полная delivery-папка | pass | отдельная папка для каждого рилса |
| последовательные reel + devlog | **не выполнено** | текущий тест — два параллельных reels |

### Реальный regression-run landscape devlog

Мигрированный `2026_07_17_devlog_01` (2:24,8 draft / 2:43 delivery) прогнан
из product root без правки VO:

- `dl2 check`: 0 errors / 0 warnings;
- `dl2 preview`: все 7 битов, MP4, 16-cell contact sheet и 8 keyframes за
  39,2 секунды;
- старый delivery SHA-256 совпадает с исходником `trolley_devlog`:
  `c39d37e6f60d0a5198e01956329c814ff1be0881cc09d79fe7cb7b0c1a6cf0b3`;
- новый `dl2 preflight` корректно остановил legacy edit: отсутствует
  hash-bound script approval, а `b07` содержит 20 слов при лимите 18;
- дополнительно сохранены 14 warnings по audio-start, occupancy и отсутствию
  cut ledger.

Это доказывает работоспособность landscape path и миграции, но намеренно
считается failed clean-room metric: задним числом создавать approval или менять
уже записанный авторский VO нельзя.

Отдельная рефлексия regression-run:
`data/review/reflections/2026-07-18T03-26-59_devlog_01_regression.md`.

## Что требует следующего реального цикла

1. После нового script approval и записи автора последовательно прогнать один
   новый reel, затем один landscape devlog длительностью 2–4 минуты, не меняя
   engine во время замера. Legacy devlog path уже проверен и сохранил blockers.
2. Начать telemetry до первого production event и передавать реальные token
   counters каждого model/agent call.
3. После фактической публикации записать platform ids/timestamps; только тогда
   активировать 48h/7d Diary/retention/CTR/wishlist follow-up.

Это не блокирует публикацию двух текущих рилсов. Это блокирует только честную
сертификацию универсального SLA `Autopilot 60`.
