# AGENTS.md — Studio v3

Этот репозиторий использует только Studio v3. Перед изменением движка прочитайте
`docs/ARCHITECTURE_V3.md`, а перед первым запуском —
`docs/QUICKSTART_V3.md`.

## Главное

- Studio — локальный модульный монолит для одного владельца.
- Production всегда выбирается явно через `production.toml`.
- CLI, HTTP API и UI вызывают одни application-функции.
- Пользователь видит только следующее полезное действие:
  `advance`, `review` или `deliver`.
- Старые v1/v2 readers, команды, fallback-пути и параллельные runtime
  отсутствуют. Не добавляйте их обратно.
- Не создавайте service locator, command bus, event bus, plugin framework,
  универсальный repository layer или вторую реализацию процесса.

## Живой путь

Windows:

```powershell
.\dl2.bat --manifest <production>\production.toml status
.\dl2.bat --manifest <production>\production.toml serve
```

POSIX или установленный package:

```bash
./dl2 --manifest <production>/production.toml status
dl2 --manifest <production>/production.toml serve
```

Команды Studio v3:

- `status` — дешёвая проекция текущего `WorkflowRun`;
- `advance` — выполняет ровно следующий автоматический этап;
- `review --verdict <json>` — фиксирует verdict для exact final artifact;
- `deliver --destination-id <id>` — копирует готовый frozen candidate;
- `blob <sha256> <size>` — читает exact immutable object;
- `serve` — запускает тот же workflow через локальные API/UI.

Не придумывайте команды и флаги: проверяйте `dl2 --help`.

## Где что живёт

```text
common/dlstudio/src/dlstudio/
  foundation/   canonical bytes, IDs, BlobRef, ошибки
  authoring/    маленький Python DSL и explicit loader
  timeline/     replayable TimelineIR и pure checks
  rendering/    единственный FFmpeg graph/runner/cache
  assets/       AssetRevision и asset trust
  capture/      capture provenance contracts
  speech/       speech/take contracts
  review/       exact-artifact ReviewVerdict
  constraints/  canonical ConstraintSet
  workflow/     WorkflowRun и stage transitions
  release/      ReleaseCandidate и DeliveryReceipt
  application/  общие use cases для всех adapters
  persistence/  immutable objects, head transaction, writer lease
  adapters/     CLI, HTTP, local manifest и providers
```

Public cross-module imports идут через `<module>.api`. Domain-модули не
импортируют adapters или persistence. `foundation` не импортирует domain.
Разрешённые зависимости исполняемо заданы в
`tools/studio_v3_verify/config.json`.

## Владельцы фактов

| Факт | Единственный владелец |
|---|---|
| Авторский монтаж | `authoring.Edit` |
| Исполняемый монтаж | `timeline.TimelineIR` |
| Media/provenance/approval/license | `assets.AssetRevision` |
| Production constraints | `constraints.ConstraintSet` |
| Production progress | `workflow.WorkflowRun` |
| Review | `review.ReviewVerdict` |
| Публикуемый пакет | `release.ReleaseCandidate` |
| Доставка | `release.DeliveryReceipt` |

Не дублируйте эти факты в JSON-флагах, adapters, UI или новых registries.

## Правила изменения

1. Ищите существующего владельца поведения; добавляйте код туда.
2. Новый пользовательский action начинается с application use case, затем
   получает тонкие CLI/API/UI adapters.
3. Authoring хранит только творческое намерение. Он не может создавать
   approval, license или migration evidence.
4. Renderer принимает `TimelineIR` и object store; он не импортирует authoring.
5. Checks остаются чистыми: `TimelineIR + CheckPolicy -> CheckReport`.
6. Review обязан называть exact artifact, check report и constraints.
7. Delivery принимает только текущий eligible candidate и ничего не рендерит.
8. Не использовать `Path.cwd()`/`os.chdir()` в runtime.
9. Не добавлять old/new switch, compatibility reader или bypass delivery.
10. Не трогать и не удалять исходные media/recordings. Неизвестные исторические
    данные сохранять read-only.

## Проверки

После изменения runtime:

```powershell
common\dlstudio\.venv\Scripts\python.exe -m tools.studio_v3_verify `
  --profile cutover --scope full --skip-toolchain
```

Фокусные тесты можно запускать раньше, но они не заменяют full gate. Для UI:

```powershell
cd common\dlstudio\webui
npm run generate:client
npm test
npm run typecheck
npm run build
```

Generated `src/api/v3.gen.ts` не редактируется вручную. Если OpenAPI изменился,
перегенерируйте client и проверьте clean diff.

CI запускает тот же cutover gate на `windows-2022` и `ubuntu-24.04` с Python
3.12.4 и Node 22.14.0.

## Работа в общем workspace

- Сохраняйте чужие dirty/untracked изменения.
- Для поиска используйте `rg`/`rg --files`.
- Ручные правки делайте через `apply_patch`.
- Ставьте в commit только точные файлы своей задачи.
- После commit повторяйте релевантную проверку.
- Generated media, recordings, object store и delivery outputs не коммитятся.

## Расширение без бюрократии

- Новый layer/instruction: `authoring` → `timeline` → `rendering`, с canonical
  round-trip и render test.
- Новый asset origin: `assets` плюс ingest validation; не новый registry.
- Новый check: `timeline` и executable rule catalog; не отдельный service.
- Новый workflow stage нужен только если он представляет отдельный
  crash-resumable side effect или реальный пользовательский gate.
- Новый transport: тонкий adapter поверх существующего application use case.

Если задача решается обычной функцией в модуле-владельце, новая сущность или
framework не нужны.
