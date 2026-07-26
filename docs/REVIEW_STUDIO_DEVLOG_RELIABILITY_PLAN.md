# Критическое ревью плана Studio для производства девлогов

**Ревьюируемый документ:** `docs/PLAN_STUDIO_DEVLOG_RELIABILITY.md`
**Дата:** 2026-07-24
**Тип ревью:** стратегия продукта, архитектура, порядок реализации,
конкурентный benchmark
**Вердикт:** план хорошо предотвращает повторение ошибок Devlog 1, но пока
недостаточно хорошо решает исходную задачу — сделать производство девлога
лёгким, быстрым и визуально сильным.

## 1. Короткий вывод

Оценка плана зависит от того, чем его считать:

| Роль документа | Оценка | Почему |
|---|---:|---|
| Post-mortem и каталог отказов | 9/10 | Почти весь фактический фидбек имеет владельца и проверяемый gate |
| План повышения mechanical reliability | 8/10 | Хорошо закрывает capture, provenance, geometry, continuity и VO |
| План продукта «девлог легко и просто» | 5/10 | Слишком много инфраструктуры до первого заметного выигрыша |
| План визуально сильного монтажного инструмента | 4/10 | Visual polish отложен в Wave 8, отсутствует смысловой rough cut |
| Реалистичный MVP-план | 6/10 | Есть acceptance criteria, но нет вертикального среза с ранней ценностью |

Главная ошибка плана не в выбранных механических проверках. Они в основном
правильные. Ошибка в порядке:

> План сначала строит надёжный контроль производства, а только потом —
> быстрый и красивый способ производить видео.

Для внутренней инфраструктуры это логично. Для пользовательского продукта,
получившего оценку 3/10 за медленную и слабую подачу, — нет.

Нужны две параллельные цели:

1. **Trust:** неправильный source, restart, debug, speed, crop или click не
   проходят дальше ingest/preflight.
2. **Velocity + polish:** из сценария и проверенных материалов за минуты
   появляется уже смотрибельный rough cut, а не только зелёный отчёт.

## 2. Что в плане действительно сильное

### 2.1. Он основан на конкретных отказах, а не на абстрактных best practices

У каждого дорогого симптома Devlog 1 есть предполагаемая первопричина,
владелец и acceptance test:

- неправильный Day/build/state → capture contract и asset identity;
- нецентрированный shot → geometry report;
- restart source → offsets, handles и boundary pack;
- ускоренный gameplay → cadence/simulation validation;
- debug/testbed → role и public-copy gates;
- click в VO → marker-bound recording и transient analysis;
- неверный CTA → canonical claims.

Это лучше типичного «добавить AI review», потому что проблема переводится в
детерминированный контракт.

### 2.2. Правильно разделены машинные факты и художественное зрение

Сильный принцип плана:

- код отвечает за state, build, method, FPS, crop arithmetic, offsets,
  transitions, text provenance, SHA;
- зрение отвечает за иерархию, читаемость, выразительность и вкус.

Это напрямую соответствует пользовательскому требованию не использовать
ненадёжное зрение для поиска механических ошибок.

### 2.3. Game-specific provenance — реальное конкурентное преимущество

Premiere, Resolve, Descript и CapCut умеют находить и монтировать медиа, но не
знают сами по себе:

- какой build игры записан;
- относится ли ролик к Day 4 или Day 7;
- является ли scene gameplay или testbed;
- какой visual state должен быть до и после изменения;
- был ли игровой цикл real-time или frame-stepped;
- продолжает ли Day 5 состояние, которым завершился Day 4.

Связка `build_id + state_id + capture_method + editorial_role + exact SHA`
может стать главным отличием Studio, а не просто внутренней бюрократией.

### 2.4. Отказ от «лечения» плохого capture в монтаже правильный

Для wrong speed, debug state, недостаточного разрешения или отсутствия handles
вердикт `recapture` экономит больше времени, чем ретайм, upscale и ручная
маскировка дефекта. Этот принцип надо сохранить.

### 2.5. План уважает существующую архитектуру

Studio остаётся code-first компилятором с FFmpeg backend, а запись gameplay —
внешним процессом. При этом Studio владеет request, validation, ingest и
approval. Это хороший архитектурный компромисс.

## 3. Главные проблемы плана

## 3.1. План скрыто занимает 14.5–25 инженерных дней

Сумма заявленных диапазонов Waves 0–9:

- минимум: 14.5 дня;
- максимум: 25 дней;
- без запаса на интеграционные дефекты, миграцию старых edits и доведение UI.

При этом первый явный пользовательский блок визуального качества находится в
Wave 8. До него нужно пройти 7 волн и ориентировочно 10.5–18 дней.

Это противоречит задаче «сделать легко и просто»: пользователь долго не увидит
главный результат.

### Решение

Планировать не горизонтальные подсистемы, а вертикальные production slices.
Первый slice за 4–6 дней должен пройти путь:

`capture request → запись → ingest → выбор → один beat → machine pack → красивый preview`

## 3.2. План оптимизирует отсутствие ошибок, но не time-to-good-draft

В baseline есть:

- число final renders;
- число corrections;
- storage churn;
- время поздних дефектов.

Но нет ключевых продуктовых метрик:

- время от brief до первого смотрибельного preview;
- время поиска правильного gameplay;
- доля rough cut, принятая без ручной перестройки;
- число ручных действий на один день;
- время от обнаружения нехватки footage до принятого recapture;
- доля ключевых claims с готовым visual proof;
- время creative polish на минуту результата.

Без этих метрик можно построить очень надёжную Studio, в которой всё ещё долго
и неприятно работать.

## 3.3. Visual polish поставлен слишком поздно

Wave 8 — это не необязательное украшение. Жалоба «видео выглядит черновиком» —
одна из двух главных проблем наряду с mechanical defects.

План сначала предлагает создать:

- versioned capture contracts;
- полный asset lifecycle;
- geometry IR;
- boundary records;
- public-copy manifest;
- VO state machine;
- полный preflight dashboard;

и только затем — visual blocks.

Такой порядок даёт правильную систему, но не ранний пользовательский выигрыш.

### Решение

В первый вертикальный slice включить четыре блока:

1. Day/Chapter Card;
2. Before/After;
3. Focus Callout / Annotated Zoom;
4. Canonical CTA Endcard.

Они должны иметь единый brand preset и использоваться в одном реальном beat до
расширения registry/UI.

## 3.4. Нет transcript/script-first rough cut

Это самый большой функциональный пробел относительно рынка.

- Adobe Premiere позволяет автоматически транскрибировать материал и строить
  rough cut копированием, перестановкой и удалением текста
  ([официальная документация](https://helpx.adobe.com/ca/premiere/desktop/edit-projects/edit-video-using-text-based-editing/overview-of-text-based-editing.html)).
- DaVinci Resolve 20 предлагает AI IntelliScript, который создаёт timeline по
  текстовому сценарию
  ([Blackmagic Design](https://www.blackmagicdesign.com/media/release/20250404-02)).
- Descript делает transcript основным интерфейсом монтажа и умеет через
  Underlord чистить структуру, паузы, retakes, звук и добавлять визуалы
  ([Descript](https://www.descript.com/video-editing)).
- Riverside совмещает запись, транскрипт и text-based editing
  ([Riverside](https://riverside.fm/video-editor)).

В текущем плане слова и script используются как данные для VO/captions, но не
как основной способ построить и пересобрать rough cut.

### Что добавить

Нужен контракт:

```text
script claim
→ VO words/time range
→ shot purpose
→ approved visual candidates
→ selected asset/source range
→ generated beat/chunk
```

Пользователь или агент должен уметь:

- удалить или переставить фразу и получить пересчитанный rough cut;
- выбрать claim и увидеть связанные gameplay/visual candidates;
- увидеть, для какой фразы нет proof/explain/emphasis;
- заменить визуал без ручного поиска Python-координат.

Это не GUI timeline и не отказ от code-first. Source of truth остаётся
Python/IR, но смысловой монтаж становится первой операцией.

## 3.5. Asset Registry без semantic search рискует стать бюрократией

Wave 2 предлагает правильные metadata и lifecycle, но не отвечает на вопрос:

> Как агент за секунды найдёт «новый трамвай Day 5, normal speed, чистая сцена,
> где люди уже двигаются»?

Adobe Media Intelligence ищет клипы по объектам, локациям, ракурсам, речи и
metadata естественным языком
([Adobe](https://blog.adobe.com/en/publish/2025/04/02/introducing-new-ai-powered-features-workflow-enhancements-premiere-pro-after-effects)).
CapCut заявляет Smart Search по объектам, речи, людям и окружению
([CapCut](https://www.capcut.com/tools/desktop-ai-power)).

Studio не обязана сразу делать visual embeddings. Но нужны:

- строгие фильтры по day/state/build/role/method/approval;
- полнотекстовый поиск по capture request, notes и transcript;
- понятные thumbnails/contact strips;
- ranking: exact state → approved → adequate handles → resolution → freshness;
- запрос из shot expectation, а не ручное листание каталога.

## 3.6. Wave 6 добавляет лишнее трение при записи VO

Пользователь просил:

- начинать raw recording сразу;
- показать 3–2–1;
- оставить 2–3 секунды материала, чтобы click легко вырезался.

План предлагает:

`3 s countdown + 2 s room tone + речь + 2 s post-roll`.

Это пять секунд ожидания перед каждой репликой и две после. Для большого числа
takes Studio станет ощутимо медленнее.

### Лучше

```text
T+0.0  recorder start, click допустим только здесь
T+0–3  3–2–1, это же lead-in/room-tone
T+3.0  «Говори»
stop   marker
+1.0 s post-roll
```

Если transient или noise floor требуют больше room tone, Studio просит
повторить конкретный take. Общий default должен быть быстрым.

## 3.7. Transition intent слишком дорог как обязательная ручная разметка

Обязательный `transition_intent` на каждой границе создаст много authoring
шума. Большинство переходов можно вывести:

- один asset, монотонный offset → `continuous_same_take`;
- смена day/beat → `chapter_boundary`;
- совпадающая пара state `before/after` → `before_after`;
- один gameplay shot в пределах claim → `no_cut`;
- всё остальное → требует explicit intent.

Нужно требовать ручную декларацию только для неоднозначных или рискованных
границ.

## 3.8. Focus-center gate не доказывает хорошую композицию

Числовой центр `focus_rect` полезен, но:

- главный объект может быть визуально несимметричным;
- UI игры может менять perceptual center;
- «идеально по центру» не всегда художественно правильно;
- нужная композиция зависит от текста и будущего callout.

Лучшее решение — game-owned framing presets через DevAPI:

```text
scene_id
camera_preset
subject_ids
safe_focus_rect
overlay_exclusion_rects
```

Тогда Studio проверяет обещанный framing. Если таких данных нет, machine gate
проверяет только transform и safe bounds, а композиция остаётся creative
review.

## 3.9. OCR как P0/P1 — дорого и ненадёжно

Rendered OCR полезен как последний страховочный слой, но он:

- ошибается на стилизованных и анимированных надписях;
- плохо работает на коротких появлениях;
- не объясняет источник строки;
- добавляет runtime/dependency cost.

Сначала нужно закрыть source-level текст:

- Overlay/caption model;
- HyperFrames visible-copy manifest;
- canonical CTA;
- запрет production labels в public layer.

OCR оставить P2/final fallback для неуправляемых импортированных assets.

## 3.10. Audio plan только ловит дефект, но слабо улучшает звук

Конкуренты дают не только детект:

- Premiere предлагает Enhance Speech и инструменты микса
  ([Adobe](https://www.adobe.com/products/premiere/features.html));
- Resolve 20 — AI Audio Assistant, анализирующий и собирающий микс
  ([Blackmagic Design](https://www.blackmagicdesign.com/products/davinciresolve));
- Descript — Studio Sound, filler/retake removal
  ([Descript](https://www.descript.com/tools/video-editor));
- Riverside — noise/reverb removal, EQ и loudness balancing
  ([Riverside](https://riverside.fm/magic-audio)).

Studio уже имеет speech-edit и loudness pipeline, но в плане нет:

- профиля voice cleanup;
- A/B preview raw/processed;
- измеримого noise/reverb/clipping report;
- автоматического выбора безопасной обработки;
- проверки качества стыков после enhancement.

Нужен не только verdict `re-record`, но и быстрый путь `clean → preview → use`.

## 3.11. Capture plan слабее специализированных recorders по observability

Riverside подчёркивает local recording, отдельные raw tracks и continuous
upload/recovery
([Riverside](https://riverside.fm/video-editor)).
OBS показывает CPU, FPS и dropped-frame statistics
([OBS](https://obsproject.com/forum/resources/status-indicators-and-what-they-mean.957/)).

Для внешнего gameplay capture runner в плане отсутствуют:

- live FPS/encode-lag monitor;
- dropped/duplicated frame counters во время записи;
- target-window visibility/occlusion check;
- disk-space guard;
- crash-safe temporary recording и recovery;
- hardware/software encoder profile;
- запись фактического client rect при старте и завершении;
- сигнал о смене build/state во время take.

Проверка после записи нужна, но ранняя остановка плохого take ещё дешевле.

## 3.12. Нет автоматического visual attention для screen/demo shots

Screen Studio автоматически добавляет zoom к действиям, сглаживает cursor,
адаптирует zoom при vertical export и применяет background/spacing/shadow
([Screen Studio](https://screen.studio/)).

Studio не должна копировать cursor-specific продукт целиком, но для записей
Studio UI, Canvas, кода и debug-пояснений полезны:

- declarative focus events;
- automatic pan/zoom к focus rect;
- consistent inset/background/shadow preset;
- адаптация framing под vertical/landscape;
- автоматическое скрытие неподвижного cursor, если он попал в capture.

Это даст больше видимого качества, чем добавление ещё одного общего reviewer.

## 3.13. Creative score `≥4/5` создаёт ложную точность

Без калиброванного reference set два reviewer-а могут дать разные 4/5.
Acceptance должен опираться на наблюдаемые условия:

- каждый ключевой claim имеет proof/explain/emphasis;
- нет статического участка дольше установленного порога без намеренного hold;
- public text проходит dwell/readability gate;
- chapter transition имеет визуальный и звуковой мотив;
- before/after сопоставимы по framing;
- CTA читаем и соответствует canonical product fact.

Числовой score можно оставить как trend, но не как единственный pass.

## 3.14. Нет post-publish learning loop

План заканчивается delivery. Но запрос — не просто отсутствие дефектов, а
«стильно, сочно, хитово».

Для этого нужны данные после публикации:

- CTR thumbnail/title;
- retention первых 30 секунд;
- drop-off по главам и claims;
- rewatch peaks;
- clicks/wishlists, если доступны;
- комментарии, классифицированные как story/clarity/visual/audio.

Минимально достаточно вручную заносить показатели через 48 часов и 7 дней,
привязывая их к beat/claim ids. Без этого Studio учится только на субъективном
review, но не на реакции аудитории.

## 4. Сравнение с конкурентами

Конкуренты ниже — не обязательно прямые замены Studio. Они являются benchmark
по отдельным частям workflow.

| Продукт | Где он сильнее текущего плана | Что Studio должна взять | Что не нужно копировать |
|---|---|---|---|
| Adobe Premiere | Text-Based Editing, Media Intelligence, Enhance Speech, Generative Extend, зрелый NLE | transcript rough cut, semantic search, удобный extension/handles workflow | полный timeline, color/VFX suite, cloud-first generative dependency |
| DaVinci Resolve 20 | IntelliScript, animated subtitles, Audio Assistant, Fusion, профессиональный finish | script-to-IR, параметризованные subtitle/motion templates, mix assistant | собственный Fusion/Fairlight/Color аналог |
| Descript | документ как интерфейс монтажа, Underlord, filler/retake cleanup, Studio Sound | смысловой editing loop и reversibility, one-click cleanup/polish | непрозрачные AI-правки без deterministic IR/evidence |
| CapCut | быстрый первый результат, AutoCut, Smart Search, Auto Reframe, captions/templates | instant styled preview, curated presets, fast candidate search | trend/template spam и автоматические cuts без continuity contract |
| Riverside | запись и монтаж в одном UX, local recording, tracks, text editing, recovery | recording health, markers, recovery, immediate transcript | remote guest/collaboration platform |
| Screen Studio | красивый screen capture по умолчанию, auto zoom, cursor smoothing, brand framing | declarative attention motion и polished capture wrapper | macOS-only cursor-centric модель как ядро Studio |

### 4.1. Capability matrix

Обозначения: **сильная** — ключевая функция продукта; **частично** — есть
основа, но нет полного удобного workflow; **нет** — отсутствует в плане.

| Capability | Studio plan | Premiere | Resolve | Descript | CapCut | Riverside | Screen Studio |
|---|---|---|---|---|---|---|---|
| Build/state-aware gameplay provenance | **сильная** | нет | нет | нет | нет | нет | нет |
| Deterministic hard QA gates | **сильная** | частично | частично | частично | частично | частично | частично |
| Code-first reproducible edit | **сильная** | нет | нет | нет | нет | нет | нет |
| Transcript/script rough cut | нет | **сильная** | **сильная** | **сильная** | частично | **сильная** | нет |
| Natural-language media search | нет/частично | **сильная** | частично | transcript | **сильная** | transcript | нет |
| Instant visual polish/templates | поздно/частично | **сильная** | **сильная** | **сильная** | **сильная** | частично | **сильная** |
| Automatic audio cleanup/mix | частично | **сильная** | **сильная** | **сильная** | частично | **сильная** | частично |
| Recording health/recovery | частично | не ядро | не ядро | частично | частично | **сильная** | **сильная** |
| Gameplay continuity by semantic state | **сильная** | нет | нет | нет | нет | нет | нет |
| Post-publish learning | нет | через ecosystem | через ecosystem | частично | platform-oriented | частично | нет |

## 5. Правильное позиционирование Studio

Studio не должна пытаться стать:

> бесплатным локальным Premiere + Resolve + Descript + CapCut + Riverside.

Такой scope никогда не станет простым.

Более сильная позиция:

> Studio — локальный devlog compiler и production control plane, который
> знает build/state игры, не пропускает неправильные записи, строит
> смысловой rough cut из сценария и проверенных assets и применяет
> повторяемый визуальный язык.

То есть Studio должна выигрывать не шириной NLE, а связкой:

```text
game state truth
+ semantic asset selection
+ script-to-IR
+ deterministic QA
+ opinionated visual polish
```

Для сложной ручной цветокоррекции или уникального VFX можно позже добавить
экспорт/round-trip, но не строить собственный профессиональный NLE.

## 6. Что сохранить, изменить, отложить

### Сохранить как P0

- regression fixtures по реальным дефектам;
- CaptureRequest/Result v2;
- запрет frame-stepped DevAPI для editorial gameplay;
- state/build/method/role/exact-SHA provenance;
- native resolution/cadence/freeze/handles gate;
- minimal approved asset identity;
- explicit geometry в IR;
- source offsets и restart detection;
- marker-aware VO recording и transient gate;
- exact-hash review;
- debug/public-copy separation.

### Изменить

- полный Asset Registry заменить в MVP на hash-bound sidecars и query API;
- explicit `transition_intent` требовать только на неоднозначных boundaries;
- VO сделать `3 s total lead-in + 1 s post-roll`, а не `3+2+2`;
- geometry связать с game-owned camera/focus presets;
- gate UI начинать как маленькую таблицу вертикального slice, не отдельную
  позднюю волну;
- visual blocks делать одновременно с первым production slice;
- creative score использовать как diagnostic, а не hard truth.

### Добавить в P0/P1

- script/claim ↔ words ↔ shot-purpose ↔ asset mapping;
- transcript/script-first rough cut;
- semantic filter/search по asset registry;
- time-to-first-good-draft telemetry;
- capture live-health и crash recovery;
- voice cleanup A/B preview;
- affected-beat preview budget;
- brand/style preset;
- post-publish retention/CTR feedback.

### Отложить до P2

- полный lifecycle UI `candidate → archived/rejected`;
- OCR всех sampled frames;
- восемь visual blocks сразу;
- полноценный storage dashboard;
- natural-language visual embeddings, пока строгих metadata-фильтров
  достаточно;
- collaboration/cloud review parity;
- generative clip extension;
- любой аналог полноценного timeline editor.

## 7. Пересобранный roadmap

## Milestone A — Trusted polished slice

**Срок:** 4–6 дней
**Цель:** один реальный день проходит от capture до красивого beat preview без
ручного обнаружения механических дефектов.

### Scope

1. Negative/positive fixtures для Day 5.
2. CaptureRequest/Result v2.
3. Ingest gate: method/state/build/role/resolution/cadence/handles.
4. Minimal `AssetRecord` sidecar:
   `asset_id`, SHA, state, build, role, method, approval, focus.
5. Geometry IR + restart/boundary report.
6. VO markers: recorder start → 3–2–1 → speak → 1 s post-roll.
7. Один compact gate screen.
8. Четыре visual blocks:
   Day Card, Before/After, Focus Callout, CTA.
9. Один реальный beat, собранный целиком.

### Exit criteria

- неправильный Day 5 capture невозможно выбрать как approved gameplay;
- центрирование и crop доказаны числами;
- restart/short handle блокируются;
- raw VO содержит безопасные границы;
- preview уже выглядит как часть релизного видео;
- не более одной человеческой mechanical correction.

## Milestone B — Fast semantic rough cut

**Срок:** 4–6 дней
**Цель:** превратить сценарий и approved assets в изменяемый rough cut без
ручного поиска исходников и таймингов.

### Scope

1. Claim ids и script-to-words map.
2. Shot purpose на каждый claim.
3. Asset query/ranking по state/build/role/handles/focus.
4. Script/transcript operations, компилируемые обратно в Python/IR.
5. Missing-proof report.
6. Preview только изменённых beats.
7. Метрики:
   search time, rough-cut acceptance, actions per day, first-good-draft time.

### Exit criteria

- удаление/перестановка claim пересобирает rough cut;
- для claim видны selected asset и альтернативы;
- missing visual proof обнаруживается до full preview;
- один день чернового монтажа собирается за минуты, не часы.

## Milestone C — Opinionated polish

**Срок:** 5–7 дней
**Цель:** превратить корректный rough cut в последовательный,
рекламно-выразительный devlog.

### Scope

1. Brand preset: typography, color, spacing, transitions, sound accents.
2. Расширение visual block catalog только по реальным потребностям.
3. Declarative focus events и automatic pan/zoom.
4. Caption/emphasis templates.
5. Voice cleanup preview и safe processing profile.
6. Creative evidence rubric с reference frames.
7. One-click `polish preview`, но все изменения остаются в IR и обратимы.

### Exit criteria

- каждый главный claim имеет proof/explain/emphasis;
- отсутствуют немотивированные source changes;
- стиль целостен между днями;
- пользователь исправляет вкус, а не базовый монтаж.

## Milestone D — Release learning

**Срок:** 2–3 дня
**Цель:** следующий devlog становится лучше на основании реакции аудитории.

### Scope

1. Publish snapshot: title, thumbnail, description, artifact SHA.
2. Ручной импорт метрик через 48 часов и 7 дней.
3. Retention/drop-off mapping к beat/claim.
4. Hypothesis log для hook, visual emphasis, pacing и CTA.

### Exit criteria

- следующий план использует фактические retention/CTR наблюдения;
- «хитово» перестаёт означать только субъективную оценку reviewer-а.

## 8. Изменённый critical path

```text
Regression fixtures
       ↓
Capture v2 + minimal asset sidecar
       ↓
Geometry + boundary + VO markers
       ↓
One real beat + 4 polish blocks
       ↓
────────────────── value checkpoint ──────────────────
       ↓
Script/transcript rough cut + semantic asset query
       ↓
Full devlog preview + calibrated creative review
       ↓
Release + retention/CTR learning
```

Ключевое отличие: пользователь получает проверяемый и красивый результат
после первого milestone, а не после Wave 8.

## 9. Обновлённые продуктовые метрики

| Метрика | Baseline | Цель MVP |
|---|---:|---:|
| Time to first good draft | не измерялось | ≤30 мин после готовых VO/assets |
| Поиск правильного asset | ручной/неизвестно | ≤30 с на claim |
| Human mechanical corrections | 20 | ≤1 на полный devlog |
| Final renders | 27 | 1, максимум 2 |
| Recapture decision latency | до позднего монтажа | ≤2 мин после take |
| Rough-cut acceptance | не измерялось | ≥70% duration без перестройки |
| Claims with visual proof | не измерялось | 100% ключевых claims |
| Manual actions per day | не измерялось | измерить, затем −60% |
| Full preview count | много итераций | 1–2 |
| Post-release learning | отсутствует | snapshot 48 h + 7 d |

## 10. Итоговая рекомендация

Исходный план не нужно выбрасывать. Его mechanical части — хорошая спецификация
целевого состояния. Но исполнять его по Waves 0→9 не следует.

Рекомендуется:

1. Сохранить документ как полный reliability backlog.
2. Реализацию вести по четырём вертикальным milestones из этого ревью.
3. В первый milestone включить одновременно trust и видимый polish.
4. До полного registry/UI добавить смысловой script-to-IR workflow.
5. Позиционировать Studio как game-aware devlog compiler, а не как новый NLE.

После этой перестройки план будет не только предотвращать повтор Devlog 1, но и
реально сокращать путь к сильному видео.

## 11. Официальные источники конкурентного benchmark

- [Adobe Premiere — features](https://www.adobe.com/products/premiere/features.html)
- [Adobe Premiere — Text-Based Editing](https://helpx.adobe.com/ca/premiere/desktop/edit-projects/edit-video-using-text-based-editing/overview-of-text-based-editing.html)
- [Adobe — Media Intelligence and Generative Extend](https://blog.adobe.com/en/publish/2025/04/02/introducing-new-ai-powered-features-workflow-enhancements-premiere-pro-after-effects)
- [Blackmagic Design — DaVinci Resolve 20 announcement](https://www.blackmagicdesign.com/media/release/20250404-02)
- [Blackmagic Design — DaVinci Resolve](https://www.blackmagicdesign.com/products/davinciresolve)
- [Descript — AI video editing](https://www.descript.com/video-editing)
- [Descript — editor](https://www.descript.com/tools/video-editor)
- [CapCut Desktop — AI features](https://www.capcut.com/tools/desktop-ai-power)
- [CapCut — Auto Video Editor](https://www.capcut.com/tools/auto-video-editor)
- [Riverside — video editor and recording](https://riverside.fm/video-editor)
- [Riverside — Magic Audio](https://riverside.fm/magic-audio)
- [Screen Studio — product page](https://screen.studio/)
- [OBS — status indicators and statistics](https://obsproject.com/forum/resources/status-indicators-and-what-they-mean.957/)
