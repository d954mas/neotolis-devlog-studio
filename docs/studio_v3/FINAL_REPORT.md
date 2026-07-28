# Studio v3 foundation — итоговый отчёт

Дата: 2026-07-28
Ветка: `codex/studio-v3-foundation`

## Результат

Studio v3 реализован как один локальный модульный монолит. Живой runtime
содержит 14 bounded modules и один production path:

```text
explicit production.toml
→ shared application use cases
→ WorkflowRun
→ exact review
→ complete immutable ReleaseCandidate
→ eligible delivery
→ DeliveryReceipt
```

CLI, FastAPI и UI используют одну application-layer реализацию. Пользователь
видит только `advance`, `review` или `deliver`; технические stage records нужны
для crash-safe resume, а не для ручного заполнения.

## Фазы 0–7

| Фаза | Итог |
|---|---|
| 0. Scope/recovery/harness | 5 project roots классифицированы; полный fail-closed inventory, canonical/architecture gates и recovery contract |
| 1. Foundation/persistence | Canonical encoding, immutable object store, roots/head CAS, writer lease и crash-safe commit |
| 2. Assets/migration | `AssetRevision` стал единственным владельцем media trust; ingest, evidence closure, GC и one-shot rehearsal реализованы |
| 3. Authoring/IR/render | Маленький v3 DSL, repository-resolved assets, replayable `TimelineIR`, pure checks и единственный FFmpeg renderer/cache |
| 4. Workflow/release | Typed `WorkflowRun`, resumable attempts, exact `ReviewVerdict`, complete frozen candidate, eligibility и receipt |
| 5. Adapters/dress rehearsal | Explicit manifest; эквивалентные CLI/API use cases; generated OpenAPI TypeScript client; workflow UI |
| 6. Cutover | Выполнены backup/restore и clone rehearsal; активные порты применены идемпотентно; v1/v2 runtime и one-shot migrator физически удалены |
| 7. Tightening | Cutover allowlist/ban gates, Windows/Linux CI matrix, performance budgets, package/UI checks; research исключён из core runtime |

## Миграция и безопасность данных

Final before-manifest:

- 5 project roots: 3 `MIGRATE_ACTIVE`, 2 `ARCHIVE_READ_ONLY`;
- 11 008 entries;
- 33 367 407 382 bytes;
- 4 327 327 714 source-media bytes;
- 0 unmatched, 0 ambiguous, 0 parse failures;
- actions: 3 064 archive, 3 938 migrate, 42 explicit port,
  3 964 recompute.

Фактический дополнительный peak для трёх независимых verified copies
(backup, restore rehearsal и migration clone): 100 573 793 391 bytes. На
reference volume в момент preflight было 133 346 467 840 bytes свободно;
budget прошёл.

Backup:

```text
C:\Users\ROG\.codex\visualizations\2026\07\26\
019f9e4a-ebec-7951-b9d9-0154ebf7b4ac\studio-v3-cutover\backup
```

- report: `docs/studio_v3/phase6/backup_report.json`;
- 11 008/11 008 entries verified;
- missing/extra/mismatched: 0/0/0;
- manifest SHA-256:
  `ff92b7bde893945d769d717508e5ea44b16503dfcbcc90e876f3813fde34f44e`.

Restore rehearsal скопировал bytes в отдельный empty destination и повторно
проверил те же 11 008 entries и тот же digest с нулём различий. Hardlinks не
считались backup. Исходные media/recordings не удалялись.

Restore target:

```text
C:\Users\ROG\.codex\visualizations\2026\07\26\
019f9e4a-ebec-7951-b9d9-0154ebf7b4ac\
studio-v3-cutover\restore-rehearsal-final
```

## Активные historical ports

На clone, затем на рабочем workspace применены три явных v3 authoring port:

| Production | Assets | Approval state | Timeline SHA-256 |
|---|---:|---|---|
| vertical `2026_07_18_reel_02` | 8 | 1 approved, 5 validated, 2 pending | `a4f0883e65fb829bbca2b0ca8aec177bc1e5e936889ca33af21de799a1860145` |
| long-form `2026_07_22_devlog_01` | 37 | 1 approved, 18 validated, 18 pending | `a06b37cd3af5ae259b3433abdbbc894639257220be651d083bcd2fc84e1c7ae8` |
| capture/VO `2026_07_17_devlog_01` | 47 | 23 validated, 24 pending | `66356b40da51c3de7a45c3ea7ec49517720bb1f547b79d1d16a5ab8393b6eff1` |

Первый apply ingested 92 revisions. Второй apply ingested 0 и reused все 92,
сохранив revisions и timeline hashes. Все три manifest открываются через v3,
authoring загружается/компилируется, а `status` возвращает canonical
`WorkflowStatus`.

Это не превращает неполные исторические доказательства в approved facts.
Полный release этих трёх исторических production честно заблокирован до
появления exact approval и license/redistribution evidence. Старые artifacts,
которые нельзя включить в v3 trust chain, сохранены read-only.

## Representative E2E

Один application path прошёл три полных synthetic release/delivery flow:

- vertical reel;
- long-form devlog;
- capture/VO с typed provenance, approval и creator-owned license.

Каждый flow выполняет prepare/check, draft render, final render, exact review,
package freeze, eligibility, local delivery и immutable receipt. Отдельные
negative tests блокируют pre-render failure, authoring identity mismatch,
arbitrary artifact delivery, stale/revoked candidate и delivery crash windows.

Historical port smoke отделён от synthetic trusted E2E: первый доказывает
корректность migration/load/compile/status, второй — полный release contract.
Эти доказательства намеренно не подменяют друг друга.

## Проверки

Локально на Windows прошли:

```text
147 v3 Python tests
architecture/import/allowlist gate: 42 files, 30 edges
executable quality-rule index: VQ-ASSET, VQ-LICENSE, VQ-MOTION, VQ-RES, VQ-SYNC
canonical vectors
4 behavioral performance hooks
generated OpenAPI client clean check
4 Web UI tests
TypeScript typecheck
Vite production build
full cutover verify
git diff --check
wheel build and wheel-origin static/API smoke
npm audit: 0 vulnerabilities
```

Финальный clean wheel:

```text
dlstudio-3.0.0-py3-none-any.whl
sha256 ee8067f05a33ee7a2710f5cc3c6514f1fd1eafcc5c47a052cf72c06cfa4fd78d
```

Full cutover gate запускался с зафиксированными Python 3.12.4 и Node 22.14.0,
а не только с локально доступными версиями по умолчанию.

GitHub Actions настроен выполнять тот же full cutover gate на:

- `windows-2022`;
- `ubuntu-24.04`;
- Python 3.12.4;
- Node 22.14.0.

Этот отчёт не утверждает, что hosted Linux job уже был запущен для финального
commit: в текущей локальной сессии подтверждён Windows gate и проверена
конфигурация двухплатформенной matrix.

## Performance

Reference machine: Windows, Python 3.12.4.

| Измерение | Runs | Результат |
|---|---:|---:|
| `dl2 --help`, cold process | 15 | cold 332.10 ms; p50 318.41 ms; p95 415.037 ms |
| status projection | 2 000 | p50 5.0108 ms; p95 9.0509 ms |
| unchanged compile/check | 300 | p50 0.1682 s; p95 0.2497 s |
| orchestration peak memory | — | 1 129 676 bytes |

Все значения ниже blocking budgets: CLI 800 ms, status 100 ms,
compile/check 0.5 s и memory 8 MiB.

## Ключевые commits

Foundation и vertical flow:

- `69a0140` — advance workflow through one application path;
- `b6e6e2f` — explicit local production;
- `0a5b27a` — complete application production flow;
- `b95552b` — three representative release flows;
- `d798eeb` — workflow UI.

Trust, reliability и упрощение:

- `3548f4c` — close workflow bypass and resume gaps;
- `ba4a6c0` — keep release constraints executable;
- `bd2f76d` — share renderer invariants;
- `b924585` — fail-closed asset migration;
- `c63f29f` — executable quality gates.

Migration safety:

- `a156963` — exclude generated roots;
- `b95ffce` — audit exclusions;
- `0cf0470` — bind exclusion evidence;
- `001a73d` — verified byte backup;
- `21ac109` — resumable recovery staging;
- `5b9218c` — complete backup source snapshot.

Cutover and final verification:

- `d977305` — physical v3-only runtime cutover;
- `31a5939` — installed-wheel and cross-platform CI gates.

Manifest, restore, active-port and final-review evidence lives beside this
report in its documentation commit.

## Remaining non-blocking risks

1. Historical production release остаётся intentionally blocked, пока владелец
   не добавит exact approval/license evidence. Это защита данных, а не runtime
   compatibility blocker.
2. Hosted Linux CI для финального commit должен быть подтверждён GitHub job;
   matrix и blocking command уже зафиксированы.
3. Absolute latency report относится к одной Windows reference machine;
   behavioral performance gates остаются платформенно-независимыми.
4. Research не входит в Studio core. Если он снова понадобится, его следует
   делать отдельным bounded package, не возвращать в runtime orchestration.

## Итог по поддерживаемости

Вместо старого набора команд, services и дублирующих JSON-процессов остались:

- один explicit manifest;
- один authoring file;
- один current workflow;
- один owner каждого trust fact;
- один FFmpeg renderer;
- один application path;
- одно следующее пользовательское действие;
- одна frozen release closure и один delivery path.

Новая функция должна добавляться в owning module и проходить через существующий
application seam. Если ей не нужна отдельная identity, persistence или
lifecycle, новая entity не создаётся.
