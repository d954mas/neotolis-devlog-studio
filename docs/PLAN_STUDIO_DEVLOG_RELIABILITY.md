# Studio v2: план надёжного и качественного производства девлогов

**Статус:** approved for incremental execution; Milestone A started  
**Основание:** Devlog 1, пользовательская оценка 3/10, подробная рефлексия от 2026-07-24  
**Связанные документы:** `ARCHITECTURE_V2.md`, `PLAN_STUDIO_V2.md`,
`PLAN_STUDIO_AUTOPILOT_60.md`,
`REVIEW_STUDIO_DEVLOG_RELIABILITY_PLAN.md`

## 0. Решение после критического и конкурентного ревью

Waves 0–9 ниже остаются **полным reliability backlog**, но больше не являются
порядком реализации. Последовательная реализация Waves откладывала первый
видимый выигрыш до Wave 8 и скрыто занимала 14.5–25 инженерных дней.

Работа ведётся четырьмя вертикальными milestones:

| Milestone | Срок | Рабочий результат |
|---|---:|---|
| A. Trusted polished slice | 4–6 дней | Один реальный день проходит `capture → ingest → approved asset → проверенный beat → аккуратный preview` |
| B. Fast semantic rough cut | 4–6 дней | Сценарий/транскрипт связываются с claims, shot purpose и approved visuals |
| C. Opinionated polish | 5–7 дней | Brand preset, focus motion, captions, audio cleanup и повторяемая рекламная подача |
| D. Release learning | 2–3 дня | Retention/CTR и реакции аудитории возвращаются в beat/claim planning |

### Milestone A — обязательный порядок тонких срезов

1. **A1 — trusted capture ingest**
   - regression fixtures;
   - `CaptureRequest/Result v2`;
   - gameplay role принимает только real-time capture;
   - state/build/method/resolution/cadence/handles проверяются до ingest.
2. **A2 — minimal approved asset identity**
   - hash-bound sidecar вместо полного registry UI;
   - `asset_id`, state, build, role, method, approval и focus;
   - replacement под тем же path делает approval stale.
3. **A3 — geometry and boundary evidence**
   - resolved geometry в IR;
   - source offsets, restart и handle checks;
   - compact geometry/boundary report.
4. **A4 — fast clean VO**
   - raw recording начинается до `3–2–1`;
   - countdown является общим трёхсекундным lead-in;
   - одна секунда post-roll;
   - markers и transient verdict управляют безопасным trim.
5. **A5 — visible polish checkpoint**
   - Day Card;
   - Before/After;
   - Focus Callout / Annotated Zoom;
   - Canonical CTA Endcard;
   - один реальный beat проходит полный slice и уже выглядит релизно.

После каждого среза обязательны:

1. узкие unit/integration tests;
2. релевантный real-FFmpeg smoke;
3. `dl2 verify --changed` для engine-work;
4. simplicity review;
5. критическое ревью против исходного пользовательского фидбека;
6. только затем следующий срез.

### Метрики, добавленные ревью

- `time_to_first_good_draft`;
- `asset_search_time_per_claim`;
- `rough_cut_acceptance_ratio`;
- `manual_actions_per_day`;
- `recapture_decision_latency`;
- `key_claims_with_visual_proof`;
- число human mechanical corrections;
- final render count и storage churn.

### Продуктовая граница

Studio — не новый Premiere/Resolve. Это локальный **game-aware devlog
compiler/control plane**:

`game state truth + semantic asset selection + script-to-IR + deterministic QA + opinionated polish`.

Полный timeline editor, собственные Color/Fusion/Fairlight-аналоги, cloud
collaboration и generative clip extension в этот план не входят.

## 1. Зачем нужен этот план

Devlog 1 в итоге удалось довести до приемлемого состояния, но пользователь
вручную нашёл дефекты, которые Studio должна была блокировать до просмотра:

- нецентрированные сцены;
- резкие и ненужные смены gameplay;
- окончание source и повторный запуск с начала;
- старый и новый gameplay в одной последовательности;
- ускоренный gameplay;
- testbed/debug-визуал вместо чистой игры;
- покадровый DevAPI capture вместо обычной записи;
- черновые подписи и внутренние заметки;
- щелчки и артефакты в начале/на стыках VO;
- неправильный CTA и слабая финальная сцена;
- большое количество дорогих render/review итераций.

Это не набор независимых монтажных ошибок. Это один системный дефект:

> Studio разрешала продолжать производство с неподтверждённым source, а затем
> пыталась найти измеримые ошибки зрением после рендера.

Цель плана — изменить направление потока:

`контракт → проверенный asset → проверенный монтаж → creative review → final`

вместо:

`сомнительный файл → монтаж → render → просмотр → пользователь находит дефект`.

## 2. Измеренный baseline

По рефлексии Devlog 1:

| Показатель | Факт | Целевое значение |
|---|---:|---:|
| Wall time исправлений | 4 ч 37 мин | ≤2–3 ч на полный devlog |
| Пользовательских коррекций до принятия | 20 | ≤1 mechanical correction |
| Final renders | 27 | 1, максимум 2 |
| Preflight runs | 3 | перед каждым storyboard/final |
| Image previews | 97 | компактный machine pack + 1 visual review |
| `data/finalize` | 334 MP4 + 333 WAV, ~12.4 GB | текущий + last-known-good + delivery |
| Центрирование Day 4–7 | 1 ч 17 мин ручной диагностики | автоматический geometry report |
| Speed/recapture | 48 мин | немедленный `recapture` verdict |
| Поздние финальные дефекты | 49 мин | 0 mechanical defects после final gate |

Рендер не был главным bottleneck. Дорого стоило позднее обнаружение неправильных
входов и повторная сборка.

## 2.1. Текущее состояние реализации

| Возможность | Статус сейчас | Что остаётся |
|---|---|---|
| FFprobe catalog | есть | semantic identity и approval |
| Capture batch v1 | есть | method/state/build/handles и core audit |
| External real-time recorder | добавлен в `devlog-record-media` | production integration и positive UAT |
| Gameplay capture validator | добавлен в skill | вызывать из core ingest |
| Debug capture scenes | game-side contract уже есть, создан routing skill | строгая role enforcement в ingest |
| Centered FFmpeg cover crop | есть | explicit IR geometry/focus proof |
| Freeze/cadence/boundary analysis | частично есть в `render_preflight.py` | source identity, offsets, handles, intent |
| Compact review pack | есть | единый geometry/source/boundary report |
| HyperFrames visible-text preflight | частично есть | public-copy manifest и rendered OCR fallback |
| Studio VO recording | A4 core: immediate record, countdown, room tone, post-roll, markers, guarded trim, verdict | real-device WebM/Opus UAT |
| Exact-hash review | есть | обязательная known-constraints regression |
| Iteration cap в инструкциях | есть | runtime enforcement |
| Visual templates | HyperFrames bridge есть | curated commercial-quality blocks и grammar |

Критично: отдельный скилл ещё не является hard gate. Пока
`services/capture_batch.py` сам не отклоняет неправильный result, старый класс
ошибки остаётся технически возможным.

## 3. Принципы целевой Studio

### 3.1. Код проверяет факты, зрение — качество

До visual review код обязан определить:

- точный asset, build и visual state;
- capture method;
- разрешение, FPS, cadence и simulation rate;
- чистый это capture или debug/testbed;
- head/tail handles;
- source offsets и достижение конца файла;
- restart, freeze и duplicate frames;
- crop/fit/anchor arithmetic;
- declared transitions и фактические boundaries;
- public text против internal text;
- VO silence, clipping и transients;
- SHA reviewed artifact и stale review.

Зрение используется только после pass для:

- композиции и субъективного визуального центра;
- выразительности и иерархии;
- читаемости и уместности текста;
- визуальной энергии;
- стилистической цельности;
- рекламного/хитового качества подачи.

### 3.2. Capture остаётся внешней системой

Решение `ARCHITECTURE_V2.md` сохраняется:

- Studio не превращается в OBS и не управляет игровым циклом;
- DevAPI подготавливает state;
- внешний capture runner записывает gameplay;
- Studio владеет capture request, contract validation, ingest, registry,
  approval и отображением результата.

То есть Studio не записывает gameplay сама, но не принимает gameplay без
машинных доказательств.

### 3.3. Путь не является идентичностью asset

`data/footage/recentered/labeled/day7_gameplay_reprise.mp4` — это путь, а не
доказательство содержания.

Монтаж должен ссылаться на stable `asset_id`. Путь, hash и derivation являются
свойствами конкретной ревизии asset.

### 3.4. Не ремонтировать неправильный capture

Ошибки `wrong state`, `wrong speed`, `debug`, `frame-stepped capture`,
`insufficient handles`, `native resolution too low` получают verdict
`recapture`.

Ретайм, интерполяция, upscale или ручной crop не должны превращать
неподходящий source в approved gameplay.

### 3.5. Final — состояние, а не название файла

Команда `final` доступна только после:

1. approved sources;
2. compile/IR pass;
3. boundary pack pass;
4. storyboard pass;
5. visual review;
6. known-constraints regression.

## 4. Карта пользовательского фидбека

| Пользовательский симптом | Корневая причина | Будущий владелец |
|---|---|---|
| Day 3–7 не по центру | capture включал editor strip; crop не был контрактом | asset registry + geometry gate |
| Резкие переходы 22–23, 55, Day 7 15 s | source менялся без `transition_intent` | IR boundary gate |
| Gameplay закончился и запустился заново | короткий take, нет handles, offset reset | continuity gate |
| Слишком много смен gameplay | shot plan не ограничивал source churn | shot grammar + storyboard gate |
| Старый gameplay сменяет новый | нет build/state identity и approved selector | asset registry + compile |
| Day 5 ускорен | speed не измерялся; source пытались ретаймить | capture/cadence gate |
| DevAPI кадры вместо записи | capture method отсутствовал в request/result | capture contract v2 |
| Test/debug visual Day 5–7 и outro | debug status определялся по имени/взгляду | capture metadata + text/debug gate |
| Черновые тексты, `01→10` | public и internal copy не разделены | public-copy manifest |
| Щелчки и артефакт на 74–75 s | нет pre/post-roll и transient gate | VO recording state machine |
| Day 5 не продолжает Day 4 | shot plan не закреплял входной/выходной state | inter-beat continuity contract |
| Плохое качество gameplay | ingest проверял слишком мягкий upscale cap | native-resolution gate |
| Сцена стоит | короткий/замороженный source и поздний motion review | capture handles + motion range |
| Неправильный CTA | product facts не являлись источником public copy | canonical claims/CTA |
| Видео выглядит черновиком | нет visual-purpose grammar и polish pass | visual toolkit + creative review |

## 5. Целевой workflow

```text
Brief + approved script
        ↓
Shot expectations per day/claim
        ↓
Capture requests v2
        ↓
External real-time capture / explicit debug presentation
        ↓
Capture validation + semantic asset registration
        ↓
Author approves one take per purpose
        ↓
Compile by asset_id → IR with source geometry and boundaries
        ↓
Machine boundary pack
        ↓
Targeted beat drafts
        ↓
Creative visual review
        ↓
One full storyboard preview
        ↓
Known-constraints regression
        ↓
One final + exact-hash review + delivery
```

Для каждого дня по умолчанию:

- один continuous gameplay take; либо
- один `before` и один `after`;
- дополнительные sources разрешаются только с declared purpose.

## 6. Целевые контракты данных

### 6.1. CaptureRequest v2

`CaptureRequestSpec` должен стать строгим описанием результата:

```json
{
  "id": "day5_station_realtime",
  "editorial_role": "gameplay",
  "capture_method": "realtime_window",
  "state_id": "day5.station.new_visual",
  "build_id": "exe-sha256:<running-executable-sha256>",
  "orientation": "landscape",
  "min_width": 1920,
  "min_height": 1080,
  "min_fps": 30,
  "simulation_rate": 1.0,
  "content_seconds": 27,
  "head_handle_seconds": 5,
  "tail_handle_seconds": 5,
  "continuous": true,
  "clean_ui": true,
  "action_id": "station_queue_and_tram_pass",
  "focus_rect_source": "game_layout",
  "presentation": {
    "fit": "cover",
    "output_width": 1920,
    "output_height": 1080,
    "focus_center_required": true
  }
}
```

Free-form `instructions` остаются дополнительным описанием, но не заменяют
структурные поля.

### 6.2. CaptureResult v2

Result обязан доказать:

- exact request id;
- capture method;
- state/build identity;
- artifact SHA;
- recorder metadata SHA;
- client rectangle;
- cursor/debug status;
- actual duration/FPS;
- actual handles;
- start/end timestamps;
- validator report path/SHA;
- verdict.

`note` не является доказательством.

### 6.3. AssetRecord v2

Минимальные поля semantic registry:

```text
asset_id
artifact_path
artifact_sha256
revision
status: candidate | approved | rejected | archived
kind / source_role / editorial_role
day / build_id / state_id / visual_state
capture_method / simulation_rate / clean_ui
width / height / fps / duration / cadence
head_handle / tail_handle
focus_rect / framing / intended_for
parent_asset_id / transform_recipe
quality_flags
validation_report_sha256
approved_at / approved_by
```

Каталог больше не выводит semantic facts из имени файла. Filename heuristics
могут дать initial guess, но такой asset остаётся `candidate/unverified`.

### 6.4. ShotExpectation

Каждый shot связывает смысл и техническое ожидание:

```text
shot_id
beat_id / day / claim_id
purpose: proof | context | compare | explain | emphasis | transition | cta
expected_asset_id или semantic selector
expected_state_id
allowed_roles
source_window
transition_intent
presentation
public_copy_ids
motion_requirement
```

### 6.5. BoundaryRecord

Compiler должен выдавать для каждой границы:

```text
timeline_time
left/right shot_id
left/right asset_id + SHA
left/right source offset
remaining head/tail handles
state change
fit/crop/focus transform
declared transition_intent
actual transition kind/duration
frame-distance/SSIM facts
verdict
```

## 7. План реализации

## Wave 0 — Regression corpus и измеримый baseline

**Приоритет:** P0  
**Effort:** 0.5–1 день  
**Зависимости:** нет

### Работы

1. Зафиксировать семь классов fixtures:
   - source с editor strip;
   - короткий source с restart;
   - stepped/accelerated capture;
   - debug/testbed overlay;
   - old/new state mismatch;
   - hard unexplained cut;
   - VO click без leading quiet.
2. Сохранить текущий Day 5 audit как negative fixture.
3. Создать synthetic positive fixtures, чтобы gates имели pass-контроль.
4. Зафиксировать baseline telemetry:
   render count, preflight count, wall time, human time, storage churn.
5. Добавить failure taxonomy:
   `recapture`, `replace_asset`, `fix_timeline`, `fix_copy`, `creative_review`.

### Acceptance

- каждый пользовательский mechanical defect воспроизводится отдельным тестом;
- тест падает до реализации owning gate;
- fixture не зависит от agent vision.

## Wave 1 — Capture contract v2 и обязательный ingest gate

**Приоритет:** P0  
**Effort:** 1–2 дня  
**Зависимости:** Wave 0

### Owning files

- `services/capture_batch.py`;
- CLI `capture-batch`;
- `devlog-record-media`;
- tests `test_services_capture_batch.py`.

### Работы

1. Добавить versioned `CaptureRequestSpecV2` и `CaptureResultSpecV2`.
2. Для `editorial_role=gameplay` разрешить только `realtime_window`.
3. Для `deterministic_devapi` разрешить только `debug_proof/presentation`.
4. Проверять exact state/build match.
5. Требовать 5 s head/tail handles.
6. Требовать native target resolution без post-upscale.
7. Запускать cadence/freeze validation до catalog rebuild.
8. Сохранять hash-bound audit в ingest receipt.
9. V1 results импортировать как `unverified`, не `approved`.
10. Запретить ingest по одному лишь path/hash/duration.

### Acceptance

- старый Day 5 result блокируется внутри `dl2 capture-batch --ingest`, а не
  отдельным скиллом;
- result без method/state/build/metadata не входит в catalog как approved;
- valid real-time fixture проходит;
- debug presentation проходит только с правильной role.

## Wave 2 — Approved Asset Registry

**Приоритет:** P0  
**Effort:** 2–3 дня  
**Зависимости:** Wave 1

### Owning files

- `services/autopilot.py`;
- production manifest/services;
- inventory CLI;
- Studio asset UI.

### Работы

1. Ввести `AssetRecord v2` и stable `asset_id`.
2. Хранить semantic metadata в sidecar/registry, а не в filename.
3. Разделить lifecycle:
   `candidate → validated → approved → archived/rejected`.
4. Записывать derivation lineage:
   label, crop, transcode, clean-up, generated wrapper.
5. Скрывать `rejected`, `archive`, `testbed`, `retimed` из default selector.
6. Автоматически refresh catalog после capture/audio/HyperFrames processing.
7. Сделать duplicate-by-hash информацией, а не альтернативной identity.
8. Добавить Studio action `Approve take` с exact SHA.
9. Запретить final shot manifest с raw path без approved asset.
10. Сделать compatibility layer для старых `src=` с warning и migration report.

### Acceptance

- Day 4–7 нельзя перепутать выбором похожего имени;
- замена файла под тем же path инвалидирует approval;
- derived asset показывает parent и transform;
- rejected/debug assets не появляются в обычном выборе.

## Wave 3 — Source geometry и центрирование

**Приоритет:** P0  
**Effort:** 1–2 дня  
**Зависимости:** Wave 2

### Owning files

- `model/content.py`;
- `compile/roles.py`, `compile/segments.py`;
- `ir.py`;
- `render/beat.py`;
- check services.

### Работы

1. Дать `VideoShot` явные `fit`, `anchor` и/или `focus_rect`.
2. Перенести resolved crop в IR:
   source dimensions, scaled dimensions, crop origin/size, output bounds.
3. Сделать центральный crop явным выражением, а не implicit FFmpeg default.
4. Проверять, что capture client rect совпадает с encoded frame.
5. Запретить editor/window strips для approved gameplay.
6. Проверять, что focus rect не обрезан.
7. Проверять отклонение focus center от output center по tolerance.
8. Запретить повторный pre-crop/upscale только для обхода VQ-RES.
9. Создавать `data/review/geometry_report.json`.
10. Показывать в Studio source frame, crop frame и focus frame численно.

### Важное ограничение

Код доказывает правильность transform. Он не может универсально доказать, что
трамвай художественно выглядит по центру. Если game/layout не предоставляет
focus rect, итоговый subjective center остаётся creative review.

### Acceptance

- editor strip ловится до render;
- crop каждого shot полностью восстанавливается из IR;
- одинаковый source/contract даёт одинаковую geometry;
- Day 3–7 проходят единый report, а не ручные recentered copies.

## Wave 4 — Continuity и Machine-first Boundary Pack

**Приоритет:** P0  
**Effort:** 2–3 дня  
**Зависимости:** Waves 2–3

### Owning files

- `services/render_preflight.py`;
- `services/review_pack.py`;
- compile/IR;
- storyboard/preflight CLI.

### Работы

1. Ввести обязательный `transition_intent`:
   - `continuous_same_take`;
   - `motivated_cut`;
   - `before_after`;
   - `chapter_boundary`;
   - `no_cut`.
2. Для одного asset проверять monotonic source offsets.
3. Блокировать reset к offset 0 без explicit restart intent.
4. Проверять, что used window не съедает head/tail handles.
5. Сопоставлять source state слева и справа от boundary.
6. Расширить существующие duplicate/freeze/cadence checks.
7. Считать frame-distance/SSIM вокруг каждой границы.
8. Генерировать boundary strip ±0.08–0.25 s.
9. Добавить source-change density:
   по умолчанию один gameplay source на день или before+after.
10. Между Day N и Day N+1 требовать declared chapter transition/continuity.
11. Не добавлять fade автоматически как универсальное лечение hard cut.
12. Блокировать full preview при boundary errors.

### Acceptance

- restart Day 7 на 15 s ловится до просмотра;
- ненужный cut 22–23 s виден как undeclared source change;
- переход 55 s имеет explicit intent;
- source end/restart невозможен при достаточных handles;
- pack содержит таблицу всех boundaries, а не случайную выборку кадров.

## Wave 5 — Public copy, debug leaks и canonical claims

**Приоритет:** P0/P1  
**Effort:** 1–2 дня  
**Зависимости:** Wave 2

### Owning files

- `services/editorial_preflight.py`;
- HyperFrames metadata;
- shot manifest;
- product/production facts.

### Работы

1. Создать `data/plan/public_copy.json`.
2. Каждой viewer-visible строке присвоить `copy_id`.
3. Извлекать видимый текст из:
   overlays, captions, labels, HyperFrames, endcards.
4. Добавить forbidden internal tokens:
   `DEBUG`, `TESTBED`, `TODO`, `VERSION`, production ids, технические ranges.
5. Добавить OCR sampled frames как fallback для текста, которого нет в model.
6. Требовать explicit approval для текста вне public-copy manifest.
7. Хранить canonical product facts и CTA:
   Steam page status, wishlist wording, product name.
8. Endcard и publish copy строить из canonical claims.
9. Не смешивать production notes и public labels в одном HTML.

### Acceptance

- `01→10 бумага + графит` блокируется как unapproved copy;
- testbed/debug text блокируется;
- CTA «Следующая остановка — Steam» не может противоречить product facts;
- typo исправляется до render.

## Wave 6 — Полный VO recording state machine

**Приоритет:** P0  
**Effort:** 1–2 дня  
**Зависимости:** Wave 0

### Текущий статус

Уже реализовано частично:

- MediaRecorder начинается сразу;
- UI показывает 3-second countdown;
- karaoke начинает движение после countdown.

Ещё отсутствуют:

- дополнительные 2 s room tone после countdown;
- автоматический 2 s post-roll;
- markers в metadata;
- take-level transient/silence verdict;
- guarded automatic trim.

### Целевые состояния

```text
idle
→ recording_countdown (MediaRecorder уже пишет, 3–2–1)
→ room_tone (2 s)
→ speaking
→ post_roll (2 s после Stop)
→ analyzing
→ ready | rejected
```

### Работы

1. Начинать recorder до countdown.
2. После `3–2–1` показывать `Тишина` ещё 2 s.
3. Только затем показывать `Говори`.
4. Stop переводит UI в `Post-roll`, recorder пишет ещё 2 s.
5. Сохранять markers:
   record start, speech allowed, stop requested, record end.
6. Измерять:
   leading/trailing silence, impulse, clipping, noise-floor jumps.
7. Показывать take badge:
   `clean`, `trim-safe`, `click detected`, `re-record`.
8. `dl2 audio` использует markers для guarded trim.
9. Небезопасная граница не форсится.
10. Добавить browser fake-timer tests и WAV fixtures.

### Acceptance

- raw take всегда содержит ≥2 s чистого lead-in и ≥2 s tail;
- mouse click не попадает в retained speech;
- transient fixture блокируется;
- пользователь видит причину re-record до монтажа.

## Wave 7 — Studio Preflight UI

**Приоритет:** P1  
**Effort:** 2–3 дня  
**Зависимости:** Waves 1–6

### Основной экран production

Studio показывает одну таблицу:

| Day/claim | Expected source | Approved asset | Capture | Geometry | Boundary | Text | Status |
|---|---|---|---|---|---|---|---|

### Работы

1. Capture queue показывает external request/result, не имитируя recorder.
2. Asset card показывает state/build/method/handles/focus/approval.
3. IR inspector показывает asset id, path, SHA, offset и crop.
4. Gate dashboard разделяет:
   `pass`, `block`, `unverified`, `creative decision`.
5. Каждая ошибка предлагает одно действие:
   `recapture`, `approve`, `replace`, `merge`, `change transition`.
6. Final button disabled до полного pass.
7. Один author checkpoint содержит только творческие решения.
8. Blind reviewer остаётся независимым.
9. После blind review запускается known-constraints regression.
10. Stored review проверяется по exact artifact SHA.

### Acceptance

- пользователь не проверяет method/build/debug/speed/handles;
- UI не показывает `green`, если факт unverified;
- механическая ошибка имеет owning action и report link;
- final нельзя запустить обходом UI или CLI.

## Wave 8 — Visual direction и рекламный polish

**Приоритет:** P1  
**Effort:** 3–5 дней  
**Зависимости:** machine gates должны быть готовы

Mechanical correctness не решает жалобу «монтаж выглядит как черновик».
После стабилизации sources Studio должна улучшить визуальный язык.

### Shot-purpose grammar

Каждый ключевой shot получает purpose:

- `proof` — показать реальный результат;
- `compare` — до/после;
- `explain` — визуально объяснить процесс;
- `emphasize` — выделить главный объект/цифру;
- `transition` — обозначить смену главы;
- `cta` — завершить действием.

### Reusable visual blocks

Через существующий HyperFrames bridge:

- Before/After Split;
- Focus Callout;
- Annotated Zoom;
- Process/Pipeline Explainer;
- Progress/Iteration Counter;
- Feature Comparison;
- Day/Chapter Transition;
- Canonical CTA Endcard.

### Правила подачи

1. Ключевой claim имеет видимый proof или emphasis.
2. Текст объясняет, а не повторяет VO целиком.
3. Gameplay не меняется только ради движения.
4. Static visual >3 s требует внутреннего motion/emphasis.
5. Label держится ≥2 s и входит в public copy.
6. Переход соответствует смыслу: продолжение, контраст или новая глава.
7. Before/after синхронизированы по framing.
8. CTA deliberate, корректный и держится достаточно долго.
9. Creative reviewer оценивает:
   hierarchy, clarity, motion, emphasis, consistency, polish.

### Acceptance

- нет черновых технических плашек;
- главные моменты визуально выделены;
- количество source changes не используется как замена анимации;
- video-reviewer даёт ≥4/5 по каждому creative dimension;
- пользовательские замечания после review относятся к вкусу, не к механике.

## Wave 9 — Iteration budget, storage и stop rules

**Приоритет:** P1  
**Effort:** 1–2 дня  
**Зависимости:** gate pipeline

### Работы

1. Считать semantic draft iteration, а не каждый cache restore.
2. Default cap: 3; hard cap: 5.
3. После третьей итерации генерировать root-cause report.
4. После пятой блокировать новый render до:
   - исправления source/capture pipeline; или
   - explicit user override.
5. `final` не использовать как preview.
6. Хранить:
   current draft, last-known-good, exact reviewed final, delivery.
7. Для остального создавать cleanup plan; удаление только явно подтверждённое.
8. Разделять telemetry:
   production, tooling, render, review, human.
9. Dashboard показывает wall budget и главный источник churn.

### Acceptance

- не больше двух draft renders на один локальный mechanical fix;
- не больше двух final renders;
- storage production не растёт бесконтрольно;
- пятая итерация действительно останавливает цикл.

## 8. Critical path

Рекомендуемый порядок:

```text
Wave 0 fixtures
    ↓
Wave 1 capture ingest
    ↓
Wave 2 asset registry
    ↓
Wave 3 geometry ─────┐
                    ├→ Wave 4 boundary pack
Wave 6 VO ──────────┘
    ↓
Wave 5 copy/claims
    ↓
Wave 7 Studio gate UI
    ↓
Wave 8 visual polish
    ↓
Wave 9 budget/storage
```

Почему visual polish не первый: красивый template поверх неправильного source
ускорит выпуск неправильного видео.

## 9. Implementation backlog

| ID | Изменение | Priority | Effort | Основной тест |
|---|---|---:|---:|---|
| CAP-001 | CaptureRequest/Result v2 | P0 | M | DevAPI result не проходит gameplay ingest |
| CAP-002 | Core ingest вызывает capture audit | P0 | M | Day 5 negative fixture |
| REG-001 | AssetRecord v2 + stable id | P0 | L | old/new selector не смешивает state |
| REG-002 | Approval hash binding | P0 | S | replacement делает approval stale |
| GEO-001 | Explicit VideoShot fit/crop/focus | P0 | M | editor strip/focus clipping |
| GEO-002 | Geometry report | P0 | S | deterministic crop facts |
| BND-001 | BoundaryRecord + transition intent | P0 | M | undeclared hard cut |
| BND-002 | Offset/handles/restart gate | P0 | M | source reset на 15 s |
| TXT-001 | Public copy manifest | P0 | M | internal label blocks |
| TXT-002 | Canonical claims/CTA | P1 | S | Steam CTA matches product facts |
| VO-001 | Countdown + room tone + post-roll | P0 | M | fake timer state test |
| VO-002 | Marker-bound transient/trim report | P0 | M | click fixture blocks |
| UI-001 | Production gate table | P1 | L | final disabled on block |
| POL-001 | Six reusable visual blocks | P1 | L | catalog/render tests |
| ORCH-001 | Known-constraints regression | P0 | M | exact SHA checklist |
| OPS-001 | Iteration/storage budget | P1 | M | sixth loop blocked |

Effort: `S` ≤0.5 дня, `M` 1–2 дня, `L` 2–4 дня.

## 10. Migration

1. Не ломать существующие productions сразу.
2. Inventory v1 assets помечает `unverified`.
3. Только v2 productions требуют semantic asset ids для final.
4. Для Devlog 1 создать migration report:
   - logical groups;
   - approved current artifacts;
   - archive/rejected variants;
   - derivation lineage.
5. Raw `src` временно поддерживается с warning.
6. После миграции запретить raw paths для новых productions.
7. Rendered MP4 не перемещать автоматически.
8. Cleanup выполняется отдельным подтверждаемым шагом.

## 11. Test strategy

### Unit

- Pydantic v2 contracts;
- crop/focus arithmetic;
- offset/handle continuity;
- state/build/role compatibility;
- public-copy matching;
- VO state transitions.

### Integration

- valid real-time capture → ingest → approved asset;
- invalid DevAPI gameplay → block;
- approved asset → compile → IR geometry;
- source restart → preflight block;
- public internal label → editorial block;
- exact final SHA → review/delivery.

### Real FFmpeg

- cadence;
- duplicate/freeze;
- boundary strips;
- resolution/upscale;
- audio silence/transients.

### Browser

- Studio recorder countdown/room-tone/post-roll;
- stale approval;
- gate table;
- disabled final;
- actionable errors.

### UAT на одном дне

1. Один 30–40 s real-time take.
2. Один VO take.
3. Один approved asset.
4. Один targeted beat draft.
5. Один machine boundary pack.
6. Одна mechanical correction максимум.
7. Один full preview.

## 12. Definition of Done

План считается реализованным, если новый devlog:

- не содержит wrong old/new source;
- не содержит debug/testbed gameplay;
- не использует DevAPI frames как обычный gameplay;
- не содержит restart/freeze/stepped speed;
- не содержит необъяснимых hard cuts;
- не содержит geometry/upscale defects;
- не содержит internal/черновой copy;
- не содержит click/transient в retained VO;
- использует canonical CTA;
- требует ≤1 mechanical user correction;
- требует ≤3 draft iterations и ≤2 final renders;
- укладывается в 2–3 часа wall и 20–30 минут human time;
- проходит creative review только после всех machine gates;
- визуально воспринимается как законченный ролик, а не technical draft.

## 13. Что не строим

- полноценный GUI timeline editor;
- встроенный OBS/capture backend в Studio;
- автоматическую «оценку красоты» вместо человека;
- silent auto-delete production assets;
- универсальный fade между всеми сценами;
- post-fix неправильного gameplay через interpolation/upscale;
- выбор source по похожему filename.

## 14. Ближайший практический шаг

Не продолжать сначала visual polish. Следующая реализация должна быть вертикальным
срезом `Capture → Registry → IR → Boundary Pack` на одном дне:

1. CaptureRequest v2.
2. Real-time result с state/build/handles.
3. Core ingest block/pass.
4. Approved asset id.
5. Один beat через asset id.
6. Geometry + boundary report.
7. Один storyboard preview.

Этот эксперимент сразу проверит четыре самых дорогих класса ошибок:
неправильный source, нецентрированный capture, restart и лишний переход.
