# Studio v3 — архитектура

Studio v3 — локальный модульный монолит для одного владельца. Его задача —
быстро провести production от небольшого Python authoring-файла до проверенного
immutable release и доставки. Архитектура намеренно не содержит микросервисов,
DI-контейнера, event bus, общего plugin framework, глобальной БД и
compatibility-layer.

## Простая пользовательская модель

У production есть один `WorkflowRun` и одно следующее действие:

```text
status
  ├─ action=advance ──► выполнить следующий автоматический этап
  ├─ action=review  ──► дать verdict по exact final artifact
  └─ action=deliver ──► скопировать уже frozen candidate
```

Внутренний порядок этапов:

```text
prepare → draft → final → review → package → deliver
```

`prepare`, `draft`, `final` и `package` запускаются одной командой `advance`.
Это не форма, которую надо вручную заполнять: stage record нужен для
idempotent resume после ошибки или завершения процесса. Пользователь вручную
участвует только там, где действительно требуется решение: exact review и
destination доставки.

## Модули и границы

```text
CLI / FastAPI / generated UI client
                  │
                  ▼
             application
       ┌──────────┼────────────┐
       ▼          ▼            ▼
   authoring   workflow     release/review/assets/constraints
       │          │            │
       ▼          └─────┬──────┘
    timeline ◄──────────┘
       ▲
       │
   rendering

persistence реализует файловое хранение;
adapters знают application и persistence;
domain не знает adapters.
```

| Модуль | Ответственность |
|---|---|
| `foundation` | Canonical encoding, IDs, `BlobRef`, общие ошибки |
| `authoring` | Маленький explicit Python DSL и loader одного `EDIT` |
| `timeline` | Canonical replayable `TimelineIR`, policy и pure checks |
| `rendering` | Единственный FFmpeg graph, runner, cache и postconditions |
| `assets` | Immutable `AssetRevision`, provenance, approval и license |
| `capture` | Typed capture request/receipt/provenance |
| `speech` | Typed take/speech-edit facts, создающие asset revisions |
| `review` | Immutable verdict, связанный с exact artifact |
| `constraints` | Единственный canonical `ConstraintSet` |
| `workflow` | Текущий run, attempts, resume и invalidation |
| `release` | Полный frozen candidate и delivery receipt |
| `application` | Общие команды и queries для CLI/API/UI |
| `persistence` | Object store, state root/head, CAS и writer lease |
| `adapters` | Parsing, HTTP presentation, manifest loading, providers |

Cross-module public API находится в `<module>/api.py`. Исполняемый gate
проверяет список разрешённых зависимостей, циклы, forbidden imports/calls и
точный allowlist runtime-пакета.

## Один владелец каждого факта

| Факт | Canonical owner | Допустимое производное |
|---|---|---|
| Творческое намерение | `authoring.Edit` | Compile input |
| Исполняемая timeline | `TimelineIR` | Graph, checks, render/cache key |
| Blob identity | `BlobRef` | Materialized object path |
| Media trust | `AssetRevision` | Snapshot внутри IR/candidate |
| Ограничения | `ConstraintSet` | Exact ref в checks/release |
| Прогресс | `WorkflowRun` | Read-only status projection |
| Review | `ReviewVerdict` | Exact ref в workflow/candidate |
| Release | `ReleaseCandidate` | Exact delivery manifest |
| Факт доставки | `DeliveryReceipt` | Read-only delivery status |
| API schema | Pydantic/OpenAPI | Generated TypeScript client |

Snapshot не становится вторым владельцем: он canonical и hash-bound к
владельцу. UI и CLI ничего из этого не вычисляют самостоятельно.

## Authoring, IR и render

Manifest выбирает один authoring-файл явно:

```toml
schema = "dlstudio.production"
version = 3
id = "example.reel"
authoring = "authoring.py"
delivery_root = "delivery"
```

Loader принимает только v3 `EDIT`. Dotted-module discovery, cwd fallback,
module-level migration evidence и compatibility constructors отсутствуют.
Application разрешает asset IDs через текущий `AssetRepository`; authoring не
может назначить себе approval или license.

Compiler превращает `Edit` и exact `AssetRevision` в `TimelineIR`. IR содержит
полные timing/geometry/audio instructions и immutable asset snapshots. В нём
нет Python callbacks, DSL handles, resolver keys или абсолютных machine paths.
Поэтому fresh process может проверить и отрендерить IR, не импортируя authoring.

Три разных identity не смешиваются:

- semantic — canonical hash `TimelineIR`;
- execution — IR плюс renderer/FFmpeg/runtime/options/assets;
- delivery — hash уже frozen output bytes.

FFmpeg — единственный backend. Cache rebuildable и не является источником
release trust.

## Assets и trust chain

`AssetRevision` связывает:

- logical asset ID и immutable media blob;
- probed media facts;
- provenance/capture method;
- evidence и approval state;
- license/redistribution/attribution;
- предыдущую logical revision.

Object store проверяет exact SHA-256 и size. Release использует только
достижимые из финального IR revisions и их evidence closure. Недостающие
approval/license facts блокируют release; система не заменяет их догадкой.

Checks — чистый вызов:

```text
TimelineIR + CheckPolicy → CheckReport
```

`CheckPolicy` ссылается на exact `ConstraintSet`. Blocking findings останавливают
FFmpeg и не позволяют создать render output.

## Workflow без процессной бюрократии

`WorkflowRun` — не task tracker и не журнал действий человека. Это маленький
immutable snapshot, необходимый для двух вещей:

1. после crash повторить stage без двойного visible side effect;
2. доказать, что review/package/delivery относятся к тем же exact inputs.

Каждый `StageAttempt` хранит operation ID, input refs, output refs и
success/failure. Изменение входа инвалидирует downstream и eligibility.
`status` читает только текущую проекцию: он не компилирует проект, не сканирует
media и не запускает subprocess.

## Review, release и delivery

`ReviewVerdict` создаётся application-layer из небольшого payload, но внутри
всегда связывается с exact:

- final artifact;
- check report;
- constraints;
- review scope и findings.

`package` повторно загружает canonical records из object store и создаёт
`ReleaseCandidate` только после проверки полной closure. Candidate включает
final video, TimelineIR, execution/options, checks, constraints, verdict,
reachable assets и generated `licenses.json`. После freeze его нельзя
дополнять.

Delivery:

1. проверяет current eligibility;
2. читает exact frozen package;
3. копирует и хеширует staging;
4. atomic-promote делает package видимым;
5. коммитит immutable `DeliveryReceipt`.

Она не рендерит и не патчит package. Pending delivery journal сначала
reconcile-ится, поэтому retry не создаёт вторую видимую доставку.

## Persistence

Canonical local state:

```text
data/.studio/
  objects/<sha256>
  state/roots/<root-hash>.json
  state/head.json
  state/pending_delivery.json
  staging/
  locks/
  outputs/
  cache/
```

Все большие и domain-записи immutable. Единственный обычный mutable canonical
pointer — `state/head.json`; он меняется same-directory replace под writer
lease и compare-and-swap. После crash достижим либо старый, либо новый valid
root. Orphan objects допустимы и удаляются только явным reachability GC.

## Как расширять

Расширение должно менять владельца факта и один seam, а не плодить framework:

- новая instruction: authoring type → canonical IR codec/check → renderer;
- новый asset origin: provenance validation в `assets`/`capture`/`speech`;
- новый check: правило в `timeline`, включённое в canonical policy;
- новый stage: только для отдельного resumable side effect или настоящего
  пользовательского gate;
- новый API action: application function → тонкие HTTP/CLI/UI adapters;
- новый provider: изолированный adapter, возвращающий typed domain result.

Если новое поведение не требует своей identity, persistence или lifecycle, ему
не нужна новая entity.

## Что физически отсутствует

После cutover нет `common/devlog`, старых `dl`/`dl.bat`, v2
`api/cache/check/cli/compile/model/render/services/template`, старых schema
readers, global resolver, compatibility policy, manual TypeScript mirrors,
runtime migrator и прямого final/delivery bypass.

Исторические bytes могут оставаться read-only данными, но ни один runtime path
их не читает.
