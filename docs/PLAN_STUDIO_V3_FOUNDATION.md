# Studio v3 — план фундаментального рефакторинга

Статус: **approved / converged — финальный gate-review PASS**  
Дата: 2026-07-26  
Область: `common/dlstudio`, `dl2`, Studio API/UI, production workflow,
assets/capture/evidence/review/release.

## 1. Решение

Studio v3 строится как **локальный модульный монолит для одного владельца**.
Это breaking-refactor без поддержки v1/v2-контрактов, runtime-миграций,
fallback-веток и параллельных реализаций одного процесса.

Цель — оставить минимальное ядро, в котором:

1. у каждого факта есть один владелец и один канонический формат;
2. зависимости направлены внутрь, CLI/API/UI являются тонкими адаптерами;
3. компиляция, проверки и рендер воспроизводимы без глобального состояния;
4. production workflow — типизированный автомат, а не набор команд и JSON;
5. side effects выполняются через единый crash-safe commit protocol;
6. публикуется только полный immutable release closure;
7. расширение добавляет owning module/handler, а не ветку в god-file;
8. старые контракты удаляются после одноразового offline cutover.

## 2. Зафиксированные ограничения

| Вопрос | Решение |
|---|---|
| Пользователи | Один локальный владелец. Нет auth, RBAC, tenancy и server orchestration. |
| Deployment | Windows — основной runtime; Linux — CI и проверка переносимости. |
| Архитектура | Модульный монолит. Не микросервисы и не общий plugin framework. |
| Render backend | Только FFmpeg; graph и runner имеют одного владельца. |
| Authoring | Python DSL. GUI не является альтернативным timeline editor. |
| DSL migration | Публичный v2 DSL не сохраняется. Активные edit-модули портируются явно и проверяются по одному; произвольный Python автоматически не переписывается. |
| Совместимость | Старые API, CLI, schema readers и fallback удаляются. |
| Миграция | Один offline-migrator для данных плюс явный port активных edit packages. Runtime старые форматы не читает. |
| Persistency | Immutable objects/revisions + один atomic production head; глобальная БД не нужна. |
| Concurrency | Один production writer lease; отдельные per-key locks только у render cache. |
| Расширение | Через domain API и application handlers, не через импорты CLI/API или service locator. |
| Capture | Studio владеет request/receipt/provenance validation/ingest. Реальная запись gameplay остаётся внешним agent/provider process. |
| Research | Вне критического пути v3; отдельный bounded package, не импортируемый Studio core. |

## 3. Что сохраняем

- Кодовый DSL как git-friendly и agent-friendly authoring.
- Контур `DSL → compile → IR → check → FFmpeg`.
- Content-addressed render cache и раздельные beat/video/VO artifacts.
- Mechanical pre-render checks, render postconditions и VQ-каталог.
- Compact review evidence, hash-bound feedback и bounded improve loop.
- Word timing, capture provenance, production manifests и delivery evidence
  как предметные понятия — но не их текущие схемы.
- FastAPI/Vite; смена стека не решает архитектурные проблемы.

## 4. Почему v2 трудно поддерживать

1. `cli/autopilot.py`, `services/capture_batch.py`,
   `services/speech_edit.py`, `api/app.py`, `services/asset_registry.py`
   совмещают transport, state, policy, IO и orchestration.
2. Render зависит от глобального chunk resolver и исходного DSL object graph;
   JSON IR не является автономно исполняемым.
3. Checks читают filesystem/services/`Path.cwd()`, поэтому имеют скрытые inputs.
4. Run JSON, manifests, catalog/registry, feedback и evidence дублируют status
   и trust state; CLI/API способны вычислить их по-разному.
5. Check, exact review, package и delivery не образуют один hash-bound closure;
   mutable файлы создают bypass и TOCTOU.
6. Python DTO, JSON, TypeScript types и UI state описываются вручную несколько раз.
7. `cwd/chdir`, eager re-exports и отсутствие import rules размывают реальные
   границы и замедляют cold start.
8. Основной runtime Windows, но CI проверяет прежде всего Ubuntu и не
   воспроизводит реальные process/locking semantics.

## 5. Единственный источник истины

«Один источник» означает одного владельца каждого класса фактов. Snapshots и
projections допустимы только как hash-bound или полностью rebuildable данные.

| Факт | Канонический владелец | Допустимое производное |
|---|---|---|
| Авторский timeline | Python DSL (`authoring`) | compiled usage в IR |
| Исполняемый timeline | Versioned `TimelineIR` (`timeline`) | graph, reports, cache keys |
| Blob identity | `BlobRef` по content hash (`assets`) | materialized path |
| Media/provenance/license | Immutable `AssetRevision` (`assets`) | hash-bound snapshot в IR/candidate |
| Production constraints | Immutable `ConstraintSet` (`constraints`) | exact ref в policy/workflow/candidate |
| Production progress | `WorkflowRun` (`workflow`) | CLI/API/UI projection |
| Review findings/change requests | Immutable `ReviewVerdict` (`review`) | refs + resolution state в workflow |
| Publishable release | Immutable `ReleaseCandidate` (`release`) | delivery copy |
| Факт доставки | Immutable `DeliveryReceipt` (`release`) | delivery status projection |
| API schema | Pydantic application DTO/OpenAPI | generated TypeScript client/types |
| Quality metadata/logic | Исполняемый rule catalog (`timeline.checks`) | generated/validated Markdown index |

Инварианты:

- DSL редактируется; IR никогда не редактируется вручную.
- `AssetRevision` владеет hash, probe facts, provenance, approval и license.
- IR содержит только точные `AssetRevisionRef` и hash-bound snapshots,
  достижимые из compiled timeline.
- Asset reverse-usage index — rebuildable projection, не поле trust ledger.
- `CheckPolicy` содержит ruleset/platform/constraints/profile, но не повторяет
  asset probes. Checks используют snapshots IR; render postconditions —
  immutable output facts.
- `ReviewVerdict` владеет текстом findings/requests. `WorkflowRun` хранит refs
  и состояние разрешения, не копии findings.
- `ConstraintSet` владеет содержанием, revisions и resolution constraints.
  Check policy, workflow и candidate содержат только exact refs/hash snapshots.
- Candidate содержит только достижимые asset/package refs, а не hash всего
  глобального ledger.
- Canonical state записывает только owning repository; прямые записи в его
  paths запрещены architecture tests.

## 6. Storage и commit model

### 6.1. Immutable objects + один head

```text
data/.studio/
  objects/<sha256>                 immutable blobs и canonical records
  state/roots/<root-hash>.json     immutable production state roots
  state/head.json                  единственный mutable pointer
  staging/<operation-id>/          незавершённые операции
  locks/production.writer          один writer lease
```

`ProductionStateRoot` содержит refs на текущие revisions конфигурации,
`AssetIndex`, `WorkflowRun` и другие canonical records. Обновление:

1. записывает и проверяет immutable objects;
2. записывает новый immutable state root;
3. под writer lease проверяет expected head revision;
4. делает same-directory `os.replace` маленького `head.json`.

Crash оставляет достижимым либо старый, либо новый целостный root. Orphan
objects допустимы и очищаются только явной reachability-GC командой. Dangling
canonical refs запрещены.

Локальные абсолютные bindings (`game_root`, tools, workspace paths) живут в
`ProductionContext`/machine config, не входят в portable state и semantic IDs.

### 6.2. Единый operation commit protocol

Любая операция с side effect использует storage-level primitive:

```text
prepare opaque operation record
→ execute into operation-specific staging/content store
→ verify hashes + postconditions
→ publish immutable outputs
→ commit new production root
```

Domain-aware `WorkflowRun`/`StageAttempt` поверх этого primitive появляется в
Фазе 4. Storage Фазы 1 ничего не знает о stages.

`operation_id` включает:

- production/run/stage identity;
- canonical input refs;
- stage contract и schema version;
- implementation/source fingerprint;
- applicable policy и toolchain fingerprints.

Resume обязан корректно обрабатывать crash:

- до side effect;
- во время staging;
- после immutable publish, до run commit;
- после commit;
- при Ctrl-C/termination дочернего FFmpeg.

Итог всегда один: один visible committed output, один committed operation,
никакого trusted partial state. Workflow layer дополнительно гарантирует один
committed attempt. External operations получают стабильный idempotency key,
если поддерживают его.

### 6.3. Locking

- Один production writer lease сериализует изменения canonical production state.
- Render workers параллельны и используют per-key cache locks.
- Reads lock-free через immutable root.
- Multi-production операция, если появится, использует канонический порядок
  production IDs.
- Locks проверяются реальными Windows spawned processes, не только threads.

## 7. Целевая модульная структура

```text
common/dlstudio/src/dlstudio/
  foundation/              # IDs, canonical encoding, schema envelope, errors
  authoring/               # Python DSL и loader
  timeline/                # IR, compiler, pure checks, internal IR invariants
  rendering/               # FFmpeg graph/runner, raster, cache, postconditions
  assets/                  # BlobRef, AssetRevision, index, ingest contracts
  capture/                 # request/receipt/provenance; запись остаётся внешней
  speech/                  # take/speech-edit domain, производит AssetRevision
  review/                  # review pack и immutable ReviewVerdict
  constraints/             # immutable production ConstraintSet
  workflow/                # typed runs, stage graphs, attempts, invalidation
  release/                 # package closure, candidate, delivery
  application/             # commands, queries, DTO, cross-context reconciliation
  persistence/             # filesystem repositories, head transaction, writer lease
  adapters/
    cli/
    api/
    hyperframes/
    providers/
```

`webui/` — отдельный TypeScript package, использующий только generated client.
`research` выносится в отдельный package/workstream после core cutover.

### 7.1. Направления зависимостей

```text
CLI / API / UI
       │
       ▼
 application ─────► workflow / release / review / constraints / assets / capture / speech
       │                              │
       ├──────────► authoring ─────► timeline
       └──────────► rendering ─────► timeline

 persistence реализует repository contracts модулей;
 domain-модули не импортируют persistence или adapters.
 foundation не импортирует ни один domain module.
```

Уточнения:

- `rendering` — единственный владелец FFmpeg graph и process runner; отдельного
  `adapters/ffmpeg` и общего `foundation/process.py` нет.
- `rendering` принимает `TimelineIR`, execution fingerprint и explicit options.
- Cross-context reconciliation `manifest ↔ IR ↔ assets` живёт в `application`
  или `release`, не в чистом `timeline`.
- Capture/speech создают `AssetRevision` через публичный assets contract.
- CLI/API вызывают только application commands/queries.
- Public cross-module доступ идёт через узкий `api.py`; deep imports запрещены.

### 7.2. Не вводить

- DI container/service locator;
- event bus/event sourcing/saga framework;
- универсальный plugin registry;
- repository abstraction на каждый dataclass;
- второй renderer;
- глобальную SQL БД;
- runtime flags старого/нового пути.

## 8. Ключевые контракты

### 8.1. `ProductionContext`

Immutable object на application boundary:

```python
ProductionContext(
    workspace_root=...,
    project_root=...,
    production_id=...,
    paths=ProductionPaths(...),
    machine_bindings=...,
    clock=...,
)
```

Заменяет `Path.cwd()`, `os.chdir` и повторный workspace discovery. Не содержит
mutable status и не является service locator.

### 8.2. `AssetRevision`

- `AssetId` — логическая роль;
- `BlobRef` — immutable bytes;
- media facts;
- origin/capture method;
- state/build/native geometry;
- script hash для voice take;
- validation/approval;
- license/attribution;
- canonical revision hash.

Ingest order: temp write → hash/media verify → fsync → atomic blob publish →
writer lease/CAS → immutable AssetRevision/index → new production head.
Orphan blob безопасен; ledger ref на отсутствующий blob невозможен.

### 8.3. `TimelineIR`

- versioned canonical serialization;
- разрешённые times/layers/raster instructions/audio graph;
- точные `AssetRevisionRef` и необходимые snapshots;
- никаких callback, Python handles, resolver keys, absolute machine paths;
- fresh-process render только из IR + immutable object store.

Canonical encoding:

- UTF-8, Unicode NFC;
- stable field order; lists ordered by domain semantics;
- finite floats с зафиксированным representation;
- normalized logical paths, без drive letters;
- timestamps и host paths исключены из semantic identity;
- schema version и domain separator входят в hash;
- golden canonical bytes/hash одинаковы на Windows/Linux.

Различаются:

1. **semantic identity** — canonical IR hash;
2. **execution identity** — IR + renderer source hash + FFmpeg build/version +
   raster/layout version + fonts/assets + codec/runtime options;
3. **media equivalence** — ffprobe/frame/audio metrics с tolerances;
4. **delivery identity** — hash уже frozen output bytes, без повторного render.

Cache key строится по execution identity, не только по IR.

### 8.4. Checks

Timeline rule — deterministic function:

```text
TimelineIR + CheckPolicy → Findings
```

`CheckPolicy` содержит ruleset, platform policy, known constraints и profile.
Rule не читает filesystem, environment, services и cwd.

Output postcondition:

```text
OutputArtifactRef + immutable media facts + policy → Findings
```

Quality rule metadata и implementation имеют один canonical registry; Markdown
index генерируется или валидируется из него.

`ConstraintSet` — immutable canonical record с production constraints, source,
revision и resolution policy. `CheckPolicy` ссылается на его exact revision.

### 8.5. `ReviewVerdict`

Каждый verdict неизменяемо связывает:

- exact `OutputArtifactRef` и SHA-256 reviewed bytes;
- refs review pack/evidence, использованные reviewer;
- review policy и schema version;
- reviewer identity/role;
- timestamp;
- findings/change requests и verdict.

Candidate validation обязана доказать, что artifact ref verdict точно равен
финальному output ref candidate. Stale verdict не может быть разрешён вручную:
требуется новый review.

### 8.6. `WorkflowRun`

- `run_id`, `revision`, `production_id`;
- typed `stage_graph` для reel/long-form/silent-VO;
- `current_stage`;
- `StageAttempt(operation_id, input_refs, output_refs, state, duration, error)`;
- refs на verdicts/requests и их resolution state;
- terminal outcome.

Переходы определены статическими typed graphs, а не plugin engine. Повтор:

- возвращает committed output при тех же input refs;
- создаёт новый attempt при изменении;
- не перепрыгивает gate;
- инвалидирует downstream при новом request/input;
- reconciles опубликованный output после crash до state commit.

Operation identity и invalidation включают stage contract/schema,
implementation fingerprint и applicable policy/toolchain hashes. Обновление
stage code не может переиспользовать старый derived output.

### 8.7. `ReleaseCandidate` и `DeliveryReceipt`

Release flow:

```text
final IR
→ exact checks
→ final render + postconditions
→ exact review
→ known-constraints regression
→ build complete package in staging
→ publish every package file as immutable blob
→ validate complete reachable closure
→ freeze canonical ReleaseCandidate
→ deliver exact frozen closure
```

Candidate содержит refs на IR, execution fingerprint, final outputs, exact
reports/verdict, resolved constraints, reachable AssetRevisions, license bundle
и **все** package files.

`candidate_id = hash(canonical candidate payload)`.

Immutable candidate не равен текущему разрешению на delivery. Production head
хранит `eligible_candidate_ref`; новый request/input/revocation очищает его.

`deliver(candidate_id)` ничего не генерирует и не патчит. Перед side effect он:

1. захватывает production writer lease и удерживает его до receipt/head commit;
2. под lease/CAS проверяет, что current head всё ещё разрешает exact candidate
   и не содержит unresolved blockers;
3. читает frozen blobs, одновременно хеширует sibling staging copy;
4. сверяет полный manifest и делает atomic promote;
5. публикует immutable `DeliveryReceipt`, связанный с candidate ID,
   destination identity и hashes скопированного manifest;
6. коммитит receipt ref в новый production head и только затем освобождает lease.

Retry reconciles существующий receipt/staging и не дублирует visible output.
Если process упал после promote, но до receipt, recovery обязана проверить
promoted destination и завершить/заблокировать исходную delivery transaction
**до любой следующей canonical mutation**, включая revocation. Поэтому уже
видимый authorized promote не может задним числом остаться без receipt, а
concurrent revocation не проходит между eligibility check и commit.
Для unreconcilable non-idempotent external targets workflow создаёт blocking
recovery checkpoint, а не угадывает результат. Mutation source после freeze не
меняет candidate, а mutation current head может отозвать право на delivery.

## 9. Production flow

```text
resolve context
→ inventory/validate assets
→ compile immutable IR
→ mechanical checks
→ draft render/review pack
→ author checkpoint
→ resolve change requests
→ final compile/exact checks
→ final render/postconditions
→ exact artifact review
→ known-constraints gate
→ build and validate package closure
→ freeze ReleaseCandidate
→ deliver frozen candidate
```

Новый change request инвалидирует downstream attempts независимо от момента
появления. Shot manifest и script/take provenance reconciled с финальным IR.

`dl2 final` как bypass исчезает:

- `render-final` создаёт непубликуемый artifact;
- `release` создаёт candidate после всех gates;
- `deliver <candidate-id>` — единственный delivery path.

## 10. План реализации

Временное сосуществование допустимо только в refactor branch/worktree:
старый runtime служит oracle, новый запускается внутренним v3 harness.
Runtime feature switch отсутствует. Cutover — один короткий commit.
Rollback — git tag + восстановление data snapshot, не fallback-код.

### Фаза 0. Scope, recovery contract и quality harness

1. Классифицировать **каждый** project root:
   `MIGRATE_ACTIVE`, `ARCHIVE_READ_ONLY`, `DELETE_CONFIRMED`.
2. Создать disposition matrix:
   `old path/schema → target owner → port/migrate/recompute/archive/drop`.
3. Отдельно покрыть:
   product/production TOML; edit Python; registry/catalog/capture; story/shot/
   script; recordings/words/speech edit; review; publish/licenses/delivery;
   finalize/cache; HyperFrames sources/manifests; local scripts/docs.
4. Выбрать representative vertical, long-form и capture/VO productions.
5. Зафиксировать semantic baselines: IR/graph, ffprobe, selected frames,
   audio fingerprints и check reports. MP4 hash — identity конкретного artifact,
   не cross-platform pixel-parity oracle.
6. Зафиксировать v3 schemas, canonical vectors, atomic head и recovery protocol.
7. Создать skeleton migrator с dry-run/disposition report в
   `tools/studio_v3_migrate/`, вне importable runtime package.
8. Выполнить backup/restore rehearsal на копии данных.
9. Поднять Windows+Linux Python 3.12 CI, canonical locked install и один
   `dl2 verify`-эквивалент для v3.
10. Добавить architecture gates и внутренний v3 harness без изменения `dl2`.

Exit:

- 100% project roots и известных artifact patterns классифицированы;
- generated before-manifest перечисляет каждый in-scope file/record; каждый
  элемент совпадает ровно с одним disposition rule;
- unmatched paths, parse failures и ambiguous matches fail closed;
- стратегия каждого активного edit package: explicit port;
- backup восстановлен, source media hashes совпали;
- рассчитаны disk/hardlink/copy budgets;
- Windows/Linux baseline green;
- canonical vectors и import rules blocking;
- cutover/recovery transaction утверждена до production code.

### Фаза 1. Foundation, context и state transaction

1. Реализовать canonical encoding, IDs, schema envelope, error taxonomy.
2. Ввести `ProductionContext` и portable/local config separation.
3. Реализовать immutable objects, state roots, head CAS и writer lease.
4. Реализовать opaque operation staging и atomic root commit primitive без
   зависимости от `WorkflowRun`.
5. Убрать `cwd/chdir` из нового пути.
6. Добавить real-process Windows/Linux crash/locking tests.

Exit:

- crash до/после head swap оставляет старый либо новый valid root;
- stale writer получает CAS conflict;
- два contexts работают в одном процессе;
- spawned writers не создают partial canonical state;
- v3 harness использует только новый storage contract.

### Фаза 2. Asset identity, store и migration rehearsal

1. Реализовать `BlobRef`, `AssetRevision`, immutable index revisions.
2. Реализовать ingest protocol и explicit reachability GC.
3. Перенести capture/speech provenance и script hash binding.
4. Сделать translator старых asset/capture/control schemas.
5. Добавить hardlink-on-same-volume и verified-copy-on-other-volume policy.
6. Выполнить dry-run/apply/re-run/crash matrix на clone активных data.

Exit:

- source bytes не меняются;
- повторный apply не создаёт side effects;
- interrupted ingest не публикует dangling revision;
- disk preflight точен;
- все active asset refs переведены или явно заблокированы;
- projections удаляются и rebuild дают тот же canonical result.

### Фаза 3. Authoring port, replayable IR и render kernel

1. Сформировать финальный v3 DSL без compatibility constructors.
2. Явно портировать representative edit packages.
3. Реализовать canonical `TimelineIR` с `AssetRevisionRef`.
4. Компилировать все raster/decorations/anims в serializable instructions.
5. Удалить global resolver/lock из нового renderer.
6. Перевести checks на pure contracts.
7. Реализовать `render(ir, execution_fingerprint, options, store)`.
8. Привязать cache к полной execution identity.

Exit:

- каждый representative edit компилируется новым authoring path;
- IR рендерится fresh-process без импорта edit module;
- parallel edits не разделяют mutable state;
- canonical hashes совпадают Windows/Linux;
- semantic media/graph regressions в tolerance;
- timeline/rendering не импортируют workflow/application/adapters.

### Фаза 4. Workflow и release как один вертикальный flow

1. Реализовать typed stage graphs, attempts, invalidation и repository поверх
   storage-level operation primitive.
2. Разнести stages в application handlers.
3. Перенести author/check/draft/final/review/constraints/package.
4. Реализовать immutable `ReviewVerdict` и request resolution refs.
5. Реализовать complete package closure и `ReleaseCandidate`.
6. Оставить единственный `deliver(candidate_id)`.
7. Реализовать delivery eligibility и immutable `DeliveryReceipt`.
8. Fault-injection на каждом stage и TOCTOU window.

Exit:

- kill/restart проходит на каждой границе stage protocol;
- duplicate resume не дублирует visible side effects;
- request/mutation инвалидирует downstream;
- произвольный MP4 нельзя доставить;
- package после freeze не изменяется и не дополняется;
- stale/revoked candidate не доставляется;
- retry delivery reconciles receipt и не дублирует visible output;
- fault test `promote → crash → revocation/retry` сначала reconciles delivery
  и только затем разрешает новую canonical mutation;
- legacy release либо read-only archive, либо проходит новый release.

### Фаза 5. Тонкие adapters и dress rehearsal

1. CLI оставить parsing/use-case/presentation.
2. FastAPI разбить на routers без domain logic.
3. Генерировать TS client/types из OpenAPI; удалить manual mirrors.
4. Status queries читать projection, не compile/recursive scans.
5. Изолировать HyperFrames/providers.
6. Полностью портировать активные edit packages.
7. На clone выполнить migration dry-run → apply → verify → second apply.
8. Провести full release трёх representative productions и restore rehearsal.

Exit:

- CLI/API дают эквивалентный результат одного use case;
- generated client имеет clean diff;
- active edits работают только через v3 DSL;
- clone full release/delivery green;
- second migration apply idempotent;
- rollback восстанавливает exact before manifest;
- неизвестных данных и ручных migration steps не осталось.
- generated manifest покрывает каждый in-scope entry ровно одним disposition.

### Фаза 6. Cutover и физическое удаление

1. Остановить Studio/render writers.
2. Создать final before-manifest, disk preflight и verified backup.
3. Выполнить one-shot data migration и switch production head.
4. Переключить `dl2`/Studio entrypoints одним commit.
5. Выполнить smoke + representative full release.
6. Удалить v1/v2 schemas/readers/API/CLI, `common/devlog`, старый `dl`,
   compatibility policy, global resolver, old autopilot, manual TS types.
7. Удалить или архивировать external migration/harness tools; runtime никогда
   их не импортирует, что проверяется import-ban gate.
8. Старые releases оставить только как bytes/read-only archive вне v3 runtime.
9. Обновить AGENTS/Quickstart/Architecture до одной системы.

Exit:

- все active projects открываются только v3;
- media hashes совпадают с before manifest;
- новый full release проходит после cutover;
- old runtime физически отсутствует;
- banned imports/symbols/commands/schema readers отсутствуют;
- docs описывают только v3.

### Фаза 7. Tightening, performance и отдельный research decision

Quality не появляется здесь — gates действуют с Фазы 0. Эта фаза:

1. ужесточает budgets по накопленным измерениям;
2. удаляет оставшиеся временные test hooks; migrator никогда не находился в
   runtime package и уже удалён/архивирован в Фазе 6;
3. добавляет architecture/rule index generation;
4. принимает отдельное решение: удалить research surface или вынести package;
5. документирует extension recipes.

## 11. Workstreams и зависимости

| Workstream | Владеет | Зависит от |
|---|---|---|
| Verification | CI, fixtures, architecture, crash/perf gates | стартует первым |
| Foundation/persistence | context, canonical, objects/head, lease | contracts Фазы 0 |
| Asset trust | blob/revision/ingest/migration | foundation/persistence |
| Timeline/render | DSL, compiler, IR, checks, FFmpeg/cache | frozen AssetRef |
| Workflow/release | attempts, invalidation, review, closure/delivery | storage + IR/assets |
| Adapters | CLI/API/generated UI client | application contracts |

Timeline и Render могут идти параллельно только после freeze
`AssetRevisionRef/TimelineIR` contracts. Общие `utils` запрещены: примитив
принадлежит owning domain либо проходит строгий критерий `foundation`.

## 12. Blocking gates

### Каждый PR, Windows + Linux

- locked Python 3.12/Node environment;
- pure unit и architecture/import rules;
- canonical serialization vectors;
- state-machine properties;
- repository contracts;
- real spawned-process locks/crash recovery;
- compact real-FFmpeg synthetic E2E;
- generated OpenAPI client clean.

### Перед cutover

- три representative E2E;
- migration clone dry-run/apply/re-run/fault/restore;
- release trust-DAG и mutation во всех TOCTOU windows;
- generated before-manifest: каждый in-scope entry имеет ровно один disposition,
  unmatched/ambiguous/parse-failed = 0;
- banned runtime surface scan;
- reference-machine performance report.

### Автоматическое доказательство SSOT

- canonical paths пишет только owning repository;
- stale revision/CAS write отвергается;
- projections/cache можно удалить и rebuild;
- CLI/API/UI status равны одной projection из `WorkflowRun`;
- workflow status вне `WorkflowRun` и asset trust вне `AssetRevision` запрещены;
- candidate reachability не включает unrelated ledger objects.
- verdict artifact ref совпадает с candidate output ref;
- delivery receipt связан с current eligible candidate и exact copied manifest.

Лимит 400 строк остаётся warning, не архитектурным gate. Blocking metrics:
cycles, forbidden imports/writes, fan-in/fan-out, public surface и complexity.

## 13. Performance contract

CI проверяет прежде всего поведение:

- status не запускает compile, recursive scan, subprocess и full-media read;
- cache hit не запускает FFmpeg и не читает media целиком;
- import CLI/API не загружает heavy providers;
- review pack имеет bounded items/bytes независимо от общего числа keyframes.

Абсолютные ceilings в hosted CI намеренно широкие. Строгие p50/p95 измеряются
fresh/warm на зафиксированной Windows reference machine: одинаковый fixture,
toolchain, число прогонов и statistic сохраняются вместе с report.

Начальные targets после baseline:

- `dl2 --help`: p95 ≤ 800 ms cold, ≤ 300 ms warm;
- status query: p95 ≤ 100 ms warm;
- unchanged reel compile/check: p95 ≤ 500 ms;
- review pack: фиксированный cap по frames/bytes;
- orchestration memory: фиксированный cap на representative fixture.

Budget меняется только ADR с before/after measurements.

## 14. Что удаляется

Не общий поиск слова `fallback`, а утверждённый machine-readable ban list:

- старые package imports и entrypoints;
- v1/v2 schema readers и constructors;
- `asset_policy="compatibility"`;
- path/dotted-module fallback production loading;
- global chunk resolver;
- direct final/delivery bypass;
- raw dict autopilot state;
- catalog/registry competing writes;
- ручные TS mirrors;
- `cwd/chdir` в domain/application;
- старые CLI commands/flags;
- runtime migration adapters.
- imports из `tools/studio_v3_migrate`/временного harness в runtime.

Содержательные fallback внутри внешнего provider могут существовать только как
явная domain policy нового контракта; скрытый compatibility fallback запрещён.

## 15. Definition of Done

1. Финальный IR проверяется и рендерится fresh-process без DSL/resolver.
2. CLI/API/UI вызывают одни application use cases.
3. Status существует только в `WorkflowRun`.
4. Asset trust существует только в `AssetRevision`.
5. Публикуется только полный immutable `ReleaseCandidate`.
6. Verdict доказуемо относится к exact final artifact candidate.
7. Delivery требует current eligibility, ничего не генерирует, копирует exact
   frozen closure и коммитит immutable receipt.
8. Старый schema/API/CLI/fallback отсутствует в runtime.
9. Windows/Linux blocking gates проходят.
10. Active vertical, long-form и capture/VO productions проходят port,
   migration, release и delivery.
11. Architecture/performance budgets блокируют regressions.
12. Новый check, asset origin, stage или API command меняет owning module и
    application/adapter seam, а не orchestration god-files.

## 16. Решения независимого review

План проверили три независимых сабагента:

1. **Architecture/SSOT:** потребовал убрать дубли facts между IR, checks,
   ledger, review и workflow; исправить ownership FFmpeg/reconciliation;
   строить package до candidate freeze.
2. **Migration/cutover:** обнаружил неверный порядок AssetRef/IR; потребовал
   явный port Python DSL, полный disposition inventory, ранний migrator и один
   atomic production head.
3. **Verification/reliability:** перенёс CI/performance harness в Фазу 0;
   уточнил stage commit protocol, real-process locks, determinism levels и
   immutable delivery closure.

Первый финальный gate-review нашёл дополнительные проблемы владения constraints,
artifact binding verdict, delivery eligibility/receipt, fail-closed inventory,
границы migrator и derivation identity. После revision 3 тот же reviewer
повторно проверил исправления и дал **PASS: остаточных BLOCKER/HIGH нет**.

## 17. Порядок старта после утверждения

1. Создать refactor branch/worktree.
2. Выполнить только Фазу 0.
3. Представить disposition matrix, target schemas, recovery rehearsal и
   baseline report как отдельный approval gate.
4. После утверждения реализовывать Фазы 1–6 последовательно.

Новые функции до стабилизации Фаз 1–4 не добавляются, кроме исправлений,
необходимых для достоверного baseline или текущего выпуска.
