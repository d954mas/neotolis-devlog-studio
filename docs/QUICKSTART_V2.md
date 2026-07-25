# Studio v2 — quickstart (полный draft-путь)

Одна страница для холодного старта. Все команды — `dl2`. Движок:
`common/dlstudio`. Новый рекомендуемый путь — product-first manifests и ссылка
`product_id:production_id`; старые dotted edit paths остаются совместимыми.

## 0. Проверка окружения

```bash
dl2 doctor          # ffmpeg/ffprobe/python/pydantic — всё должно быть OK
```

## 1. Создать product и production

```bash
dl2 new-product not_a_trolley_problem --game-root C:/projects/game-67-idle
dl2 new-production not_a_trolley_problem --kind reel --date 2026-07-18
dl2 list-productions not_a_trolley_problem
```

Получившийся edit адресуется как
`not_a_trolley_problem:2026_07_18_reel_01`. Весь review/finalize/publish
изолирован внутри production, а готовая публикационная папка — внутри общего
product root. Точные дубликаты исходных assets можно безопасно собрать в одно
физическое хранилище, не ломая production paths:

```bash
dl2 dedupe-assets not_a_trolley_problem          # read-only план
dl2 dedupe-assets not_a_trolley_problem --apply  # verified hardlinks + report
```

### Legacy scaffold

```bash
dl2 new-video myreel --format vertical    # или --format landscape
```

Создаёт `<workspace>/myreel/`:

```text
myreel/
  edits/main/            # __init__.py (EDIT), beats.py, design.py
  data/
    audio/  footage/  images/  music/  sfx/  fonts/
    hyperframes/         # исходники HTML-ассетов (dl2 gen-html)
    infographics/        # отрендеренные MP4-ассеты
    finalize/  scratch/
```

Dotted-путь этого edit: `myreel.edits.main`. Ориентация задаётся
`RESOLUTION` в `design.py` (vertical = `(1080, 1920)`) — отдельного поля
формата нет. Положи TTF в `data/fonts/main.ttf` (битый или отсутствующий
шрифт — это ошибка check, не «тихий» фолбэк).

## 2. Сценарий и beats

Правь `myreel/edits/main/beats.py`: тексты VO (`vo=`), чанки
(`Plate/Overlay/ImageShot/VideoShot`), сцены (`Scene`), музыку
(`MusicRegion` в `MIX`), SFX (`SfxEvent`, якорь — индекс слова). Для reel
включи субтитры на бите: `subtitles=True` — фразы собираются из words
автоматически, стиль — `Design.captions`.

```bash
dl2 check myreel.edits.main     # список отсутствующих ассетов = твой TODO
```

## 3. Scratch VO → words

```bash
dl2 scratch-tts myreel.edits.main b01
#   -> data/scratch/b01_scratch_tts.wav
dl2 transcribe data/scratch/b01_scratch_tts.wav data/scratch/b01_words.json
```

Затем пропиши ОБА пути в `beats.py` у бита: `audio="data/scratch/..."`,
`words="data/scratch/..."` (CLI не редактирует Python-файлы — это делаешь
ты).

## 4. Ассеты

Готовые файлы кладутся в `data/footage`, `data/images`, `data/music`,
`data/sfx` и подключаются путями в `beats.py`. Инфографика/моушн:

```bash
dl2 gen-html intro_chart --init        # каркас в data/hyperframes/intro_chart/
# правишь index.html (GSAP-таймлайны в window.__timelines), затем:
dl2 gen-html intro_chart --out data/infographics/intro_chart.mp4 --quality draft
```

Требуется Node 22+ (npx). Подключай сгенерированный MP4 вместе с его
hash-bound manifest — финальный gate заново проверит MP4, HTML, variables и
evidence:

```python
VideoShot(
    src="data/infographics/intro_chart.mp4",
    render_manifest="data/infographics/intro_chart.mp4.render.json",
    editorial_role="presentation",
)
```

### Запись gameplay без ручной склейки шагов

Сначала опиши нужные состояния в `data/plan/capture_requests.json` версии 2.
Для gameplay обязательны одинаковые `state_id` и `scene` (точный id
game-owned capture scene), точный `build_id`, `seed`, ожидаемый semantic hash
и, если сценарию нужно действие, объявленный сценой `action_id`,
`capture_method="realtime_window"`, скорость `1.0`, чистый UI и запас не
меньше 5 секунд с обеих сторон. Затем веди одну сцену одной resumable-командой:

```bash
# Один раз привяжи request к фактическому PID/build/seed/parameters:
python .agents/skills/devlog-record-media/scripts/record_window_realtime.py \
  --pid <game-pid> \
  --probe-requests <production-root>/data/plan/capture_requests.json \
  --request-id <request-id>
dl2 capture-flow <product:production> <request-id>
# внешний recorder выполняет созданный
# data/plan/capture_batches/<request-id>.json
python .agents/skills/devlog-record-media/scripts/record_window_realtime.py \
  --pid <game-pid> \
  --batch <production-root>/data/plan/capture_batches/<request-id>.json \
  --request-id <request-id>
python .agents/skills/devlog-record-media/scripts/validate_gameplay_capture.py \
  --contract <production-root>/data/plan/capture_requests.json \
  --production-root <production-root> \
  --result <production-root>/data/plan/capture_results/<request-id>.json \
  --request-id <request-id> \
  --report <production-root>/data/review/<request-id>-capture-audit.json
dl2 capture-flow <product:production> <request-id> \
  --ingest data/plan/capture_results/<request-id>.json
# после просмотра валидированного клипа — явный авторский checkpoint:
dl2 capture-flow <product:production> <request-id> --approve
```

Recorder создаёт `<clip>.game.json` из ответов
`game.capture_scene.describe/status` и привязывает его SHA-256 к metadata и
`capture_results/<request-id>.json`. Ingest блокирует запись, если сцена перезапустилась,
действие не объявлено, нет semantic/clean-UI capability, отчёт изменился или
длительность MP4 отличается от измеренного реального времени более чем на 3%
(минимальный допуск 0.5 секунды). Одного поля `simulation_rate=1.0` от
рекордера больше недостаточно.

Последний вызов создаёт
`data/plan/capture_snippets/day5_station.py`: готовый `VideoShot` с точными
`asset_id`, state/build/action identity, центрированным anchor и offset после
пятиисекундного head handle. Не переписывай эти поля вручную и не включай
`loop` для gameplay.

## 5. Autopilot preflight + draft

Для product-first production сначала зафиксируй assets и shot contract:

Перед запуском reel заполни созданный шаблон
`data/plan/story_contract.json`: `premise`, `causal_turn`, `payoff`. Затем:

```bash
dl2 autopilot-run not_a_trolley_problem:2026_07_18_reel_01
# автор проверяет один storyboard checkpoint
dl2 autopilot-run not_a_trolley_problem:2026_07_18_reel_01 --resume --human-minutes 8
# один exact-hash blind review
dl2 autopilot-run not_a_trolley_problem:2026_07_18_reel_01 --resume
# create data/publish/publish.json, metadata.md and cover/thumbnail
dl2 autopilot-run not_a_trolley_problem:2026_07_18_reel_01 --resume
```

Run хранится в `data/review/autopilot_run.json`; все stage events получают
один `run_id`. Команда останавливается на первом failed gate и продолжает тот
же run после `--resume`, без polling и повторного command discovery.
После exact review она останавливается на явной границе `awaiting_package`;
следующий resume запускает evidence validation и delivery только после
создания названных checkpoint-файлов пакета.

`inventory` создаёт `data/assets/catalog.json`, `preflight` проверяет approved
script/VO/source/duplicate/pacing/readability и пишет JSON-отчёт, а
`storyboard` создаёт watchable draft и review artifacts. Перед final blockers
должны быть устранены; warning не является автоматическим pass.

Autopilot также создаёт компактные `data/review/review_pack.json` и
`review_pack_sheet.jpg`: exact SHA, границы/длительности shots, source paths,
story contract, видимый HyperFrames-текст, preflight facts и не более 16
маленьких кадров. Reviewer открывает full-resolution только при конкретной
аномалии.

Legacy/низкоуровневый preview остаётся доступен:

```bash
dl2 preview myreel.edits.main
```

Одна команда = check (ошибки блокируют) → рендер только устаревших битов
(540p draft, кэш) → полная сборка с миксом → артефакты:

```text
data/finalize/final.mp4            # draft всего ролика (имя из EDIT.output)
data/review/contact_sheet.jpg      # сетка 4x4 кадров
data/review/keyframes/kf_NN.jpg    # 8 стоп-кадров
```

Точечная итерация: `dl2 iter myreel.edits.main --stale -j 4`; один бит:
`dl2 compose myreel.edits.main b01`; статус кэша: `dl2 beats myreel.edits.main`.

## 6. Запись настоящего VO (опционально)

```bash
dl2 studio myreel.edits.main       # http://127.0.0.1:8788 — запись/такейки
# или из готовой записи:
dl2 audio myreel.edits.main b01 data/recordings/take.webm

# Speech edit выполняет агент автоматически, без авторского чекпоинта:
dl2 speech-edit myreel.edits.main b01 \
  --prepare-plan data/review/b01_speech_edit_plan.json
# агент дополняет plan семантическими cuts и применяет его:
dl2 speech-edit myreel.edits.main b01 data/review/b01_speech_edit_plan.json
dl2 check myreel.edits.main
```

Полный контракт плана, артефакта и перенумерации word-index ссылок:
`docs/SPEECH_EDIT.md`. Вызов без файла плана создаёт только безопасный
baseline и сохраняет повторы. Для удаления повторов агент сначала готовит
hash-bound plan, добавляет семантически обоснованные cuts и применяет его.

## 7. Final

```bash
dl2 final myreel.edits.main        # 1080p/upload, −14 LUFS loudnorm
dl2 publish myreel.edits.main      # -> data/publish/youtube_package.md
dl2 publish-evidence not_a_trolley_problem:2026_07_18_reel_01
# -> data/publish/video.mp4 + exact hash/review evidence
dl2 deliver not_a_trolley_problem:2026_07_18_reel_01
```

`publish-evidence` после exact preflight/review кладёт сам готовый MP4 рядом с
metadata/cover как `data/publish/video.mp4`. На одном диске используется
hardlink без удвоения места; fallback-копия всегда проверяется по SHA-256.

`deliver` идемпотентно собирает exact MP4, `metadata.md`, cover/thumbnail и
`delivery_manifest.json` в `product/delivery/<kind>/<production_id>/` и
проверяет хэши/hashtags.

## Пути вывода (сводка)

| Что | Где |
|---|---|
| Побитовые рендеры | `data/finalize/<beat>.mp4` (+ `<beat>_vo_stem.wav`) |
| Собранный ролик | `EDIT.output` (по умолчанию `data/finalize/final.mp4`) |
| Contact sheet / keyframes | `data/review/contact_sheet.jpg`, `data/review/keyframes/` |
| Scratch VO | `data/scratch/<beat>_scratch_tts.wav` |
| HyperFrames-ассеты | `data/infographics/<asset>.mp4` |
| Feedback ревьюеров | `data/review/feedback.json` |
| Publish-пакет | `data/publish/video.mp4`, `metadata.md`, cover/thumbnail, `publish.json` |

Тесты движка (при работе над самим Studio): `dl2 verify --changed`.
