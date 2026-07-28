# Studio v3 — быстрый старт

Studio v3 показывает одно следующее действие и хранит технические
доказательства автоматически. Самый простой путь — локальный UI; CLI нужен для
скриптов и диагностики.

## 1. Окружение

Нужны:

- Python 3.12;
- FFmpeg/ffprobe в `PATH`;
- Node 22 только для разработки Web UI.

Windows:

```powershell
py -3.12 -m venv common\dlstudio\.venv
common\dlstudio\.venv\Scripts\python.exe -m pip install -e "common\dlstudio[dev]"
.\dl2.bat --help
```

POSIX:

```bash
python3.12 -m venv common/dlstudio/.venv
common/dlstudio/.venv/bin/python -m pip install -e 'common/dlstudio[dev]'
./dl2 --help
```

## 2. Production состоит из двух входных файлов

`production.toml`:

```toml
schema = "dlstudio.production"
version = 3
id = "example.reel"
authoring = "authoring.py"
delivery_root = "delivery"
```

`authoring.py`:

```python
from dlstudio.authoring.api import Edit, SolidLayer

EDIT = Edit(
    production_id="example.reel",
    width=1080,
    height=1920,
    fps_num=30,
    fps_den=1,
    duration_ns=3_000_000_000,
    background="#0b0d12",
    visuals=(
        SolidLayer(
            start_ns=0,
            duration_ns=3_000_000_000,
            z=0,
            x=0,
            y=0,
            width=1080,
            height=1920,
            color="#0b0d12",
        ),
    ),
    standalone_story="Одна ясная мысль за три секунды.",
    kind="reel",
)
```

`TextLayer`, `MediaLayer` и `AudioClip` ссылаются на logical asset ID.
Соответствующий `AssetRevision` должен уже существовать в production object
store. Authoring не содержит approval, license или migration evidence.

## 3. Рекомендуемый путь: UI

```powershell
.\dl2.bat --manifest path\to\production.toml serve
```

Откройте `http://127.0.0.1:8788`. Экран показывает:

- текущий stage;
- последний failure, если он есть;
- одно следующее действие;
- exact review form только на review;
- destination form только на delivery.

`Advance workflow` выполняет один автоматический этап. После ошибки исправьте
вход и нажмите снова: committed outputs не дублируются.

## 4. Тот же flow через CLI

Всегда указывайте manifest до команды:

```powershell
.\dl2.bat --manifest path\to\production.toml status
```

Смотрите поле `action`:

- `advance`:

  ```powershell
  .\dl2.bat --manifest path\to\production.toml advance
  ```

- `review`: создайте только человеческий verdict payload:

  ```json
  {
    "outcome": "pass",
    "scope": ["visual", "audio", "constraints"],
    "reviewer": "author",
    "reviewed_at": "2026-07-27T12:00:00Z",
    "findings": []
  }
  ```

  ```powershell
  .\dl2.bat --manifest path\to\production.toml review `
    --verdict path\to\verdict.json
  ```

  Application сам привяжет payload к текущим exact artifact, check report и
  constraints. Их не нужно копировать руками.

- `deliver`:

  ```powershell
  .\dl2.bat --manifest path\to\production.toml deliver `
    --destination-id local.delivery
  ```

  Команда доставляет текущий eligible candidate в `delivery_root` из manifest.
  Она не рендерит и не изменяет frozen package.

После каждого шага снова вызовите `status`. Никаких отдельных `check`,
`preview`, `final`, `package` или `resume` команд в v3 нет.

## 5. Где искать результат

```text
<production>/
  data/.studio/
    objects/       immutable source/evidence/output bytes
    state/         canonical root и head
    outputs/       draft.mp4 и final.mp4
    cache/         rebuildable render cache
  delivery/        exact frozen package после deliver
```

`delivery/` содержит как минимум `video.mp4` и generated `licenses.json`.
Canonical receipt хранится в object store и связан с exact copied manifest.

## 6. Почему release может быть BLOCKED

Наиболее полезная ошибка показывается как `BLOCKED: ...` и код возврата `2`.
Обычные причины:

- authoring ID не совпадает с manifest;
- asset ID отсутствует;
- referenced revision не approved;
- license не разрешает redistribution;
- orientation/constraints не проходят checks;
- workflow ждёт exact review;
- candidate был invalidated или уже не eligible.

Не обходите gate и не меняйте status вручную. Исправьте canonical input:
authoring, asset revision/evidence, verdict или destination condition, затем
повторите текущее действие.

## 7. HTTP API

`serve` жёстко слушает только `127.0.0.1` и открывает только production из
переданного manifest:

```text
GET  /api/v3/status
POST /api/v3/advance
POST /api/v3/review
POST /api/v3/deliver
GET  /api/v3/blobs/{sha256}?size=<bytes>
```

UI использует generated client из `common/dlstudio/webui/src/api/v3.gen.ts`.
CLI и HTTP возвращают одну `WorkflowStatus` projection.

## 8. Проверка разработки

Полный локальный gate:

```powershell
common\dlstudio\.venv\Scripts\python.exe -m tools.studio_v3_verify `
  --profile cutover --scope full --skip-toolchain
```

Web UI:

```powershell
cd common\dlstudio\webui
npm ci
npm run generate:client
npm test
npm run typecheck
npm run build
```

CI настроен запускать full cutover gate на Windows 2022 и Ubuntu 24.04.
