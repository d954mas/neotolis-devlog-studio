# Studio v3 — исследование review-систем и план развития

Date: 2026-07-30

Status: product decision and implementation roadmap

Persona: один владелец, который не монтирует руками, а показывает, что и где
ему не нравится; монтаж исправляет агент.

Review status: revised after the independent
[architecture, product and implementation critique](./STUDIO-V3-REVIEW-SYSTEM-PLAN-REVIEW.md).

## Решение

Studio v3 нужна собственная небольшая **director review console**, а не
встроенный монтажный редактор и не внешний approval-сервис.

Текущий review-контур уже правильно решает базовую задачу:

- комментарий к точному кадру или полуоткрытому диапазону кадров;
- прямое выделение прямоугольной области в кадре;
- автоматическая привязка активных слоёв, переходов и звуков из exact
  `TimelineIR`;
- immutable `ReviewVerdict`, связанный с exact artifact, check report и
  constraints;
- локальные черновики и CAS-защита от отправки feedback к устаревшей версии;
- машинный JSON через `GET /api/v3/review/current`.

Главный недостающий слой — не новые инструменты рисования, а **замкнутый цикл
исправления**:

```text
владелец отмечает проблему
        ↓
агент получает exact structured feedback
        ↓
агент меняет authoring и создаёт новую версию
        ↓
владелец сравнивает «до / после»
        ↓
каждое замечание получает «исправлено / всё ещё не так»
```

Поэтому первый приоритет — доказать один полный agent loop, затем формализовать
review rounds и дать агенту compact task pack. A/B-проверка идёт после
работающего handoff; звуковая шкала — только после этого.

## Что требуется именно этому пользователю

Обязательное:

1. Видеть финальный ролик и быстро перемещаться по нему.
2. Оставлять комментарий на один exact frame.
3. Выделять диапазон во времени прямым жестом.
4. Показывать область в кадре без режима ручного монтажа.
5. Видеть, какие слои, переходы и звуки активны в этом месте.
6. Передавать агенту не скриншот и пересказ, а exact structured finding.
7. После исправления видеть старую и новую версии и проверять каждое
   замечание.
8. Не ломать immutable artifacts, source-of-truth boundaries и render cache.

Не требуется:

- ручное перемещение или обрезка клипов;
- keyframe/property editor;
- multi-user presence, mentions, роли и уведомления;
- project/DAM/task-management;
- облачная загрузка как обязательная часть процесса;
- второй renderer, второй timeline runtime или plugin framework.

## Сравнение с коммерческими системами

Сравнение ниже оценивает не количество функций, а усилие одного владельца и
пригодность результата для агента.

| Система | Усилие владельца | Actionability для агента | Что взять | Что не брать |
|---|---|---|---|---|
| [**Frame.io**](https://help.frame.io/en/articles/9105251-commenting-on-your-media) | Прямой comment к кадру/range/anchor | Высокая: structured export, API, webhooks | Range handles, anchored feedback, per-finding compare | Team/DAM/notification model |
| [**Dropbox Replay**](https://help.dropbox.com/view-edit/dropbox-replay-feedback) | Простой `Post`, range и drawing | Средняя: JSON/CSV/XML export, но публичный Replay API не подтверждён | Plain-language review и переносимый JSON | Обязательный cloud handoff |
| [**SyncSketch**](https://support.syncsketch.com/hc/en-us/articles/32393850754196-Timeline-Navigation-and-Playback-Controls) | Более технический VFX-flow | Средняя: CSV; полный API на старшем tier | A/B toggle и waveform navigation | Плотная VFX timeline |
| [**Filestage**](https://help.filestage.io/en/articles/7002949-commenting-on-files) | Team approval flow | API/webhooks начиная с Business | Compare как reference | Approval/process layer |
| [**Wipster**](https://www.wipster.io/product) | Простой frame comment и region | Низкая на доступных tiers | Direct region gesture | Enterprise-only bridge |
| [**Vimeo Review**](https://help.vimeo.com/hc/en-us/articles/12426192100113-How-to-use-and-manage-video-review-links) | Самый простой timestamp flow | Низкая: geometry/range protocol не подтверждён | Простоту просмотра | Ограниченный feedback protocol |

Studio контролирует обе стороны цикла, поэтому internal canonical query важнее
чужого import/export adapter.

## Открытые и локальные системы

| Система | Сильная сторона | Критический gap | Решение |
|---|---|---|---|
| [**xSTUDIO**](https://github.com/AcademySoftwareFoundation/xstudio) | Apache-2.0, local desktop, frame/range notes, vector draw-over, multi-track audio/video, OTIO, CSV/JPEG export | Тяжёлое desktop-встраивание; vector annotation API пока новее стабильного release; нет нашего verdict lifecycle | Лучший functional POC, но не core |
| [**Kitsu + Zou**](https://kitsu.cg-wire.com/review/) | Зрелый web review, annotations, compare, waveform, REST/OpenAPI/Python SDK/event stream | Production-tracking система, AGPL, нет документированных time-range comments и TimelineIR context | Лучший open web reference, но слишком большой sidecar |
| [**OpenRV**](https://github.com/AcademySoftwareFoundation/OpenRV) | Apache-2.0, точный playback, paint/shapes, audio, layers, OTIO, wipes/layout compare | Нет comment threads, finding status, verdict и agent handoff | Viewer/annotation engine, а не готовая review-система |
| [**AYON**](https://help.ayon.app/en/help/articles/8669165-review-sessions) | Review sessions, ranges, compare, guest approval, API, OpenRV integration | Server/Postgres/Redis/addons, fair-source backend и платный review addon | Исключить из solo shortlist |

Ни один вариант не является drop-in решением. Даже самые сильные открытые
системы видят flattened media или собственную production model, но не знают
`authoring.Edit`, exact `TimelineIR` target IDs, check report, constraints и
release eligibility Studio v3.

## Отдельное решение по HyperFrames

HyperFrames полезен, но для другой роли.

[Full Studio](https://hyperframes.app/docs/5-packages/studio) через
`npx hyperframes preview` даёт timeline, clips/layers, waveform, frame
stepping, range selection и source editing. Его selection bridge:

```powershell
npx hyperframes preview --context --json --context-fields selection
```

возвращает source/composition, current time, стабильный `data-hf-id` или
selector, bounding box, text/styles и thumbnail. Это отличный протокол для
команды агенту «измени выбранный элемент».

Но Full Studio:

- предназначен для source editing: trim, move, z-order, text/style;
- не связывает feedback с artifact/check/constraints digests Studio v3;
- не хранит полноценный lifecycle frame/range findings и их resolution;
- использует transient selection, а не canonical review fact;
- требует React 19/Zustand, тогда как текущий WebUI использует Preact 10;
- создаёт лишний Chrome/render/cache контур, если сделать его вторым runtime.

Лёгкий `<hyperframes-player>` проще встроить, но сам по себе не имеет layers,
ranges, comments или selection.

Итог:

- **не заменять** `ReviewWorkspace` на HyperFrames Studio;
- **не встраивать** полный Studio в owner flow;
- заимствовать range-feedback UX, compact context envelope и
  content-addressed thumbnails;
- использовать HyperFrames selection bridge как optional authoring adapter,
  только если конкретная production действительно authored в HyperFrames.

## Почему это не ломает разделение и кеширование

Review остаётся строго downstream от render:

```text
authoring.Edit
      ↓
TimelineIR ──→ render/execution cache ──→ exact final BlobRef
                                            ↓ read-only
                               review context + comments
                                            ↓
                         ReviewVerdict.v3 + ReviewRound.v1
                                            ↓
                                 agent changes authoring
                                            ↓
                                  new TimelineIR/artifact
```

Правила реализации:

1. Текст, диапазоны, области и resolution status никогда не входят в render
   execution key.
2. A/B-viewer читает два существующих immutable `BlobRef`; он не копирует и не
   перерендеривает видео.
3. `ReviewVerdict.v3` остаётся byte-compatible exact-artifact decision.
   Cross-version lineage принадлежит отдельному `ReviewRound.v1`.
4. `review:latest` делает старый round/artifact достижимым из current head.
   Lineage остаётся review history и не входит в release identity/trust closure.
5. Координаты старого finding остаются привязаны только к старому artifact.
   Их нельзя молча переносить на новую версию.
6. Filmstrip thumbnails, crops и waveform — rebuildable presentation cache,
   keyed как минимум по exact source/artifact `BlobRef`, параметрам извлечения
   и tool fingerprint.
7. Извлечение кадров/волны остаётся внутри существующего владельца
   `rendering`/FFmpeg; UI не получает второй media runtime.
8. Если изменился `TimelineIR`, обычный render cache hit/miss работает как
   раньше. Сам факт review ничего не инвалидирует.
9. Одинаковый artifact hash после изменения authoring допустим: это обычный
   cache hit, а UI показывает «медиа не изменилось».

## Целевая модель использования

### Первый review

1. Владелец смотрит видео.
2. Кликает кадр или протягивает диапазон.
3. При необходимости обводит область.
4. Пишет обычным языком: «переход резкий», «музыка закрывает голос»,
   «этот блок слишком низко».
5. Studio автоматически добавляет active TimelineIR targets.
6. Владелец отправляет findings.

### Работа агента

Агент получает compact structured task pack:

```json
{
  "artifact": {"sha256": "...", "size": 123},
  "timeline": {"sha256": "...", "size": 456},
  "finding_id": "studio.ui.001",
  "frames": [120, 151],
  "region_milli": [120, 180, 420, 260],
  "target_ids": ["visual.002", "transition.visual.002", "audio.001"],
  "target_snapshots": [
    {"id": "visual.002", "kind": "visual", "label": "Заголовок"}
  ],
  "source_mapping": {"status": "unavailable"},
  "text": "Переход слишком резкий, музыка перекрывает фразу",
  "evidence": null
}
```

Это projection для агента, а не новый владелец факта. Canonical source остаётся
`ReviewVerdict`. Local authoring path или compile hint, если они доступны,
остаются noncanonical agent hints и не попадают в `TimelineIR`, render identity
или verdict.

### Повторный review

1. UI показывает новую версию.
2. Сверху — короткий список предыдущих замечаний.
3. Кнопка/клавиша «До» мгновенно показывает exact старый artifact на старом
   locator.
4. Default action — «Все исправления устраивают».
5. Владелец отмечает только исключения: `Всё ещё не так` или
   `Больше не актуально`.
6. При `Всё ещё не так` создаётся required finding с новым exact range/region.
7. Canonical round записывает explicit resolution каждого обязательного
   предыдущего finding, даже если UI сделал это одним действием.

## План реализации

### Phase 0 — доказать один полный agent loop

Status: completed on 2026-07-30. See the
[executable Phase 0 report](./STUDIO-V3-REVIEW-SYSTEM-PHASE0.md).

Цель: до изменения canonical schema проверить реальный путь:

```text
один comment → GET current feedback → поиск места в authoring → правка →
advance/render → новый review
```

Действия:

- использовать безопасную fixture production и текущий `ReviewVerdict.v3`;
- зафиксировать, сколько ручного поиска потребовали `target_ids`;
- записать `source_mapping: available | unavailable`, не добавляя новый факт;
- проверить, что агент не нуждается в screenshot, clipboard или пересчёте
  timecode;
- отдельно воспроизвести текущий non-pass переход в `package`.

Критерии приёмки:

- один finding приводит к новой review-ready версии;
- task handoff воспроизводим из API JSON в fresh process;
- известны конкретные пробелы source locatability;
- spike не меняет domain schema и render cache.

### Phase 1 — contracts: exact verdict и cross-version round

Status: completed on 2026-07-30.

Цель: определить canonical модель без compatibility reader.

Dependency: Phase 0. Это contract-only phase; runtime transition и persistence
не меняются до Phase 2.

`ReviewVerdict.v3` остаётся без изменений. Новый `ReviewRound.v1` содержит:

```json
{
  "verdict": {"sha256": "...", "size": 123},
  "previous_round": {"sha256": "...", "size": 456},
  "resolutions": [
    {
      "previous_finding_id": "studio.ui.001",
      "status": "still_wrong",
      "current_finding_id": "studio.ui.001"
    }
  ]
}
```

Canonical rules:

- `previous_round` nullable только для первого round;
- resolutions сортируются по `previous_finding_id`, который уникален;
- `current_finding_id` non-null только для `still_wrong`, уникален среди
  resolutions и обязан ссылаться на required finding текущего verdict;
- для `fixed | obsolete` `current_finding_id` всегда null;
- direct reachable refs round — `verdict` и optional `previous_round`;
- `$domain = dlstudio.review_round`, `$version = 1`;
- loader проверяет exact schema, canonical bytes и reconstructed hash.

Resolution truth table:

| Resolution | Current finding | Допустимый outcome |
|---|---|---|
| `fixed` | отсутствует | `pass`, `changes_requested` или `block` |
| `obsolete` | отсутствует | `pass`, `changes_requested` или `block` |
| `still_wrong` | required current finding обязателен | `changes_requested` или `block`, но не `pass` |

Application, загрузив previous round/verdict, проверяет:

- completeness обязательных previous findings;
- unknown и duplicate resolution;
- соответствие `still_wrong` current finding;
- запрет `pass` при любом unresolved finding.

`block` не завершает workflow, но не обрывает issue lineage: все обязательные
previous findings всё равно получают `fixed`, `obsolete` или `still_wrong`.
Blocker текущего просмотра хранится как finding текущего exact verdict.

Workflow semantics:

| Verdict outcome | Workflow |
|---|---|
| `pass` | review succeeds; следующим становится `package` |
| `changes_requested` | round сохраняется; workflow остаётся на `review` |
| `block` | round сохраняется; workflow остаётся на `review` |

Lineage — review history. Она не входит в `ReleaseCandidate` identity или
release trust closure; release по-прежнему использует только exact passing
`ReviewVerdict.v3`.

Критерии приёмки:

- byte-exact golden fixture существующего `ReviewVerdict.v3`;
- deterministic canonical round-trip `ReviewRound.v1`;
- три раунда `still_wrong → still_wrong → fixed`;
- multi-round `block` сохраняет и затем продолжает active issue lineage;
- `pass + still_wrong` и incomplete/unknown/duplicate resolutions rejected;
- package/release regression подтверждает неизменный v3 contract.

### Phase 2 — atomic persistence и lineage authorization

Status: completed on 2026-07-30.

Цель: сделать round history crash-safe и разрешить только её exact media.

Dependency: Phase 1. Именно здесь contract-only workflow table из Phase 1
становится runtime behavior.

Persistence:

- добавить `review:latest` в reserved record keys;
- generic record mutation не может писать этот key;
- расширить `WorkflowStore` exact owner operation:

  ```python
  commit_review_round(
      workflow: WorkflowRun,
      round_ref: BlobRef,
      *,
      expected_workflow_revision: int,
      expected_head_revision: int,
      expected_latest_round: BlobRef | None,
  ) -> WorkflowRun
  ```

- operation проверяет expected head, workflow revision и previous round ref;
- `pass` одним CAS публикует succeeded workflow и новый latest round;
- non-pass одним CAS публикует latest round, не завершая workflow review;
- upstream `prepare` invalidation сохраняет latest round;
- crash до commit оставляет старое состояние, retry идемпотентен.

Verdict и round bytes публикуются в object store до CAS. Если клиент потерял
ответ и повторил identical payload, а `review:latest == round_ref` и workflow
уже в ожидаемом состоянии, use case возвращает success. Иной latest ref даёт
CAS conflict.

Application/HTTP:

- `GET /api/v3/review/current` сохраняет response contract
  `ReviewVerdict`, но читает verdict через `review:latest`, а не только
  succeeded workflow attempt;
- `GET /api/v3/review/context` получает optional previous round/context;
- новый `GET /api/v3/review/task-pack` появляется только в Phase 3;
- `POST /api/v3/review` принимает optional `expected_latest_round` и
  `resolutions`; первый round использует null и пустой список;
- существующая CLI-команда `review --verdict` вызывает тот же application use
  case с теми же optional transport fields; новая команда не добавляется;
- lineage walk bounded, cycle-safe и fail-closed на corrupt object;
- old timeline восстанавливается через
  `verdict.check_report → CheckReport.timeline`;
- artifact query принимает только current artifact или artifact из exact
  latest-round lineage;
- requested old `BlobRef`, а не current context, выбирает bytes;
- authorization cache keyed по current head/latest round и имеет bound.

Concrete limits:

- `MAX_REVIEW_LINEAGE_DEPTH = 1024`; depth exhaustion fails closed;
- test fixture содержит 101 linked rounds;
- authorized-lineage LRU: максимум 8 head/latest identities;
- verified-artifact LRU: максимум 256 `(sha256, size)` entries;
- смена current head/latest round инвалидирует соответствующую authorization
  entry.

Критерии приёмки:

- atomic «workflow + pointer или ничего» для pass;
- crash/retry/reopen и stale previous-round CAS tests;
- latest round остаётся доступен после нового `prepare`;
- current/old GET, HEAD и 206 работают;
- unrelated blob, wrong size/hash, cycle и corrupt lineage rejected;
- cached old URL никогда не отдаёт current bytes;
- render execution key и cache layout не меняются.

### Phase 3 — минимальный agent task pack

Цель: агент получает actionable context до появления A/B UI.

Dependencies: Phases 0–2.

- application query объединяет exact round/verdict/context и target snapshots;
- каждый target snapshot содержит kind/lane/label/start/duration;
- adapter может добавить local authoring hint как noncanonical projection;
- при отсутствии надёжного mapping возвращается
  `source_mapping: unavailable`;
- HTTP отдаёт structured JSON; clipboard не является протоколом;
- first version не генерирует evidence и не мутирует submitted verdict.

HTTP contract: `GET /api/v3/review/task-pack` возвращает latest round ref,
verdict ref/payload, artifact/timeline/check/constraints refs и findings с
target snapshots. Если latest round отсутствует, endpoint отвечает not-found,
а не строит feedback из browser draft.

Если Phase 0 показывает повторяемую проблему поиска source, source map
проектируется отдельно в владельце `authoring`; он не попадает в `TimelineIR`.

Критерии приёмки:

- task pack восстанавливается в fresh process из canonical refs;
- агенту не нужен `localStorage` или UI state;
- target IDs и human labels соответствуют exact TimelineIR своего round;
- CLI/HTTP transport-equivalence сохраняется.

### Phase 4 — resolution UI и минимальный A/B

Цель: владелец быстро проверяет исправления без issue-tracker ceremony.

Dependencies: Phases 1–3.

- default action «Все исправления устраивают» создаёт explicit `fixed`
  resolutions;
- владелец отмечает только `still_wrong` или `obsolete` exceptions;
- `still_wrong` требует current exact locator/finding;
- per-finding hold/toggle `До` показывает old exact artifact;
- old/current version и locator всегда подписаны;
- кнопки previous/next finding;
- side-by-side, overlay и full-video linked playback не входят в first release.

Presentation-time sync помогает навигации, но не становится canonical mapping.
При разных FPS/duration каждый artifact clamped независимо.

Критерии приёмки:

- compare не запускает render;
- seek использует HTTP Range;
- одинаковые artifact refs показывают «медиа не изменилось»;
- keyboard и mobile task flow проходят browser test;
- нет horizontal overflow на responsive matrix;
- mobile bottom sheet добавляется только при превышении измеренного scroll
  budget.

### Phase 5 — presentation evidence и final-mix waveform

Цель: добавить доказательства и звуковую навигацию, не смешивая их lifecycle с
immutable verdict.

Dependencies: Phases 2–4. Phase 5 не блокирует базовый review loop.

Сначала отдельный rendering-owned extraction contract:

- exact source/artifact `BlobRef`;
- frame/crop/envelope parameters;
- tool fingerprint;
- content-addressed rebuildable presentation cache;
- bounded concurrency и corruption recovery;
- никакой FFmpeg work под writer lease.

HTTP access:

- evidence endpoint принимает exact lineage-authorized artifact ref, frame и
  optional normalized region;
- waveform endpoint принимает тот же artifact ref и bounded sample count;
- frame обязан находиться внутри exact artifact context;
- region проходит существующие 0..1000 geometry rules;
- width ограничен `64..640`, waveform samples — `256..8192`;
- unrelated artifact получает тот же fail-closed denial, что video endpoint.

Cache lifecycle:

- lazy generation выполняется после authorization и вне writer lease;
- один per-key lock объединяет concurrent misses;
- temp output проверяется и atomic-promote публикует cache entry;
- corrupt entry удаляется и перестраивается;
- максимум 4096 entries и 512 MiB на production;
- deterministic LRU manifest выполняет opportunistic eviction;
- cache полностью rebuildable и не является canonical production state.

Lazy frame/crop evidence остаётся derived task-pack projection и не добавляется
задним числом в `ReviewVerdict.review_pack`. Canonical evidence допустимо
только если оно создано до verdict CAS отдельным будущим решением.

После substrate — один final-mix waveform experiment. Role-specific waveform,
transition density и multi-lane view требуют evidence реальной пользы.

Критерии приёмки:

- cache hit не запускает FFmpeg;
- crop точно следует normalized 0..1000 region;
- waveform не загружает весь final video в browser memory;
- cache key включает exact blob и extraction fingerprint;
- review UI не импортирует rendering internals;
- cold/warm latency и browser memory укладываются в budgets ниже.

Initial executable budgets on the documented CI/toolchain:

| Measurement | Fixture | Budget |
|---|---|---:|
| Cold lineage authorization | 101 rounds | ≤ 250 ms |
| Warm lineage authorization | same latest round | ≤ 10 ms |
| Cold first Range response | 100 MiB local artifact | ≤ 2 s |
| Warm first Range response | already verified artifact | ≤ 150 ms |
| Cold frame/crop extraction | 60 s, 1080p H.264 | ≤ 4 s |
| Warm extraction | same exact key | ≤ 100 ms and 0 FFmpeg launches |
| Extraction concurrency | concurrent cache misses | ≤ 2 FFmpeg processes |
| A/B browser memory delta | two 1080p artifacts, one active player | ≤ 150 MiB |

Budgets записываются в существующий performance report. Если CI hardware
показывает стабильный иной baseline, threshold меняется отдельным обоснованным
решением, а не отключением gate.

### Позже — только по наблюдаемой потребности

- voice note + transcript;
- resize/move spatial rectangle с клавиатуры;
- side-by-side/overlay compare;
- mobile composer bottom sheet;
- Frame.io/Dropbox Replay import/export adapter;
- HyperFrames `hfId` enrichment для HyperFrames-authored production.

## Что сознательно не строим

- Full NLE/editor внутри Studio v3.
- Fork или embed Frame.io/Kitsu/xSTUDIO/OpenRV/HyperFrames Studio.
- Parallel review database.
- Event bus, command bus, service locator или plugin marketplace.
- Автоматическое «угадывание», какой новый элемент соответствует старому.
- Cloud sync и multi-user workflow без отдельной реальной потребности.
- Canonical waveform/thumbnail как новый источник release trust.

## Порядок файлов и проверок

Ожидаемые владельцы изменений:

- `common/dlstudio/src/dlstudio/review/api.py` — unchanged verdict v3 и новый
  round/resolution contract;
- `common/dlstudio/src/dlstudio/workflow/api.py` — atomic completion port;
- `common/dlstudio/src/dlstudio/application/review.py` — read projections;
- `common/dlstudio/src/dlstudio/application/workflow.py` — review use case;
- `common/dlstudio/src/dlstudio/application/api.py` — public application seam;
- `common/dlstudio/src/dlstudio/persistence/api.py` — reserved key ownership;
- `common/dlstudio/src/dlstudio/persistence/workflow.py` — atomic state update;
- `common/dlstudio/src/dlstudio/adapters/http.py` — thin HTTP adapter;
- `common/dlstudio/src/dlstudio/adapters/cli.py` — transport equivalence;
- `common/dlstudio/src/dlstudio/rendering/api.py` — только Phase 5 extraction;
- `common/dlstudio/webui/src/review/`, `src/app.tsx` и
  `src/WorkflowDashboard.tsx` — task pack, resolution и A/B routing;
- `common/dlstudio/webui/package.json` и `package-lock.json` — browser test
  runner;
- `common/dlstudio/webui/src/api/openapi.v3.json` и `v3.gen.ts` — только через
  generator;
- `.github/workflows/tests.yml` и `tools/studio_v3_verify/` — browser gate и
  performance budgets.

Новые/расширенные focused tests:

- `common/dlstudio/tests/test_v3_review.py` — v3 golden + round codec;
- `common/dlstudio/tests/test_v3_application_workflow.py` — outcome table;
- `common/dlstudio/tests/test_v3_review_http.py` — POST CAS, lineage Range;
- `common/dlstudio/tests/test_v3_review_persistence.py` — atomicity/reopen;
- `common/dlstudio/tests/test_v3_review_task_pack.py` — fresh-process pack;
- `common/dlstudio/tests/test_v3_review_evidence.py` — Phase 5 cache/extract;
- existing `webui/test/v3-dashboard.test.mjs` остаётся fast source check;
- новый `webui/playwright.config.ts`;
- новые `webui/e2e/review-rounds.spec.ts` и
  `webui/e2e/review-compare.spec.ts` запускают built FastAPI/UI против
  temporary review-ready production.

Browser cases: accept-all/exception flow, old/current labels, hold/toggle,
different FPS/duration clamping, keyboard path, 1440×900, 1024×768, 390×844 и
320×700 без overflow. CI устанавливает только Chromium и выполняет
`npm run test:e2e` после build.

После каждой phase:

```powershell
common\dlstudio\.venv\Scripts\python.exe -m tools.studio_v3_verify `
  --profile cutover --scope full --skip-toolchain
```

UI дополнительно:

```powershell
cd common\dlstudio\webui
npm run generate:client
npm test
npm run typecheck
npm run build
npm run test:e2e
```

## Источники

Коммерческие:

- Frame.io:
  [comments/ranges](https://help.frame.io/en/articles/9105251-commenting-on-your-media),
  [exports](https://help.frame.io/en/articles/9105278-comments-panel-overview),
  [comparison](https://help.frame.io/en/articles/9952618-comparison-viewer),
  [API auth](https://next.developer.frame.io/platform/docs/guides/authentication/overview),
  [webhooks](https://next.developer.frame.io/platform/docs/guides/webhooks).
- Dropbox Replay:
  [feedback/export](https://help.dropbox.com/view-edit/dropbox-replay-feedback),
  [version comparison](https://help.dropbox.com/view-edit/dropbox-replay-compare-video-versions).
- SyncSketch:
  [comments/export](https://support.syncsketch.com/hc/en-us/articles/32393948568852-Using-SyncSketch-Comments),
  [timeline/waveform](https://support.syncsketch.com/hc/en-us/articles/32393850754196-Timeline-Navigation-and-Playback-Controls),
  [comparison](https://support.syncsketch.com/hc/en-us/articles/32393992531092-Compare-Items),
  [API](https://support.syncsketch.com/hc/en-us/articles/32394082877076-Getting-started-with-the-SyncSketch-API).
- Filestage:
  [comments](https://help.filestage.io/en/articles/7002949-commenting-on-files),
  [comparison](https://help.filestage.io/en/articles/5560093-compare-versions-of-a-file-directly-in-the-viewer),
  [API/webhooks](https://help.filestage.io/en/articles/6619493-self-serve-api-key-access).
- Wipster:
  [product](https://www.wipster.io/product),
  [comparison](https://www.wipster.io/blog/version-comparison).
- Vimeo:
  [review links](https://help.vimeo.com/hc/en-us/articles/12426192100113-How-to-use-and-manage-video-review-links),
  [versions](https://help.vimeo.com/hc/en-us/articles/12426058338961-How-to-manage-video-versions-and-access-history),
  [Comment API](https://developer.vimeo.com/api/reference/response/comment).

Open/local:

- xSTUDIO:
  [repository/license](https://github.com/AcademySoftwareFoundation/xstudio),
  [notes](https://github.com/AcademySoftwareFoundation/xstudio/blob/main/docs/user_docs/workflow/notes.rst),
  [timeline/OTIO](https://github.com/AcademySoftwareFoundation/xstudio/blob/main/docs/user_docs/interface/timeline.rst),
  [annotation API PR](https://github.com/AcademySoftwareFoundation/xstudio/pull/264).
- Kitsu:
  [repository](https://github.com/cgwire/kitsu),
  [review UI](https://kitsu.cg-wire.com/review/),
  [data models](https://dev.kitsu.cloud/references/data-models),
  [agent quickstart](https://dev.kitsu.cloud/start-here/agent-quickstart).
- OpenRV:
  [repository](https://github.com/AcademySoftwareFoundation/OpenRV),
  [OTIO integration](https://aswf-openrv.readthedocs.io/en/latest/rv-packages/rv-otio-reader.html),
  [session format](https://aswf-openrv.readthedocs.io/en/latest/rv-manuals/rv-reference-manual/rv-reference-manual-chapter-six.html).
- AYON:
  [backend/license](https://github.com/ynput/ayon-backend),
  [review sessions](https://help.ayon.app/en/help/articles/8669165-review-sessions),
  [API](https://docs.ayon.dev/api/).

HyperFrames:

- [repository](https://github.com/heygen-com/hyperframes);
- [Studio](https://hyperframes.app/docs/5-packages/studio);
- [timeline editing](https://hyperframes.heygen.com/guides/timeline-editing);
- [player API](https://github.com/heygen-com/hyperframes/blob/main/packages/player/README.md).

Studio v3:

- [Architecture](./ARCHITECTURE_V3.md);
- [Quickstart](./QUICKSTART_V3.md);
- [implemented UI/UX review](./STUDIO-V3-UI-REVIEW.md).
