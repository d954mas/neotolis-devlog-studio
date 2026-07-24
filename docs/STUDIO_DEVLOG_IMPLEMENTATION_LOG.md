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

**Статус:** recording state/markers implemented; take-level transient verdict remains  
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

#### Проверка

- Studio production TypeScript/Vite build: pass;
- browser-component state test:
  countdown → room tone → read → post-roll → metadata: pass;
- take upload/metadata API: `6 passed`;
- полный engine gate: `825 passed, 3 skipped`;
- `dl2 verify --changed`: pass.

#### Критика инкремента

1. Markers больше не требуют угадывать безопасные области, но `dl2 audio`
   пока не использует sidecar для guarded marker-based trim.
2. Existing PCM click/clipping detector существует в
   `script_preflight.check_wav_first_3s`, но ещё не публикует take-level
   verdict после каждого Studio upload/process.
3. Emergency stop при смене beat/tab сохраняет take без полного post-roll;
   metadata ставит `post_roll_completed=false`, а take card показывает
   degraded warning, но автоматическое решение recapture/repair ещё отсутствует.
4. Реальная проверка микрофона/браузера всё ещё нужна; unit test доказывает
   state machine и metadata, а не качество конкретного устройства.

#### Решение

- core A4 не объявлять полностью закрытым;
- следующим VO slice связать markers с guarded trim и transient verdict;
- incomplete lead-in/post-roll не скрывать: показывать как recapture/repair
  warning в take card.
