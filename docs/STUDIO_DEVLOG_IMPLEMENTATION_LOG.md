# Studio devlog reliability — журнал реализации и критики

## Milestone A — Trusted polished slice

### A1 — Capture contract and mandatory ingest gate

**Статус:** core ingest implemented; independent game-state proof remains  
**Дата:** 2026-07-24

#### Реализовано

- versioned `CaptureRequestSpecV2` и `CaptureBatchV2`;
- gameplay принимает только `capture_method=realtime_window`;
- gameplay request требует:
  state/build, 1x simulation, continuous take, clean UI, минимум 5 секунд
  head/tail handles;
- versioned result требует artifact SHA и hash-bound recorder metadata;
- ingest сверяет request, result и recorder sidecar;
- проверяются:
  method, role, state, build, simulation rate, continuous, clean UI,
  client-area-only, cursor exclusion, artifact path/SHA, metadata SHA,
  native resolution, FPS, orientation, duration, handles и client rect;
- каталог записывается только после полного pass;
- receipt v2 сохраняет exact validated facts;
- existing frame analyzer блокирует freeze/stepped cadence на content-window,
  не считая head/tail handles дефектом;
- failed result не обязан изобретать artifact;
- v2 требует ровно один result на каждый request;
- recorder sidecar расширен structured runtime fields;
- recorder сам резолвит executable по PID, хэширует его и блокирует take при
  несовпадении с `exe-sha256:<hash>`;
- v1 сохранён для compatibility.

#### Проверка

- targeted capture/registry: `23 passed`;
- real-FFmpeg capture fixture: pass;
- full engine gate: `805 passed, 3 skipped`;
- Studio web build: pass;
- `dl2 verify --changed`: pass.

#### Критика инкремента

1. `build_id` теперь независимо связан с executable SHA. `state_id`,
   `simulation_rate` и `clean_ui` пока остаются структурированными
   утверждениями capture runner, а не независимым proof от игры. Это лучше
   свободного `note`, но ещё не достаточная защита от неверно подготовленного
   state.
2. v1 по-прежнему технически ingestable. До появления registry/final gate он
   не должен считаться approved.
3. Capture runner не имеет live encoder-health/dropped-frame telemetry.

#### Решение

- не объявлять A1 полностью завершённым;
- безопасно продолжить A2, потому что asset identity не зависит от game-side
  proof;
- до Milestone A exit добавить:
  game-owned state proof и live capture-health telemetry.

### A2 — Minimal approved asset identity

**Статус:** core registry and render-gate binding implemented; Studio UI/migration remains  
**Дата:** 2026-07-24

#### Реализовано

- `data/assets/registry.json`;
- stable id `capture:<request_id>`;
- lifecycle `validated → approved`;
- revision увеличивается при замене artifact;
- approval привязан одновременно к:
  - exact artifact SHA;
  - canonical semantic validation fingerprint;
- перелabel того же MP4 как другого state/build снимает approval;
- изменение файла после approval определяется как stale;
- v2 ingest автоматически регистрирует только полностью validated capture;
- CLI:
  `dl2 asset-approve <edit> <asset_id> --sha <exact_sha>`.
- `VideoShot`/`Scene` могут переносить `asset_id` и `editorial_role` в IR;
- `VQ-ASSET-ID` блокирует:
  - gameplay без asset binding;
  - unknown/unapproved/stale asset;
  - role mismatch;
  - raw `src`, не совпадающий с approved registry path.
- регистрация нескольких captures публикуется одной атомарной записью:
  ошибка любого элемента не оставляет частично обновлённый registry.

#### Проверка

- geometry-adjacent capture/registry/compile/check suite: `67 passed`;
- полный engine gate: `809 passed, 3 skipped`;
- Studio web build: pass.
- `dl2 verify --changed`: pass.

#### Критика инкремента

1. Старые `VideoShot` и `Scene` без `editorial_role` остаются compatibility
   path; их нельзя автоматически признать gameplay без migration metadata.
2. Approval доступен через CLI/service, но ещё не через Studio author
   checkpoint.
3. Полный lifecycle и search UI намеренно отложены; сейчас это минимальная
   identity-система, а не asset manager.

#### Решение

- добавить migration report для raw `data/footage/*`;
- добавить Studio author checkpoint;
- перейти к A3 geometry/boundary evidence.

### A3 — Deterministic geometry and centering evidence

**Статус:** core geometry contract implemented; focus proof and Studio inspector remain  
**Дата:** 2026-07-24

#### Реализовано

- `ImageShot`, `VideoShot` и `Scene` получили явные:
  - `fit=cover|contain`;
  - `anchor_x` / `anchor_y` в диапазоне `0..1`;
- `IRSegmentGeometry` хранит:
  source size, scaled size, crop/pad origin, crop/output bounds и anchor;
- центральный crop теперь задаётся явными integer coordinates, а не
  неявным default FFmpeg;
- разные geometry-contracts одного source больше не сливаются в один segment;
- render пересчитывает тот же IR-контракт под draft/delivery resolution,
  поэтому delivery-пиксели не протекают в 540p preview;
- `VQ-GEOMETRY` блокирует несогласованные source facts, fit и crop/pad;
- `dl2 preview` атомарно создаёт
  `data/review/geometry_report.json`;
- добавлен rule catalog entry `common/quality/VQ-GEOMETRY.md`;
- проверка `encoded frame == recorder client_rect` уже находилась в A1 ingest
  и остаётся обязательной.

#### Проверка

- geometry compile/render/check/preview targeted suite: `63 passed`;
- полный engine gate: `817 passed, 3 skipped`;
- Studio web build: pass;
- `dl2 verify --changed`: pass.

#### Критика инкремента

1. Математический центр теперь доказуем, но художественный центр объекта
   не доказуем без game-owned `focus_rect`/subject metadata.
2. Report существует как JSON, но Studio пока не рисует source/crop/focus
   frames поверх кадра.
3. `anchor` задаётся вручную. Он устраняет случайный implicit crop, но неверно
   выбранный anchor всё ещё является авторской ошибкой.
4. Geometry evidence относится к source transform; оно не проверяет резкие
   смены и restart на границах. Это следующий A4.

#### Решение

- не объявлять Wave 3 полностью закрытым до focus metadata и Studio inspector;
- core достаточно надёжен, чтобы начать A4 boundary contract;
- не использовать vision для поиска математического смещения: сначала
  `geometry_report.json`, затем visual review только субъекта и текста.

### A3b — Boundary intent and restart detection

**Статус:** pre-render boundary core implemented; post-render strips/density remain  
**Дата:** 2026-07-24

#### Реализовано

- `Chunk.transition_intent` с явными значениями:
  `continuous_same_take`, `motivated_cut`, `before_after`,
  `chapter_boundary`, `no_cut`;
- intent переносится в открывающий новый segment `IRSegment`;
- explicit intent не позволяет compiler молча слить заявленную границу;
- `VQ-BOUNDARY` блокирует:
  - gameplay boundary без intent;
  - `no_cut`, если boundary реально существует;
  - `continuous_same_take` между разными assets;
- `VQ-RESTART` блокирует:
  - discontinuous source offset для `continuous_same_take`;
  - rewind/restart уже использованного source без явного
    `motivated_cut|before_after|chapter_boundary`;
- `dl2 preview` атомарно создаёт
  `data/review/boundary_report.json` со всеми границами, offsets и restart facts;
- добавлен `common/quality/VQ-BOUNDARY.md`.

#### Проверка

- boundary compile/check/report/preview suite: `56 passed`;
- полный engine gate: `823 passed, 3 skipped`;
- Studio web build: pass;
- `dl2 verify --changed`: pass.

#### Критика инкремента

1. Intent доказывает осознанность cut, но не его художественное качество.
2. Пока нет post-render frame-distance/SSIM и boundary strips; это нужно,
   чтобы ловить encoder/render artifacts вокруг корректно объявленной границы.
3. Source-change density «один gameplay source на день или before/after»
   требует day/story metadata, которой ещё нет в IR.
4. Handle consumption пока валидируется на capture ingest, но ещё не
   сопоставляется с каждым used source window при монтаже.
5. JSON report и check используют один tolerance constant, однако дальнейшую
   классификацию boundaries лучше свести к одной общей analysis model.

#### Решение

- A3b core достаточно, чтобы предотвращать недекларированные restart и hard cut;
- следующим boundary slice сделать handle-window gate и post-render strips;
- не лечить найденный hard cut автоматическим fade: сначала исправить source
  continuity или объявить мотивированный переход.

### A4 — VO lead-in, room tone, post-roll, and markers

**Статус:** marker-driven trim and take-level verdict implemented; real-device UAT remains
**Дата:** 2026-07-24

#### Реализовано

- MediaRecorder по-прежнему стартует сразу по нажатию Record;
- UI теперь показывает отдельные фазы:
  - `3–2–1` countdown;
  - 2 секунды room tone;
  - `Read now`;
  - автоматический 1-second post-roll после Stop;
- повторный Stop во время post-roll заблокирован;
- karaoke начинает speech time только после полных 5 секунд lead-in;
- Studio создаёт `devlog.voice_take/v1` markers:
  countdown, room tone, speech start, stop request, post-roll end,
  completed lead-in/post-roll;
- upload API валидирует markers и сохраняет рядом с raw take
  `*.recording.json`;
- session take хранит metadata path;
- `devlog-record-media` skill синхронизирован с фактическим Studio protocol.
- `dl2 audio` и Studio process-take используют sidecar для guarded trim:
  - 250 ms материала до speech marker;
  - 100 ms guard до Stop marker, поэтому физический click кнопки не остаётся
    в retained VO;
  - обе границы выбранного WAV проверяются до cleanup;
- incomplete lead-in/post-roll теперь блокирует обработку с `re_record`, а не
  маскируется legacy fallback;
- legacy take без sidecar сохраняет старый cleanup-first путь и получает
  честный статус `unverified`;
- transient detector ловит не только full-scale single-sample impulse, но и
  короткий sub-full-scale click с парой резких фронтов;
- verdict содержит exact raw SHA-256, timestamp, фактическую selection geometry,
  head/tail QC и recommended action;
- PASS verdict публикуется только после успешной транскрипции; rejection
  сохраняется отдельным `*.rejected.json`;
- take card показывает `Clean`, `Unverified` или понятный `Re-record` reason.

#### Проверка

- Studio production TypeScript/Vite build: pass;
- browser-component state test:
  countdown → room tone → read → post-roll → metadata: pass;
- browser take-card quality badge tests: `2 passed`;
- targeted audio/API/CLI suite: `186 passed`;
- полный changed-path engine gate: `527 passed`;
- все Studio Web UI component tests: `11 passed`;
- `dl2 verify --changed`: pass.

#### Критика инкремента

1. Реальная проверка микрофона/браузера всё ещё нужна; unit test доказывает
   state machine и metadata, а не качество конкретного устройства.
2. 100 ms Stop guard опирается на точность browser marker; дополнительный
   head/tail QC блокирует найденный transient, но WebM/Opus device fixture ещё
   не заменяет real-device UAT.
3. Подробный старый Wave 6 всё ещё упоминает 2 s post-roll, тогда как
   утверждённый Milestone A и реализованный быстрый протокол используют 1 s.
   Перед дальнейшим редактированием плана это противоречие нужно удалить.

#### Решение

- A4 core принять после независимого re-review и commit;
- провести короткий real-device UAT при следующей фактической записи VO;
- перейти к A5 visible polish checkpoint.

### A5 — Reusable visual polish blocks

**Статус:** reusable core и real UAT готовы; интеграция блоков в новый edit остаётся отдельным checkpoint
**Дата:** 2026-07-24

#### Реализовано

- `dl2 gen-html --init --template` создаёт пять повторяемых HyperFrames-блоков:
  - `day-card`;
  - `before-after`;
  - `focus-callout`;
  - `cta-endcard`;
  - `explain-steps`;
- каждый блок поддерживает `landscape` и `vertical`, объявляет типизированные
  `data-composition-variables` и строит paused GSAP timeline без wall-clock
  анимаций;
- `dl2 gen-html --variables-file` передаёт фактические тексты, изображения и
  координаты в рендер без ручной правки HTML;
- variables-файл требует явный output, проверяется через HyperFrames
  `--strict-variables`, а release-placeholder и пропущенные обязательные поля
  блокируют рендер;
- proof-блоки требуют evidence v2 и больше не доверяют ручным флагам:
  - source обязан быть exact approved revision из `data/assets/registry.json`;
    evidence фиксирует `registry_revision` и approved `validation_sha256`,
    поэтому смена state/build при тех же медиабайтах инвалидирует proof;
  - `catalog.json` используется только для роли `real_product`, а не как approval;
  - evidence ссылается по path/SHA и `beat_id + segment_index` на A3
    `geometry_report.json`;
  - каждый derived image содержит source asset id/SHA, timestamp, crop и output;
    Studio требует точного совпадения crop/output с полным A3 transform,
    повторяет FFmpeg-рецепт и сверяет полученный SHA до запуска npx;
- production root передаётся явно через `--production-root` или находится по
  ближайшему ancestor с registry; фиксированной глубины директорий больше нет;
- каждый успешный render создаёт `*.mp4.render.json` с SHA-256 artifact,
  `index.html`, variables и evidence;
- visual language использует палитру проекта: near-black, paper white,
  trolley red, ink и muted grey; generic glass/neon/dashboard UI не используется;
- Before/After показывает две полные карточки одновременно, без центрального
  hybrid-cut; обе производные берутся из разных timestamp одного approved
  continuous source с одинаковыми A3 crop/output;
- Focus Callout требует явные `focus_x/focus_y`, использует контрастную
  explanation-плашку и не выдаёт authorial focus за game-owned proof;
- Explain Steps превращает длинную заметку в последовательность
  `графит → бумажный слой → тени → контраст`;
- CTA принимает только явные release values, проверяет wishlist-семантику,
  canonical Steam app URL и блокирует фразу «Следующая остановка — Steam»;
- реальный Day 4 Before/After получен из одного зарегистрированного source frame:
  одна камера, одно состояние, без grayscale/contrast-фильтра и без debug overlay.

#### Проверка

- service/CLI tests: `68 passed`;
- HyperFrames `check --strict --at-transitions` для всех пяти блоков:
  `0 lint/runtime/layout errors`, `0 warnings`;
- contrast gate: `56 passed samples`;
- пять реальных renders: `1920x1080`, `30 fps`, `3.8–4.8 s`;
- все пять manifests имеют `quality: final`;
- Day 4 comparison SHA-256:
  `2E4C9D500B27F6902507759DCB3E7B10AA337986B952F1E8504DA59505661E8E`;
- contact sheet:
  `not_a_trolley_problem/devlogs/2026_07_22_devlog_01/data/review/a5_visual_blocks_final_sheet.jpg`.

#### Ограничения и следующий шаг

1. Это пять минимальных блоков, а не весь Wave 8 catalog; Annotated Zoom и
   Counter остаются последующими инкрементами.
2. CTA semantics проверяется локально, но canonical Steam facts ещё нужно
   перенести из project variables в единый `product.toml` contract.
3. Реальный artifact создан как UAT и не коммитится; в git входят engine,
   CLI, тесты и этот evidence log.
4. Блоки намеренно не встроены в уже утверждённый devlog: это изменило бы его
   структуру. Первый wiring checkpoint должен выполняться на следующем edit с
   `dl2 preview`, boundary strips и review полного контекста.
