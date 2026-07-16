# Studio v2 — quickstart (полный draft-путь)

Одна страница для холодного старта. Все команды — `dl2`. Движок:
`common/dlstudio`; edit — это Python-пакет с module-level `EDIT`
(`__init__.py` + `beats.py` + `design.py`), на который указывает dotted
module path, например `myreel.edits.main`.

## 0. Проверка окружения

```bash
dl2 doctor          # ffmpeg/ffprobe/python/pydantic — всё должно быть OK
```

## 1. Создать проект

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

Требуется Node 22+ (npx). Подключение: `VideoShot(src="data/infographics/intro_chart.mp4")`
или `Scene(kind="video", ...)`.

## 5. Draft + артефакты ревью

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
```

## 7. Final

```bash
dl2 final myreel.edits.main        # 1080p/upload, −14 LUFS loudnorm
dl2 publish myreel.edits.main      # -> data/publish/youtube_package.md
```

## Пути вывода (сводка)

| Что | Где |
|---|---|
| Побитовые рендеры | `data/finalize/<beat>.mp4` (+ `<beat>_vo_stem.wav`) |
| Собранный ролик | `EDIT.output` (по умолчанию `data/finalize/final.mp4`) |
| Contact sheet / keyframes | `data/review/contact_sheet.jpg`, `data/review/keyframes/` |
| Scratch VO | `data/scratch/<beat>_scratch_tts.wav` |
| HyperFrames-ассеты | `data/infographics/<asset>.mp4` |
| Feedback ревьюеров | `data/review/feedback.json` |
| YouTube-пакет | `data/publish/youtube_package.md` |

Тесты движка (при работе над самим Studio): `dl2 verify --changed`.
