---
name: dl-make-video
description: "Canonical Studio v2 production workflow (CLI dl2) for ALL new video work — devlog, reel, promo, trailer. Triggers on: 'сделай видео', 'сделай девлог', 'сделай рилс/reel', 'сделай промо', 'сделай трейлер', 'make a video', 'make a devlog', 'make a reel', 'promo', 'trailer', /dl-make-video. Full pipeline: изучение проекта → сценарий → edit → scratch VO → assets → dl2 check → dl2 preview (draft + contact sheet) → blind review → безопасные правки (≤3 итераций) → dl2 final → dl2 publish. Никогда не использовать v1-команды."
---

# Производство видео — Studio v2 (`dl2`)

Канонический workflow для **всех** новых роликов: devlog, reel, promo,
trailer. Движок — `common/dlstudio`, CLI — только `dl2`. Легаси-движок v1
для этого workflow **не существует**: любые команды старого v1 CLI
запрещены, fallback-ов на v1 нет. Справка по командам и путям вывода:
`docs/QUICKSTART_V2.md`.

Бюджет (метрики успеха): **не более 2 содержательных вопросов
пользователю** за весь ролик; **не более 3 review-итераций** по умолчанию,
жёсткий максимум — 5.

## 0. Формат и цель

Определи формат из задачи пользователя и создай/открой проект:

| Формат | Ориентация | Длительность | Особенности |
|---|---|---|---|
| devlog | landscape | 2–4 мин, 8–12 beats | музыка + ducking, SFX, разные визуалы, thumbnail/package |
| reel | vertical | 45–60 с | `subtitles=True` на битах, CTA в конце, музыка-драйв |
| promo | landscape или vertical (под площадку) | ~30–90 с | продукт и фичи, быстрый темп |
| trailer | landscape | ~60–120 с | атмосфера, минимум текста, музыка + SFX |

```bash
dl2 doctor                                  # окружение: ffmpeg/ffprobe/python
dl2 new-video <project> --format vertical   # или --format landscape
```

Ориентация задаётся кортежем `Design.resolution` (vertical =
`(1080, 1920)`) — отдельного поля формата в модели нет; `--format` лишь
выбирает resolution в шаблоне. Если проект уже существует — найди edit
(Python-пакет `<project>/edits/<name>/` с module-level `EDIT` в
`__init__.py`) и работай с его dotted path: `<project>.edits.<name>`.

## Workflow — 17 шагов

1. **Прочитать `AGENTS.md` и активный проект.** Правила workspace и
   контекст проекта — до любых действий.
2. **Определить формат и цель** (таблица выше). Создать проект
   `dl2 new-video` или открыть существующий edit.
3. **Изучить проект и готовые assets**: commits, документация,
   `data/footage/`, `data/images/`, `data/music/`, `data/sfx/`,
   `data/infographics/`. Составь список доступного материала — он
   определяет, что реально показать.
4. **Подготовить сценарий**: короткий текст VO по битам + план визуала
   на каждый бит. Открытие (hook) прогони через агента `hook-doctor`
   **до** записи.
5. **Создать/обновить edit.** DSL: `Edit`/`Beat`/`Chunk` живут в
   `<project>/edits/<name>/{__init__,beats,design}.py`; content-примитивы —
   `Plate | Overlay | ImageShot | VideoShot`; фоны — `Scene`; музыка —
   `MusicRegion` в `MIX`; звуковые акценты — `SfxEvent` с якорем-индексом
   слова. Для reel включи на битах `subtitles=True` — фразовые captions
   собираются из words автоматически, стиль — `Design.captions`.
6. **Scratch VO и words**:
   ```bash
   dl2 scratch-tts <project>.edits.<name> b01
   #   -> data/scratch/b01_scratch_tts.wav
   dl2 transcribe data/scratch/b01_scratch_tts.wav data/scratch/b01_words.json
   ```
   Затем **сам пропиши оба пути** в `beats.py` у бита:
   `audio="data/scratch/..."`, `words="data/scratch/..."` — CLI не
   редактирует Python-файлы.
7. **Подключить assets**: пути из `data/footage`, `data/images`,
   `data/music`, `data/sfx` прямо в `beats.py`. Инфографика/моушн — через
   HyperFrames:
   ```bash
   dl2 gen-html <asset> --init      # каркас в data/hyperframes/<asset>/
   dl2 gen-html <asset> --out data/infographics/<asset>.mp4 --quality draft
   ```
   (Node 22+; детерминированные GSAP-таймлайны в `window.__timelines`;
   подключение — `VideoShot(src="data/infographics/<asset>.mp4")`.)
   Нейтральный b-roll при необходимости: `dl2 stock search` /
   `dl2 stock download`.
8. **Запросить отсутствующий footage**, если он обязателен, — по шаблону
   ниже («Запрос недостающего footage») и остановиться на этом бите.
   Остальные биты продолжай.
9. **`dl2 check <project>.edits.<name>`** — список отсутствующих ассетов
   и ошибок = твой TODO. Ошибки блокируют рендер.
10. **Создать draft**:
    ```bash
    dl2 preview <project>.edits.<name>
    ```
    Одна команда = check → рендер устаревших битов (540p draft, кэш) →
    полная сборка с миксом → артефакты ревью. Точечная итерация:
    `dl2 iter <edit> --stale -j 4`; один бит: `dl2 compose <edit> b01`;
    статус кэша: `dl2 beats <edit>`.
11. **Contact sheet / keyframes** — их создаёт `dl2 preview`:
    ```text
    data/finalize/final.mp4            # draft всего ролика (имя из EDIT.output)
    data/review/contact_sheet.jpg      # сетка 4x4 кадров
    data/review/keyframes/kf_NN.jpg    # 8 стоп-кадров
    ```
12. **Blind review**: заспавнить `video-reviewer` на артефактах
    (contact sheet, keyframes, MP4), при наличии голосовых takes —
    `vo-reviewer`. Ревьюеры персистят вердикты в
    `data/review/feedback.json` (через `POST /api/feedback` запущенного
    `dl2 studio`, либо оркестратор пишет файл сам).
13. **Выполнить безопасные исправления** — только из списка «Продолжай
    сам» ниже. Перед применением любого сохранённого вердикта — проверка
    свежести (см. «Защита от stale feedback»).
14. **Повторить** правки → `dl2 preview` → review. **Не более 3 итераций
    по умолчанию, жёсткий максимум 5.** Дальше — стоп и вопрос
    пользователю.
15. **Финальный regression checklist** перед final:
    - `dl2 check` зелёный; в ролике нет placeholder-ассетов;
    - audio/video sync (длительности стримов совпадают с ожидаемой);
    - resolution соответствует `Design.resolution` (vertical final =
      1080×1920);
    - субтитры в safe zone, читаются на целевой платформе;
    - музыка ducking-ует под VO, громкость ровная по битам;
    - hook работает в первые секунды; CTA/концовка на месте;
    - каждый применённый вердикт из `feedback.json` прошёл sha256-проверку.
16. **`dl2 final <project>.edits.<name>`** — 1080p/upload, −14 LUFS
    loudnorm. Если пользователь записал настоящий VO: `dl2 studio <edit>`
    (запись/такейки на `http://127.0.0.1:8788`) или из готового файла —
    `dl2 audio <edit> b01 data/recordings/take.webm`.
17. **Publish package**: `dl2 publish <project>.edits.<name>` →
    `data/publish/youtube_package.md`; затем заспавнить
    `thumbnail-designer` (обложка) и `publish-packager` (titles,
    description, chapters, tags, pre-upload checklist).

## Продолжай сам (не спрашивая пользователя)

- исправлять очевидные опечатки;
- менять `size`;
- менять `opacity`;
- корректировать safe-zone position;
- менять subtitle ratio;
- включать существующий asset;
- менять `style`/`fit`;
- перерендеривать draft;
- запускать review;
- создавать/править HyperFrames-ассеты по конвенции
  (`data/hyperframes/<asset>/` → `dl2 gen-html` →
  `data/infographics/<asset>.mp4`);
- использовать готовые файлы из проекта.

## Остановись и спроси пользователя

- требуется новый настоящий footage;
- требуется финальный VO;
- меняется основной смысл ролика;
- меняется структура ролика;
- требуется split/merge beats;
- необходимо добавить спорный product claim;
- reviewer требует более 5 итераций;
- отсутствует критический asset, который невозможно заменить.

## Запрос недостающего footage

Не пытайся захватывать gameplay сам — это делает отдельный
gameplay/capture agent пользователя. Верни конкретный запрос по шаблону:

```markdown
## Нужен gameplay asset

Beat: combat_upgrade

Что показать:
Персонаж открывает меню улучшений, выбирает огненный модификатор
и применяет его в бою.

Длительность:
8–12 секунд.

Формат:
16:9, минимум 1080p.

Важно:
Должны быть видны выбор модификатора и результат его применения.

Сохранить:
data/footage/combat_fire_upgrade.mp4
```

После появления файла по указанному пути — продолжай производство без
дополнительных вопросов.

## Защита от stale feedback

Каждый вердикт в `data/review/feedback.json` обязан содержать:

```json
{
  "artifact_path": "data/finalize/final.mp4",
  "artifact_sha256": "<sha256 файла на момент ревью>",
  "timestamp": "<ISO>",
  "verdict": "..."
}
```

`artifact_path` — project-relative путь отревьюенного MP4. Studio API
сам заполняет `artifact_sha256`/`timestamp` из `artifact_path` при
`POST /api/feedback`, если они опущены; при прямой записи файла заполняй
их сам.

**Правило свежести**: перед тем как действовать по любому сохранённому
вердикту, пересчитай sha256 текущего файла по `artifact_path`:

```bash
python -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" data/finalize/final.mp4
```

Хэш не совпал с `artifact_sha256` → ревью устарело: **перезапусти review,
не применяй его suggestions.**

## Кому что делегировать

| Агент | Когда | Что даёт |
|---|---|---|
| `video-reviewer` | после каждого draft | разбор визуала по contact sheet / keyframes / MP4, ранжированные правки |
| `vo-reviewer` | после записи takes | вердикт in-final / re-record по каждому take |
| `hook-doctor` | до записи открытия | варианты hook с оценкой, вердикт по твоему драфту |
| `music-supervisor` | перед full-mix | выбор трека + параметры `MusicRegion` (читает `dl2 ir`) |
| `motion-infographic-designer` | нужен новый график/анимация | HyperFrames-ассет в `data/infographics/` + как подключить |
| `thumbnail-designer` | после final | обложка для YouTube |
| `publish-packager` | после final | titles/description/chapters/tags + pre-upload checklist |

## Не делай

- Никаких v1-команд и v1-путей — только `dl2` и пути из
  `docs/QUICKSTART_V2.md`.
- Не редактируй код движка (`common/dlstudio`) в рамках производства
  ролика.
- Не рендерь 4K во время итераций — draft-путь это 540p через
  `dl2 preview` / `dl2 iter`.
- Не выдумывай пути ассетов — подключай только существующие файлы
  (проверяй Glob/Read перед записью в `beats.py`).
- Не превышай бюджет: ≤2 содержательных вопросов, ≤3 review-итераций
  (максимум 5).
